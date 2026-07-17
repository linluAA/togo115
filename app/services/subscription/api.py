"""Stable public API for the subscription domain.

External callers (routers, monitor, Telegram bot/adapters, tests that exercise
end-to-end flows) should import from this module ? or from
``app.services.subscription`` which re-exports the same surface.

Implementation lives under ``app.services.subscription.*`` subpackages.
Do not reach into private ``_`` helpers across package boundaries.
"""

from __future__ import annotations

from app.schemas import SubscriptionCreate, SubscriptionUpdate
from app.services.sources.rss_torznab import SearchResult
from app.services.subscription.attach.service import (
    attach_results_to_matching_subscriptions,
    refresh_rss_sources,
)
from app.services.subscription.crud.create import create_subscription
from app.services.subscription.crud.service import (
    active_subscriptions,
    duplicate_subscription,
    mark_subscription_checked,
    delete_subscription,
    delete_subscription_by_title,
    delete_subscriptions,
    get_subscription,
    list_subscriptions,
    update_subscription,
)
from app.services.subscription.crud.rows import normalize_subscription
from app.services.subscription.delivery.service import (
    deliver_resource,
    list_failed_resources,
    retry_failed_resources as _retry_failed_resources_impl,
)
from app.services.subscription.library.service import sync_subscription_list_with_emby
from app.services.subscription.library.snapshot import library_snapshot_or_none
from app.services.subscription.delivery.recheck import (
    list_due_recheck_resources,
    recheck_pending_115_resources,
)
from app.services.subscription.search.service import search_and_attach_resources
from app.services.subscription.search.all import search_all_active_subscriptions
from app.services.subscription.search.tasks import (
    schedule_emby_subscription_sync,
    schedule_recheck_pending_115,
    schedule_retry_failed_resources,
    schedule_search_all_active_subscriptions,
    schedule_subscription_search,
)


async def retry_failed_resources(limit: int = 20) -> dict:
    """Retry failed deliveries using the domain deliver_resource entrypoint."""
    return await _retry_failed_resources_impl(limit, deliver_resource)


async def sync_subscriptions_with_emby(force: bool = False) -> dict:
    """Sync all subscriptions (including completed) against Emby library state."""
    return await sync_subscription_list_with_emby(
        list_subscriptions(include_completed=True),
        force=force,
    )


__all__ = [
    "SearchResult",
    "SubscriptionCreate",
    "SubscriptionUpdate",
    "attach_results_to_matching_subscriptions",
    "create_subscription",
    "delete_subscription",
    "delete_subscription_by_title",
    "delete_subscriptions",
    "deliver_resource",
    "get_subscription",
    "list_due_recheck_resources",
    "list_failed_resources",
    "list_subscriptions",
    "normalize_subscription",
    "recheck_pending_115_resources",
    "refresh_rss_sources",
    "retry_failed_resources",
    "schedule_emby_subscription_sync",
    "schedule_recheck_pending_115",
    "schedule_retry_failed_resources",
    "schedule_search_all_active_subscriptions",
    "schedule_subscription_search",
    "search_all_active_subscriptions",
    "search_and_attach_resources",
    "sync_subscription_list_with_emby",
    "sync_subscriptions_with_emby",
    "update_subscription",
    "active_subscriptions",
    "duplicate_subscription",
    "library_snapshot_or_none",
    "mark_subscription_checked",
]
