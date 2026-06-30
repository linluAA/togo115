import asyncio
import re
import sqlite3
from typing import Any

from app.db import add_log, db, json_dumps, json_loads, row_to_dict, utc_now
from app.schemas import SubscriptionCreate, SubscriptionUpdate
from app.services.integrations import EmbyAdapter, Pan115Adapter, SearchResult, TelegramBotAdapter, TelegramClientAdapter, TmdbAdapter, get_setting


MATCH_DROP_RE = re.compile(r"[\W_]+", re.UNICODE)
EPISODE_TOKEN_RE = re.compile(
    r"(?i)(?:s(?P<season>\d{1,2})\s*)?e(?:p)?(?P<episode>\d{1,3})(?:\s*(?:-|~|–|—|至|到)\s*(?:e(?:p)?)?(?P<episode_end>\d{1,3}))?"
    r"|第\s*(?P<cn_episode>\d{1,3})\s*[集话話](?:\s*(?:-|~|–|—|至|到)\s*第?\s*(?P<cn_episode_end>\d{1,3})\s*[集话話]?)?"
)
CN_SEASON_EPISODE_RE = re.compile(
    r"第\s*(?P<season>\d{1,2})\s*季.*?第\s*(?P<episode>\d{1,3})\s*[集话話](?:\s*(?:-|~|–|—|至|到)\s*第?\s*(?P<episode_end>\d{1,3})\s*[集话話]?)?",
    re.I,
)
PLAIN_EPISODE_RANGE_RE = re.compile(
    r"(?<![a-z0-9])(?P<start>\d{1,3})\s*(?:-|~|–|—|至|到)\s*(?P<end>\d{1,3})\s*(?:集|话|話|eps?|episodes?)?(?![a-z0-9])",
    re.I,
)
UPDATE_TO_EPISODE_RE = re.compile(r"(?i)(?:更新至|更至|连载至|完结至)\s*(?P<episode>\d{1,3})(?:\s*(?:集|话|話|ep|eps?|episode))?")
EMBY_SNAPSHOT_FAILED: dict[str, list[dict[str, Any]]] = {"__failed__": []}


def normalize_subscription(row) -> dict:
    item = row_to_dict(row) or {}
    item["keywords"] = json_loads(item.get("keywords"), [])
    item["in_library"] = bool(item.get("in_library"))
    item["tmdb_seasons"] = json_loads(item.get("tmdb_seasons"), [])
    item["emby_episode_keys"] = json_loads(item.get("emby_episode_keys"), [])
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


def _result_text(result: SearchResult, *extra_texts: str) -> str:
    return "\n".join(
        part
        for part in [getattr(result, "context", ""), result.title, *extra_texts]
        if part
    )


def _episode_key(season: int | None, episode: int | None) -> tuple[int, int] | None:
    if episode is None or episode <= 0:
        return None
    return (season or 1, episode)


def _episode_key_from_item(item: dict) -> tuple[int, int] | None:
    season = item.get("ParentIndexNumber")
    episode = item.get("IndexNumber")
    try:
        season_number = int(season) if season is not None else 1
        episode_number = int(episode) if episode is not None else None
    except (TypeError, ValueError):
        return None
    return _episode_key(season_number, episode_number)


def _expand_episode_range(season: int | None, start: int, end: int | None = None) -> set[tuple[int, int]]:
    if start <= 0:
        return set()
    end = end or start
    if end < start or end - start > 120:
        return set()
    return {((season or 1), episode) for episode in range(start, end + 1)}


def _json_episode_key(key: tuple[int, int]) -> str:
    return f"{key[0]}x{key[1]}"


def _episode_key_from_json(value: Any) -> tuple[int, int] | None:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return _episode_key(int(value[0]), int(value[1]))
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        match = re.fullmatch(r"(\d+)x(\d+)", value.strip())
        if match:
            return _episode_key(int(match.group(1)), int(match.group(2)))
    return None


def _episode_keys_from_json(value: Any) -> set[tuple[int, int]]:
    if isinstance(value, str):
        value = json_loads(value, [])
    if not isinstance(value, list):
        return set()
    keys = {_episode_key_from_json(item) for item in value}
    return {key for key in keys if key}


def _tmdb_seasons_from_detail(detail: dict) -> list[dict[str, int]]:
    seasons: list[dict[str, int]] = []
    for season in detail.get("seasons") or []:
        try:
            season_number = int(season.get("season_number"))
            episode_count = int(season.get("episode_count") or 0)
        except (TypeError, ValueError):
            continue
        if season_number <= 0 or episode_count <= 0:
            continue
        seasons.append({"season_number": season_number, "episode_count": episode_count})
    return seasons


