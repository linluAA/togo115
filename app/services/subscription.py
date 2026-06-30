import re

from app.db import add_log, db, json_dumps, json_loads, row_to_dict, utc_now
from app.schemas import SubscriptionCreate, SubscriptionUpdate
from app.services.integrations import EmbyAdapter, Pan115Adapter, SearchResult, TelegramBotAdapter, TelegramClientAdapter, get_setting


MATCH_DROP_RE = re.compile(r"[\W_]+", re.UNICODE)


def normalize_subscription(row) -> dict:
    item = row_to_dict(row) or {}
    item["keywords"] = json_loads(item.get("keywords"), [])
    item["in_library"] = bool(item.get("in_library"))
    return item


def list_subscriptions() -> list[dict]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM subscriptions ORDER BY created_at DESC").fetchall()
    return [normalize_subscription(row) for row in rows]


def get_subscription(subscription_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)).fetchone()
    return normalize_subscription(row) if row else None


def _compact_match_text(value: str | None) -> str:
    return MATCH_DROP_RE.sub("", str(value or "").casefold())


def _match_term(term: str | None) -> tuple[str, str] | None:
    raw = str(term or "").strip()
    compact = _compact_match_text(raw)
    if not raw or not compact:
        return None
    return raw.casefold(), compact


def _term_in_text(term: tuple[str, str], raw_haystack: str, compact_haystack: str) -> bool:
    raw_term, compact_term = term
    return raw_term in raw_haystack or compact_term in compact_haystack


def _subscription_required_terms(subscription: dict) -> tuple[tuple[str, str] | None, list[tuple[str, str]]]:
    title_term = _match_term(subscription.get("title"))
    seen = {title_term[1]} if title_term else set()
    keyword_terms: list[tuple[str, str]] = []
    for keyword in subscription.get("keywords") or []:
        term = _match_term(keyword)
        if not term or len(term[1]) < 2 or term[1] in seen:
            continue
        seen.add(term[1])
        keyword_terms.append(term)
    return title_term, keyword_terms


def result_matches_subscription(subscription: dict, result: SearchResult, *extra_texts: str) -> bool:
    text = "\n".join(
        part
        for part in [getattr(result, "context", ""), result.title, *extra_texts]
        if part
    )
    if not text:
        return False
    raw_haystack = text.casefold()
    compact_haystack = _compact_match_text(text)
    title_term, keyword_terms = _subscription_required_terms(subscription)
    if not title_term or not _term_in_text(title_term, raw_haystack, compact_haystack):
        return False
    return all(_term_in_text(term, raw_haystack, compact_haystack) for term in keyword_terms)


def _emby_provider_tmdb_id(item: dict) -> str:
    provider_ids = item.get("ProviderIds") or {}
    for key in ("Tmdb", "TMDB", "TheMovieDb"):
        value = provider_ids.get(key)
        if value:
            return str(value)
    return ""


def _emby_names(item: dict) -> list[str]:
    names = [item.get("Name"), item.get("OriginalTitle"), item.get("SortName"), item.get("SeriesName")]
    return [str(name).strip() for name in names if name]


def _emby_item_matches(subscription: dict, item: dict) -> bool:
    subscription_tmdb_id = str(subscription.get("tmdb_id") or "")
    item_tmdb_id = _emby_provider_tmdb_id(item)
    if subscription_tmdb_id and item_tmdb_id and subscription_tmdb_id == item_tmdb_id:
        return True
    subscription_title = _compact_match_text(subscription.get("title"))
    if not subscription_title:
        return False
    for name in _emby_names(item):
        item_title = _compact_match_text(name)
        if item_title == subscription_title:
            return True
        if len(subscription_title) >= 4 and subscription_title in item_title:
            return True
    return False


