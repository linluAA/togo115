"""Subscription domain package.

Prefer::

    from app.services.subscription import create_subscription, schedule_subscription_search

Public names are resolved lazily so importing a deep submodule
(e.g. ``subscription.delivery.executor``) does not pull the full API graph
and create circular imports with Telegram adapters.
"""

from __future__ import annotations

from typing import Any

# Keep in sync with subscription.api.__all__
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
    "schedule_search_all_active_subscriptions",
    "schedule_subscription_search",
    "search_all_active_subscriptions",
    "search_and_attach_resources",
    "sync_subscription_list_with_emby",
    "sync_subscriptions_with_emby",
    "update_subscription",
    "_active_subscriptions",
    "_duplicate_subscription",
    "_library_snapshot_or_none",
    "_mark_subscription_checked",
    "_search_all_background",
    "_search_and_attach_resources_guarded",
    "_search_semaphore",
    "_search_subscription_background",
]


def __getattr__(name: str) -> Any:
    if name == "runtime":
        from importlib import import_module

        return import_module("app.services.subscription.runtime")
    if name in __all__:
        from importlib import import_module

        api = import_module("app.services.subscription.api")
        return getattr(api, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__) | {"runtime"})
