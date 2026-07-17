from __future__ import annotations

"""Application-facing actions for UI/adapters.

Adapters and routers should import domain operations from here instead of
reaching into subscription package internals.
"""

from typing import Any


async def create_subscription(*args: Any, **kwargs: Any):
    from app.services.subscription import create_subscription as _create

    return await _create(*args, **kwargs)


def delete_subscription(*args: Any, **kwargs: Any):
    from app.services.subscription import delete_subscription as _delete

    return _delete(*args, **kwargs)


def delete_subscription_by_title(*args: Any, **kwargs: Any):
    from app.services.subscription import delete_subscription_by_title as _delete

    return _delete(*args, **kwargs)


def list_subscriptions(*args: Any, **kwargs: Any):
    from app.services.subscription import list_subscriptions as _list

    return _list(*args, **kwargs)


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


def telegram_source_lock(source: str):
    from app.services.concurrency import telegram_source_lock as _lock

    return _lock(source)