async def sync_subscriptions_with_emby() -> dict:
    subscriptions = list_subscriptions()
    if not subscriptions:
        return {"ok": True, "updated": 0, "matched": 0}
    try:
        snapshot = await EmbyAdapter().library_snapshot()
    except Exception as exc:
        add_log("error", "emby", "Emby 订阅入库状态同步失败", {"error": str(exc)})
        return {"ok": False, "updated": 0, "matched": 0, "error": str(exc)}

    movies = snapshot.get("movies", [])
    series = snapshot.get("series", [])
    episodes = snapshot.get("episodes", [])
    episode_count_by_series_id: dict[str, int] = {}
    episode_count_by_series_name: dict[str, int] = {}
    for episode in episodes:
        series_id = str(episode.get("SeriesId") or episode.get("ParentId") or "")
        if series_id:
            episode_count_by_series_id[series_id] = episode_count_by_series_id.get(series_id, 0) + 1
        series_name = _compact_match_text(episode.get("SeriesName"))
        if series_name:
            episode_count_by_series_name[series_name] = episode_count_by_series_name.get(series_name, 0) + 1

    updated = 0
    matched = 0
    now = utc_now()
    with db() as conn:
        for subscription in subscriptions:
            if subscription["media_type"] == "movie":
                match = next((item for item in movies if _emby_item_matches(subscription, item)), None)
                in_library = 1 if match else 0
                emby_count = 1 if match else 0
            else:
                match = next((item for item in series if _emby_item_matches(subscription, item)), None)
                series_id = str(match.get("Id") or "") if match else ""
                emby_count = episode_count_by_series_id.get(series_id, 0)
                if match and not emby_count:
                    for name in _emby_names(match):
                        emby_count = episode_count_by_series_name.get(_compact_match_text(name), 0)
                        if emby_count:
                            break
                if not match and not emby_count:
                    subscription_title = _compact_match_text(subscription.get("title"))
                    for series_name, count in episode_count_by_series_name.items():
                        if (
                            series_name == subscription_title
                            or (len(subscription_title) >= 4 and subscription_title in series_name)
                            or (len(series_name) >= 4 and series_name in subscription_title)
                        ):
                            emby_count = count
                            break
                in_library = 1 if match or emby_count else 0
            if in_library:
                matched += 1
            if subscription.get("in_library") == bool(in_library) and int(subscription.get("emby_count") or 0) == emby_count:
                continue
            conn.execute(
                """
                UPDATE subscriptions
                SET in_library = ?, emby_count = ?, updated_at = ?
                WHERE id = ?
                """,
                (in_library, emby_count, now, subscription["id"]),
            )
            updated += 1
    if updated:
        add_log("info", "emby", "订阅入库状态已同步", {"updated": updated, "matched": matched})
    return {"ok": True, "updated": updated, "matched": matched}


async def create_subscription(payload: SubscriptionCreate) -> dict:
    now = utc_now()
    keywords = payload.keywords or [payload.title]
    with db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO subscriptions
            (title, media_type, tmdb_id, poster_url, overview, keywords, delivery_mode, target_path, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.title,
                payload.media_type,
                payload.tmdb_id,
                payload.poster_url,
                payload.overview,
                json_dumps(keywords),
                payload.delivery_mode,
                payload.target_path,
                now,
                now,
            ),
        )
        subscription_id = cursor.lastrowid
    add_log("info", "subscription", "创建订阅并开始历史消息搜索", {"title": payload.title})
    await search_and_attach_resources(subscription_id)
    return get_subscription(subscription_id) or {}


def update_subscription(subscription_id: int, payload: SubscriptionUpdate) -> dict:
    current = get_subscription(subscription_id)
    if not current:
        raise KeyError("订阅不存在")
    data = payload.model_dump(exclude_unset=True)
    if "keywords" in data:
        data["keywords"] = json_dumps(data["keywords"])
    if not data:
        return current
    sets = ", ".join(f"{key} = ?" for key in data)
    values = list(data.values()) + [utc_now(), subscription_id]
    with db() as conn:
        conn.execute(f"UPDATE subscriptions SET {sets}, updated_at = ? WHERE id = ?", values)
    add_log("info", "subscription", "订阅已更新", {"id": subscription_id})
    return get_subscription(subscription_id) or {}


