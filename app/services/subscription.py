from app.db import add_log, db, json_dumps, json_loads, row_to_dict, utc_now
from app.schemas import SubscriptionCreate, SubscriptionUpdate
from app.services.integrations import Pan115Adapter, SearchResult, TelegramBotAdapter, TelegramClientAdapter, get_setting


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


async def search_and_attach_resources(subscription_id: int) -> list[dict]:
    subscription = get_subscription(subscription_id)
    if not subscription:
        return []
    client = TelegramClientAdapter()
    results = await client.search_history(subscription["title"], subscription["keywords"])
    created = []
    with db() as conn:
        for result in results:
            exists = conn.execute("SELECT id FROM resources WHERE url = ? AND subscription_id = ?", (result.url, subscription_id)).fetchone()
            if exists:
                continue
            cursor = conn.execute(
                "INSERT INTO resources (subscription_id, source, title, url, message_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (subscription_id, result.source, result.title, result.url, result.message_id, utc_now()),
            )
            created.append({**result.__dict__, "resource_id": cursor.lastrowid})
        conn.execute("UPDATE subscriptions SET last_checked_at = ?, updated_at = ? WHERE id = ?", (utc_now(), utc_now(), subscription_id))
    if created:
        add_log("info", "subscription", "发现新的 115 资源链接", {"id": subscription_id, "count": len(created)})
        for item in created:
            await deliver_resource(item["resource_id"])
    return created


async def attach_results_to_matching_subscriptions(results: list[SearchResult], message_text: str) -> int:
    subscriptions = [item for item in list_subscriptions() if item["status"] == "active"]
    attached = 0
    resource_ids: list[int] = []
    for subscription in subscriptions:
        haystack = f"{message_text}\n{subscription['title']}".lower()
        keywords = [subscription["title"], *subscription.get("keywords", [])]
        if not any(keyword and keyword.lower() in haystack for keyword in keywords):
            continue
        with db() as conn:
            for result in results:
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
