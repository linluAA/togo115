from __future__ import annotations

"""Application-facing actions for UI/adapters/routers.

Prefer this facade over reaching into subscription package internals.
"""

from typing import Any


async def create_subscription(*args: Any, **kwargs: Any):
    from app.services.subscription import create_subscription as _create

    return await _create(*args, **kwargs)


def delete_subscription(*args: Any, **kwargs: Any):
    from app.services.subscription import delete_subscription as _delete

    return _delete(*args, **kwargs)


def delete_subscriptions(*args: Any, **kwargs: Any):
    from app.services.subscription import delete_subscriptions as _delete

    return _delete(*args, **kwargs)


def delete_subscription_by_title(*args: Any, **kwargs: Any):
    from app.services.subscription import delete_subscription_by_title as _delete

    return _delete(*args, **kwargs)


def get_subscription(*args: Any, **kwargs: Any):
    from app.services.subscription import get_subscription as _get

    return _get(*args, **kwargs)


def list_subscriptions(*args: Any, **kwargs: Any):
    from app.services.subscription import list_subscriptions as _list

    return _list(*args, **kwargs)


def update_subscription(*args: Any, **kwargs: Any):
    from app.services.subscription import update_subscription as _update

    return _update(*args, **kwargs)


async def deliver_resource(*args: Any, **kwargs: Any):
    from app.services.subscription import deliver_resource as _deliver

    return await _deliver(*args, **kwargs)


async def deliver_resource_url(*args: Any, **kwargs: Any):
    from app.services.subscription.delivery.executor import deliver_resource_url as _deliver_url

    return await _deliver_url(*args, **kwargs)


async def attach_results_to_matching_subscriptions(*args: Any, **kwargs: Any):
    from app.services.subscription import attach_results_to_matching_subscriptions as _attach

    return await _attach(*args, **kwargs)


async def retry_failed_resources(*args: Any, **kwargs: Any):
    from app.services.subscription import retry_failed_resources as _retry

    return await _retry(*args, **kwargs)


def list_failed_resources(*args: Any, **kwargs: Any):
    from app.services.subscription import list_failed_resources as _list

    return _list(*args, **kwargs)


def schedule_subscription_search(*args: Any, **kwargs: Any):
    from app.services.subscription import schedule_subscription_search as _schedule

    return _schedule(*args, **kwargs)


def schedule_search_all_active_subscriptions(*args: Any, **kwargs: Any):
    from app.services.subscription import schedule_search_all_active_subscriptions as _schedule

    return _schedule(*args, **kwargs)


def schedule_emby_subscription_sync(*args: Any, **kwargs: Any):
    from app.services.subscription import schedule_emby_subscription_sync as _schedule

    return _schedule(*args, **kwargs)


def telegram_source_lock(source: str):
    from app.services.concurrency import telegram_source_lock as _lock

    return _lock(source)

def schedule_recheck_pending_115(*args, **kwargs):
    from app.services.subscription import schedule_recheck_pending_115 as _schedule

    return _schedule(*args, **kwargs)


def schedule_retry_failed_resources(*args, **kwargs):
    from app.services.subscription import schedule_retry_failed_resources as _schedule

    return _schedule(*args, **kwargs)