def _all_tmdb_episode_keys(subscription: dict) -> set[tuple[int, int]]:
    seasons = subscription.get("tmdb_seasons")
    if isinstance(seasons, str):
        seasons = json_loads(seasons, [])
    keys: set[tuple[int, int]] = set()
    if isinstance(seasons, list):
        for season in seasons:
            if not isinstance(season, dict):
                continue
            try:
                season_number = int(season.get("season_number"))
                episode_count = int(season.get("episode_count") or 0)
            except (TypeError, ValueError):
                continue
            if season_number <= 0 or episode_count <= 0:
                continue
            keys.update((season_number, episode) for episode in range(1, episode_count + 1))
    if keys:
        return keys
    total = int(subscription.get("tmdb_total_count") or 0)
    return {(1, episode) for episode in range(1, total + 1)} if total > 0 else set()


def episodes_from_text(text: str) -> set[tuple[int, int]]:
    episodes: set[tuple[int, int]] = set()
    for match in CN_SEASON_EPISODE_RE.finditer(text or ""):
        season = int(match.group("season"))
        start = int(match.group("episode"))
        end_value = match.group("episode_end")
        end = int(end_value) if end_value else start
        episodes.update(_expand_episode_range(season, start, end))
    for match in EPISODE_TOKEN_RE.finditer(text or ""):
        if match.group("episode") or match.group("cn_episode"):
            season = int(match.group("season")) if match.group("season") else 1
            start = int(match.group("episode") or match.group("cn_episode"))
            end_value = match.group("episode_end") or match.group("cn_episode_end")
            end = int(end_value) if end_value else start
            episodes.update(_expand_episode_range(season, start, end))
    if not episodes:
        for match in PLAIN_EPISODE_RANGE_RE.finditer(text or ""):
            start = int(match.group("start"))
            end = int(match.group("end"))
            if start <= end:
                episodes.update(_expand_episode_range(1, start, end))
    if not episodes:
        for match in UPDATE_TO_EPISODE_RE.finditer(text or ""):
            episode = int(match.group("episode"))
            episodes.update(_expand_episode_range(1, episode))
    return episodes


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


def _episode_matches_subscription(subscription: dict, episode: dict, matched_series_id: str = "") -> bool:
    if matched_series_id and str(episode.get("SeriesId") or episode.get("ParentId") or "") == matched_series_id:
        return True
    return _emby_item_matches(subscription, episode)


def _episodes_for_subscription(subscription: dict, episodes: list[dict], matched_series_id: str = "") -> set[tuple[int, int]]:
    owned: set[tuple[int, int]] = set()
    for episode in episodes:
        if not _episode_matches_subscription(subscription, episode, matched_series_id):
            continue
        key = _episode_key_from_item(episode)
        if key:
            owned.add(key)
    return owned


def _subscription_is_complete(subscription: dict, in_library: bool | None = None, emby_count: int | None = None) -> bool:
    media_type = subscription.get("media_type")
    library = bool(subscription.get("in_library")) if in_library is None else bool(in_library)
    count = int(subscription.get("emby_count") or 0) if emby_count is None else int(emby_count or 0)
    if media_type == "movie":
        return library
    expected = _all_tmdb_episode_keys(subscription)
    if expected:
        owned = subscription.get("emby_episodes")
        if not isinstance(owned, set):
            owned = _episode_keys_from_json(subscription.get("emby_episode_keys"))
        return (bool(owned) and expected.issubset(owned)) or count >= len(expected)
    total = int(subscription.get("tmdb_total_count") or 0)
    return bool(total and count >= total)


def _active_subscriptions() -> list[dict]:
    return [item for item in list_subscriptions() if item.get("status") == "active"]


def _emby_configured() -> bool:
    config = get_setting("emby")
    return bool(str(config.get("server_url") or "").strip() and str(config.get("api_key") or "").strip())


def _missing_episode_keys(subscription: dict) -> set[tuple[int, int]]:
    if subscription.get("media_type") != "tv":
        return set()
    expected = _all_tmdb_episode_keys(subscription)
    if not expected:
        return set()
    owned = subscription.get("emby_episodes")
    if not isinstance(owned, set):
        owned = _episode_keys_from_json(subscription.get("emby_episode_keys"))
    return expected - owned


