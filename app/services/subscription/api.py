"""Stable public API for the subscription domain.

External callers (routers, monitor, Telegram bot/adapters, tests that exercise
end-to-end flows) should import from this module — or from
``app.services.subscription`` which re-exports the same surface.

Internal implementation modules under ``app.services.subscription_*`` remain
available for gradual migration, but new cross-package code should not reach
into private ``_`` helpers.
"""

from __future__ import annotations

from typing import Any

from app.schemas import SubscriptionCreate, SubscriptionUpdate
from app.services.sources.rss_torznab import SearchResult
from app.services.subscription_attach import (
    attach_results_to_matching_subscriptions,
    refresh_rss_sources,
)
from app.services.subscription_create import create_subscription
from app.services.subscription_crud import (
    _active_subscriptions,
    _duplicate_subscription,
    _mark_subscription_checked,
    delete_subscription,
    delete_subscription_by_title,
    delete_subscriptions,
    get_subscription,
    list_subscriptions,
    update_subscription,
)
from app.services.subscription_crud_rows import normalize_subscription
from app.services.subscription_delivery import (
    deliver_resource,
    list_failed_resources,
    retry_failed_resources as _retry_failed_resources_impl,
)
from app.services.subscription_library import sync_subscription_list_with_emby
from app.services.subscription_library_snapshot import _library_snapshot_or_none
from app.services.subscription_recheck import (
    list_due_recheck_resources,
    recheck_pending_115_resources,
)
from app.services.subscription_search import search_and_attach_resources
from app.services.subscription_search_all import search_all_active_subscriptions
from app.services.subscription_tasks import (
    _search_all_background,
    _search_and_attach_resources_guarded,
    _search_semaphore,
    _search_subscription_background,
    schedule_emby_subscription_sync,
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
    # Public
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
    "schedule_search_all_active_subscriptions",
    "schedule_subscription_search",
    "search_all_active_subscriptions",
    "search_and_attach_resources",
    "sync_subscription_list_with_emby",
    "sync_subscriptions_with_emby",
    "update_subscription",
    # Compatibility helpers (prefer not to use from new code)
    "_active_subscriptions",
    "_duplicate_subscription",
    "_library_snapshot_or_none",
    "_mark_subscription_checked",
    "_search_all_background",
    "_search_and_attach_resources_guarded",
    "_search_semaphore",
    "_search_subscription_background",
]
