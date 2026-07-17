from __future__ import annotations


from app.db import add_log, db, json_dumps, utc_now
from app.schemas import SubscriptionCreate, SubscriptionUpdate
from app.services.subscription.crud.create import create_subscription
from app.services.subscription.crud.duplicates import duplicate_subscription
from app.services.subscription.crud.rows import (
    active_subscriptions,
    mark_subscription_checked,
    get_subscription,
    list_subscriptions,
    normalize_subscription,
)
from app.services.subscription.match.matching import (
    compact_match_text,
    normalize_quality_rules,
)

def update_subscription(subscription_id: int, payload: SubscriptionUpdate) -> dict:
    current = get_subscription(subscription_id)
    if not current:
        raise KeyError("订阅不存在")
    data = payload.model_dump(exclude_unset=True)
    if "keywords" in data:
        data["keywords"] = json_dumps(data["keywords"])
    if "quality_rules" in data:
        normalized_rules = normalize_quality_rules(data["quality_rules"])
        data["quality_rules"] = json_dumps(normalized_rules)
    if data.get("status") in ("active", "paused"):
        data["completed_at"] = None
    if data.get("status") == "completed":
        delete_subscription(subscription_id)
        return {"ok": True, "deleted": True, "id": subscription_id}
    if not data:
        return current
    sets = ", ".join(f"{key} = ?" for key in data)
    values = list(data.values()) + [utc_now(), subscription_id]
    with db() as conn:
        conn.execute(f"UPDATE subscriptions SET {sets}, updated_at = ? WHERE id = ?", values)
    add_log("info", "subscription", "订阅已更新", {"id": subscription_id})
    from app.services.subscription.crud.rows import invalidate_subscription_list_cache as _inv_sub_list
    _inv_sub_list()
    return get_subscription(subscription_id) or {}

def delete_subscription(subscription_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM subscriptions WHERE id = ?", (subscription_id,))
    add_log("info", "subscription", "订阅已取消", {"id": subscription_id})

    from app.services.subscription.crud.rows import invalidate_subscription_list_cache as _inv_sub_list
    _inv_sub_list()

def delete_subscriptions(subscription_ids: list[int]) -> int:
    ids = [int(item) for item in subscription_ids if item]
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with db() as conn:
        cursor = conn.execute(f"DELETE FROM subscriptions WHERE id IN ({placeholders})", ids)
    deleted = cursor.rowcount if cursor.rowcount is not None else 0
    add_log("info", "subscription", "批量取消订阅", {"ids": ids, "deleted": deleted})
    from app.services.subscription.crud.rows import invalidate_subscription_list_cache as _inv_sub_list
    _inv_sub_list()
    return deleted

def delete_subscription_by_title(title: str) -> int:
    needle = compact_match_text(title)
    if not needle:
        return 0
    matched_ids: list[int] = []
    for item in list_subscriptions():
        item_title = compact_match_text(item.get("title"))
        if item_title == needle or needle in item_title or item_title in needle:
            matched_ids.append(int(item["id"]))
    return delete_subscriptions(matched_ids)