def result_matches_missing_episodes(subscription: dict, result: SearchResult, *extra_texts: str) -> bool:
    if subscription.get("media_type") != "tv":
        return not bool(subscription.get("in_library"))
    if subscription.get("emby_snapshot_failed"):
        return False
    expected = _all_tmdb_episode_keys(subscription)
    if not expected:
        return True
    missing = _missing_episode_keys(subscription)
    if not missing:
        return False
    text = _result_text(result, *extra_texts)
    episodes = episodes_from_text(text)
    if episodes:
        return bool(episodes & missing)
    return False


async def sync_subscriptions_with_emby() -> dict:
    subscriptions = list_subscriptions()
    if not subscriptions:
        return {"ok": True, "updated": 0, "matched": 0}
    if not _emby_configured():
        return {"ok": True, "updated": 0, "matched": 0, "skipped": "emby_not_configured"}
    try:
        snapshot = await EmbyAdapter().library_snapshot()
    except Exception as exc:
        add_log("error", "emby", "Emby 订阅入库状态同步失败", {"error": str(exc)})
        return {"ok": False, "updated": 0, "matched": 0, "error": str(exc)}

    return await sync_subscriptions_with_emby_snapshot(subscriptions, snapshot)


async def sync_subscriptions_with_emby_snapshot(subscriptions: list[dict], snapshot: dict[str, list[dict[str, Any]]]) -> dict:
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
            tmdb_total_count = int(subscription.get("tmdb_total_count") or 0)
            tmdb_seasons = subscription.get("tmdb_seasons") or []
            if subscription.get("media_type") == "tv" and subscription.get("tmdb_id") and (not tmdb_total_count or not tmdb_seasons):
                try:
                    detail = await TmdbAdapter().detail("tv", int(subscription["tmdb_id"]))
                    tmdb_total_count = tmdb_total_count or int(detail.get("number_of_episodes") or 0)
                    tmdb_seasons = _tmdb_seasons_from_detail(detail)
                except Exception as exc:
                    add_log("debug", "tmdb", "同步媒体库时补全总集数失败", {"id": subscription.get("id"), "error": str(exc)})
            if subscription["media_type"] == "movie":
                match = next((item for item in movies if _emby_item_matches(subscription, item)), None)
                in_library = 1 if match else 0
                emby_count = 1 if match else 0
                owned_episodes: set[tuple[int, int]] = set()
            else:
                match = next((item for item in series if _emby_item_matches(subscription, item)), None)
                series_id = str(match.get("Id") or "") if match else ""
                owned_episodes = _episodes_for_subscription(subscription, episodes, series_id)
                emby_count = len(owned_episodes) or episode_count_by_series_id.get(series_id, 0)
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
            enriched = {
                **subscription,
                "tmdb_total_count": tmdb_total_count,
                "tmdb_seasons": tmdb_seasons,
                "emby_episodes": owned_episodes,
                "emby_count": emby_count,
                "in_library": bool(in_library),
            }
            completed = _subscription_is_complete(enriched, bool(in_library), emby_count)
            status = "completed" if completed else ("active" if subscription.get("status") == "completed" else subscription.get("status", "active"))
            completed_at = subscription.get("completed_at")
            if completed and not completed_at:
                completed_at = now
            if not completed:
                completed_at = None
            if in_library:
                matched += 1
            if (
                subscription.get("in_library") == bool(in_library)
                and int(subscription.get("emby_count") or 0) == emby_count
                and int(subscription.get("tmdb_total_count") or 0) == tmdb_total_count
                and subscription.get("tmdb_seasons") == tmdb_seasons
                and subscription.get("emby_episode_keys") == [_json_episode_key(key) for key in sorted(owned_episodes)]
                and subscription.get("status") == status
                and subscription.get("completed_at") == completed_at
            ):
                continue
            conn.execute(
                """
                UPDATE subscriptions
                SET in_library = ?, emby_count = ?, tmdb_total_count = ?, tmdb_seasons = ?,
                    emby_episode_keys = ?, status = ?, completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    in_library,
                    emby_count,
                    tmdb_total_count,
                    json_dumps(tmdb_seasons),
                    json_dumps([_json_episode_key(key) for key in sorted(owned_episodes)]),
                    status,
                    completed_at,
                    now,
                    subscription["id"],
                ),
            )
            updated += 1
    if updated:
        add_log("info", "emby", "订阅入库状态已同步", {"updated": updated, "matched": matched})
    return {"ok": True, "updated": updated, "matched": matched}


async def enrich_subscription_with_library(subscription: dict, snapshot: dict[str, list[dict[str, Any]]] | None = None) -> dict:
    if subscription.get("tmdb_id") and (
        not int(subscription.get("tmdb_total_count") or 0)
        or (subscription.get("media_type") == "tv" and not subscription.get("tmdb_seasons"))
    ):
        try:
            detail = await TmdbAdapter().detail(subscription.get("media_type") or "tv", int(subscription["tmdb_id"]))
            total = int(detail.get("number_of_episodes") or 0)
            tmdb_seasons = _tmdb_seasons_from_detail(detail) if subscription.get("media_type") == "tv" else []
            if total or tmdb_seasons:
                with db() as conn:
                    conn.execute(
                        "UPDATE subscriptions SET tmdb_total_count = ?, tmdb_seasons = ?, updated_at = ? WHERE id = ?",
                        (total, json_dumps(tmdb_seasons), utc_now(), subscription["id"]),
                    )
                subscription = {**subscription, "tmdb_total_count": total, "tmdb_seasons": tmdb_seasons}
        except Exception as exc:
            add_log("debug", "tmdb", "订阅总集数补全失败", {"id": subscription.get("id"), "error": str(exc)})
    if subscription.get("media_type") != "tv":
        return subscription
    if not _emby_configured():
        return subscription
    if snapshot is EMBY_SNAPSHOT_FAILED or (snapshot is not None and "__failed__" in snapshot):
        return {**subscription, "emby_snapshot_failed": True}
    try:
        snapshot = snapshot if snapshot is not None else await EmbyAdapter().library_snapshot()
    except Exception as exc:
        add_log("warning", "emby", "缺集过滤获取 Emby 快照失败，已跳过本轮推送", {"id": subscription.get("id"), "error": str(exc)})
        return {**subscription, "emby_snapshot_failed": True}
    series = snapshot.get("series", [])
    episodes = snapshot.get("episodes", [])
    match = next((item for item in series if _emby_item_matches(subscription, item)), None)
    series_id = str(match.get("Id") or "") if match else ""
    owned_episodes = _episodes_for_subscription(subscription, episodes, series_id)
    enriched = {**subscription, "emby_episodes": owned_episodes, "emby_episode_keys": [_json_episode_key(key) for key in sorted(owned_episodes)]}
    if owned_episodes and len(owned_episodes) != int(subscription.get("emby_count") or 0):
        enriched["emby_count"] = len(owned_episodes)
    return enriched


def _duplicate_subscription(payload: SubscriptionCreate) -> dict | None:
    rows = []
    with db() as conn:
        if payload.tmdb_id is not None:
            row = conn.execute(
                "SELECT * FROM subscriptions WHERE media_type = ? AND tmdb_id = ?",
                (payload.media_type, payload.tmdb_id),
            ).fetchone()
            if row:
                return normalize_subscription(row)
        title = _compact_match_text(payload.title)
        if title:
            rows = conn.execute(
                "SELECT * FROM subscriptions WHERE media_type = ? AND tmdb_id IS NULL",
                (payload.media_type,),
            ).fetchall()
    for row in rows:
        item = normalize_subscription(row)
        if _compact_match_text(item.get("title")) == title:
            return item
    return None


async def _search_subscription_background(subscription_id: int) -> None:
    try:
        await search_and_attach_resources(subscription_id)
    except Exception as exc:
        add_log("error", "subscription", "订阅后台历史搜索失败", {"id": subscription_id, "error": str(exc)})


async def create_subscription(payload: SubscriptionCreate) -> dict:
    existing = _duplicate_subscription(payload)
    if existing:
        add_log("info", "subscription", "订阅已存在，跳过重复创建", {"id": existing.get("id"), "title": existing.get("title")})
        return existing
    now = utc_now()
    keywords = payload.keywords or [payload.title]
    tmdb_total_count = int(payload.tmdb_total_count or 0)
    tmdb_seasons: list[dict[str, int]] = []
    with db() as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO subscriptions
                (title, media_type, tmdb_id, poster_url, overview, keywords, delivery_mode, target_path,
                 tmdb_total_count, tmdb_seasons, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    tmdb_total_count,
                    json_dumps(tmdb_seasons),
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError:
            existing = _duplicate_subscription(payload)
            if existing:
                return existing
            raise
        subscription_id = cursor.lastrowid
    add_log("info", "subscription", "创建订阅，历史消息搜索已进入后台", {"title": payload.title})
    asyncio.create_task(_search_subscription_background(subscription_id))
    return get_subscription(subscription_id) or {}


def update_subscription(subscription_id: int, payload: SubscriptionUpdate) -> dict:
    current = get_subscription(subscription_id)
    if not current:
        raise KeyError("订阅不存在")
    data = payload.model_dump(exclude_unset=True)
    if "keywords" in data:
        data["keywords"] = json_dumps(data["keywords"])
    if data.get("status") in ("active", "paused"):
        data["completed_at"] = None
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


def delete_subscription_by_title(title: str) -> int:
    needle = _compact_match_text(title)
    if not needle:
        return 0
    matched_ids: list[int] = []
    for item in list_subscriptions():
        item_title = _compact_match_text(item.get("title"))
        if item_title == needle or needle in item_title or item_title in needle:
            matched_ids.append(int(item["id"]))
    return delete_subscriptions(matched_ids)


def _insert_resource(conn, subscription_id: int, result: SearchResult) -> dict | None:
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO resources (subscription_id, source, title, url, message_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (subscription_id, result.source, result.title, result.url, result.message_id, utc_now()),
    )
    if cursor.rowcount == 0:
        return None
    return {**result.__dict__, "resource_id": cursor.lastrowid}


async def _library_snapshot_or_none() -> dict[str, list[dict[str, Any]]] | None:
    if not _emby_configured():
        return None
    try:
        return await EmbyAdapter().library_snapshot()
    except Exception as exc:
        add_log("warning", "emby", "Emby 快照获取失败，本轮会跳过需要缺集判断的订阅", {"error": str(exc)})
        return EMBY_SNAPSHOT_FAILED


async def search_and_attach_resources(subscription_id: int, snapshot: dict[str, list[dict[str, Any]]] | None = None) -> list[dict]:
    subscription = get_subscription(subscription_id)
    if not subscription:
        return []
    if subscription.get("status") != "active":
        return []
    subscription = await enrich_subscription_with_library(subscription, snapshot)
    client = TelegramClientAdapter()
    results = await client.search_history(subscription["title"], subscription["keywords"])
    matched_results = [
        result
        for result in results
        if result_matches_subscription(subscription, result)
        and result_matches_missing_episodes(subscription, result)
    ]
    created = []
    with db() as conn:
        for result in matched_results:
            item = _insert_resource(conn, subscription_id, result)
            if item:
                created.append(item)
        conn.execute("UPDATE subscriptions SET last_checked_at = ?, updated_at = ? WHERE id = ?", (utc_now(), utc_now(), subscription_id))
    skipped = len(results) - len(matched_results)
    if skipped:
        add_log("debug", "subscription", "历史搜索结果未匹配订阅标题/关键词/缺集范围，已跳过", {"id": subscription_id, "skipped": skipped})
    if created:
        add_log("info", "subscription", "发现新的 115 资源链接", {"id": subscription_id, "count": len(created)})
        for item in created:
            await deliver_resource(item["resource_id"])
    return created


async def search_all_active_subscriptions() -> dict:
    total = 0
    searched = 0
    subscriptions = _active_subscriptions()
    snapshot = await _library_snapshot_or_none()
    if snapshot is not None and "__failed__" not in snapshot:
        await sync_subscriptions_with_emby_snapshot(subscriptions, snapshot)
        subscriptions = _active_subscriptions()
    for subscription in subscriptions:
        subscription = get_subscription(subscription["id"]) or subscription
        if subscription.get("status") != "active":
            continue
        results = await search_and_attach_resources(subscription["id"], snapshot)
        total += len(results)
        searched += 1
    return {"ok": True, "searched": searched, "count": total}


async def attach_results_to_matching_subscriptions(
    results: list[SearchResult],
    message_text: str,
    snapshot: dict[str, list[dict[str, Any]]] | None = None,
) -> int:
    subscriptions = _active_subscriptions()
    if snapshot is None:
        snapshot = await _library_snapshot_or_none()
    if snapshot is not None and "__failed__" not in snapshot:
        await sync_subscriptions_with_emby_snapshot(subscriptions, snapshot)
        subscriptions = _active_subscriptions()
    attached = 0
    resource_ids: list[int] = []
    for subscription in subscriptions:
        subscription = get_subscription(subscription["id"]) or subscription
        if subscription.get("status") != "active":
            continue
        subscription = await enrich_subscription_with_library(subscription, snapshot)
        with db() as conn:
            for result in results:
                if not result_matches_subscription(subscription, result, message_text):
                    continue
                if not result_matches_missing_episodes(subscription, result, message_text):
                    add_log("debug", "subscription", "实时资源不在缺集范围，已跳过", {"id": subscription["id"], "title": result.title})
                    continue
                item = _insert_resource(conn, subscription["id"], result)
                if not item:
                    continue
                attached += 1
                resource_ids.append(item["resource_id"])
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