def delete_subscription(subscription_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM subscriptions WHERE id = ?", (subscription_id,))
    add_log("info", "subscription", "订阅已取消", {"id": subscription_id})


def delete_subscriptions(subscription_ids: list[int]) -> int:
    ids = [int(item) for item in subscription_ids if item]
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with db() as conn:
        cursor = conn.execute(f"DELETE FROM subscriptions WHERE id IN ({placeholders})", ids)
    deleted = cursor.rowcount if cursor.rowcount is not None else 0
    add_log("info", "subscription", "批量取消订阅", {"ids": ids, "deleted": deleted})
    return deleted


async def search_and_attach_resources(subscription_id: int) -> list[dict]:
    subscription = get_subscription(subscription_id)
    if not subscription:
        return []
    client = TelegramClientAdapter()
    results = await client.search_history(subscription["title"], subscription["keywords"])
    matched_results = [result for result in results if result_matches_subscription(subscription, result)]
    created = []
    with db() as conn:
        for result in matched_results:
            exists = conn.execute("SELECT id FROM resources WHERE url = ? AND subscription_id = ?", (result.url, subscription_id)).fetchone()
            if exists:
                continue
            cursor = conn.execute(
                "INSERT INTO resources (subscription_id, source, title, url, message_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (subscription_id, result.source, result.title, result.url, result.message_id, utc_now()),
            )
            created.append({**result.__dict__, "resource_id": cursor.lastrowid})
        conn.execute("UPDATE subscriptions SET last_checked_at = ?, updated_at = ? WHERE id = ?", (utc_now(), utc_now(), subscription_id))
    skipped = len(results) - len(matched_results)
    if skipped:
        add_log("debug", "subscription", "历史搜索结果未匹配订阅标题/关键词，已跳过", {"id": subscription_id, "skipped": skipped})
    if created:
        add_log("info", "subscription", "发现新的 115 资源链接", {"id": subscription_id, "count": len(created)})
        for item in created:
            await deliver_resource(item["resource_id"])
    return created


async def search_all_active_subscriptions() -> dict:
    total = 0
    searched = 0
    for subscription in list_subscriptions():
        if subscription["status"] != "active":
            continue
        results = await search_and_attach_resources(subscription["id"])
        total += len(results)
        searched += 1
    return {"ok": True, "searched": searched, "count": total}


async def attach_results_to_matching_subscriptions(results: list[SearchResult], message_text: str) -> int:
    subscriptions = [item for item in list_subscriptions() if item["status"] == "active"]
    attached = 0
    resource_ids: list[int] = []
    for subscription in subscriptions:
        with db() as conn:
            for result in results:
                if not result_matches_subscription(subscription, result, message_text):
                    continue
                exists = conn.execute("SELECT id FROM resources WHERE url = ? AND subscription_id = ?", (result.url, subscription["id"])).fetchone()
                if exists:
                    continue
                cursor = conn.execute(
                    "INSERT INTO resources (subscription_id, source, title, url, message_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (subscription["id"], result.source, result.title, result.url, result.message_id, utc_now()),
                )
                attached += 1
                resource_ids.append(cursor.lastrowid)
    for resource_id in resource_ids:
        await deliver_resource(resource_id)
    if attached:
        add_log("info", "subscription", "实时监控发现并处理新资源", {"count": attached})
    return attached


async def deliver_resource(resource_id: int) -> bool:
    with db() as conn:
        resource = conn.execute(
            "SELECT r.*, s.target_path FROM resources r JOIN subscriptions s ON s.id = r.subscription_id WHERE r.id = ?",
            (resource_id,),
        ).fetchone()
    if not resource:
        return False
    delivery = get_setting("delivery", {"mode": "115"})
    delivery_mode = delivery.get("mode") or "115"
    if delivery_mode == "telegram_bot":
        ok = await TelegramBotAdapter().forward_to_bot(resource["url"])
    else:
        ok = await Pan115Adapter().transfer(resource["url"], resource["target_path"])
    with db() as conn:
        conn.execute("UPDATE resources SET status = ? WHERE id = ?", ("delivered" if ok else "failed", resource_id))
    return ok
