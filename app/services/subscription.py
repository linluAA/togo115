import asyncio
import re

from app.db import add_log, db, json_dumps, json_loads, row_to_dict, utc_now
from app.schemas import SubscriptionCreate, SubscriptionUpdate
from app.services.integrations import EmbyAdapter, Pan115Adapter, SearchResult, TelegramBotAdapter, TelegramClientAdapter, get_setting


MATCH_DROP_RE = re.compile(r"[\W_]+", re.UNICODE)

# Bug 1 fix: 白名单映射，防止动态 SQL 拼接注入
_SUBSCRIPTION_ALLOWED_FIELDS = {
    "title": "title",
    "keywords": "keywords",
    "delivery_mode": "delivery_mode",
    "target_path": "target_path",
    "status": "status",
}

# 优化3: 投递并发度限制
_DELIVER_SEMAPHORE = asyncio.Semaphore(3)


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
        # 优化5: 子串匹配增加最小长度比例校验，防止"黑袍"误匹配"新黑袍纠察队"
        if len(subscription_title) >= 4 and len(item_title) > 0 and subscription_title in item_title:
            if len(subscription_title) >= len(item_title) * 0.5:
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
    add_log("info", "subscription", "创建订阅，后台开始历史消息搜索", {"title": payload.title})
    # 优化7: 创建订阅不阻塞API响应，改为后台任务执行搜索
    asyncio.create_task(search_and_attach_resources(subscription_id))
    return get_subscription(subscription_id) or {}


def update_subscription(subscription_id: int, payload: SubscriptionUpdate) -> dict:
    current = get_subscription(subscription_id)
    if not current:
        raise KeyError("订阅不存在")
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return current
    # Bug 1 fix: 使用白名单映射，显式指定列名，防止 SQL 注入
    sets: list[str] = []
    values: list = []
    for field, col in _SUBSCRIPTION_ALLOWED_FIELDS.items():
        if field in data:
            sets.append(f"{col} = ?")
            values.append(json_dumps(data[field]) if field == "keywords" else data[field])
    if not sets:
        return current
    values.extend([utc_now(), subscription_id])
    with db() as conn:
        conn.execute(f"UPDATE subscriptions SET {', '.join(sets)}, updated_at = ? WHERE id = ?", values)
    add_log("info", "subscription", "订阅已更新", {"id": subscription_id})
    return get_subscription(subscription_id) or {}


def delete_subscription(subscription_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM subscriptions WHERE id = ?", (subscription_id,))
    add_log("info", "subscription", "订阅已取消", {"id": subscription_id})


async def search_and_attach_resources(subscription_id: int) -> list[dict]:
    subscription = get_subscription(subscription_id)
    # Bug 5 fix: 检查订阅是否存在且状态为 active
    if not subscription or subscription.get("status") != "active":
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
        # 优化3: 并发投递新资源，使用 Semaphore 限流
        await _deliver_resources_batch([item["resource_id"] for item in created])
    return created


async def attach_results_to_matching_subscriptions(results: list[SearchResult], message_text: str) -> int:
    subscriptions = [item for item in list_subscriptions() if item["status"] == "active"]
    attached = 0
    resource_ids: list[int] = []
    # 优化4: 使用单一 DB 连接，避免每个订阅开独立连接
    with db() as conn:
        for subscription in subscriptions:
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
    # 优化3: 并发投递
    await _deliver_resources_batch(resource_ids)
    if attached:
        add_log("info", "subscription", "实时监控发现并处理新资源", {"count": attached})
    return attached


async def _deliver_resources_batch(resource_ids: list[int]) -> None:
    """优化3: 并发投递多个资源，使用 Semaphore 限制并发度。"""
    if not resource_ids:
        return

    async def _deliver_one(rid: int) -> None:
        async with _DELIVER_SEMAPHORE:
            await deliver_resource(rid)

    await asyncio.gather(*[_deliver_one(rid) for rid in resource_ids])


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
    # Bug 4 fix: 捕获投递异常，避免网络错误导致资源永远停留在 pending
    try:
        if delivery_mode == "telegram_bot":
            ok = await TelegramBotAdapter().forward_to_bot(resource["url"])
        else:
            ok = await Pan115Adapter().transfer(resource["url"], resource["target_path"])
    except Exception as exc:
        add_log("error", "delivery", "资源投递异常", {"resource_id": resource_id, "error": str(exc)})
        ok = False
    with db() as conn:
        conn.execute("UPDATE resources SET status = ? WHERE id = ?", ("delivered" if ok else "failed", resource_id))
    return ok
