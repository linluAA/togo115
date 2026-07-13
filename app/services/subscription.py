"""
Compatibility facade for legacy imports.

New code should import concrete services directly, for example
subscription_crud, subscription_tasks, subscription_search, subscription_delivery
or subscription_library_snapshot. This module remains to avoid breaking older
call sites and external integrations.
"""

import asyncio
from typing import Any

from app.schemas import SubscriptionCreate, SubscriptionUpdate
from app.services.subscription_crud import (
    normalize_subscription as _normalize_subscription_impl,
    list_subscriptions as _list_subscriptions_impl,
    get_subscription as _get_subscription_impl,
    _active_subscriptions as _active_subscriptions_impl,
    _duplicate_subscription as _duplicate_subscription_impl,
    _mark_subscription_checked as _mark_subscription_checked_impl,
    create_subscription as _create_subscription_impl,
    update_subscription as _update_subscription_impl,
    delete_subscription as _delete_subscription_impl,
    delete_subscriptions as _delete_subscriptions_impl,
    delete_subscription_by_title as _delete_subscription_by_title_impl,
)
from app.services.sources.rss_torznab import SearchResult
from app.services import subscription_runtime as _runtime
from app.services.subscription_delivery import list_failed_resources as _list_failed_resources_impl, retry_failed_resources as _retry_failed_resources_impl, deliver_resource as _deliver_resource_impl
from app.services.subscription_tasks import (
    _search_semaphore as _search_semaphore_impl,
    _search_and_attach_resources_guarded as _search_and_attach_resources_guarded_impl,
    _search_subscription_background as _search_subscription_background_impl,
    schedule_subscription_search as _schedule_subscription_search_impl,
    _search_all_background as _search_all_background_impl,
    schedule_search_all_active_subscriptions as _schedule_search_all_active_subscriptions_impl,
)
from app.services.subscription_search import search_and_attach_resources as _search_and_attach_resources_impl, search_all_active_subscriptions as _search_all_active_subscriptions_impl, attach_results_to_matching_subscriptions as _attach_results_to_matching_subscriptions_impl, refresh_rss_sources as _refresh_rss_sources_impl
from app.services.subscription_library import (
    sync_subscription_list_with_emby,
)
from app.services.subscription_library_snapshot import (
    _library_snapshot_or_none as _library_snapshot_or_none_impl,
)


_search_all_task = _runtime.search_all_task
_subscription_search_tasks = _runtime.subscription_search_tasks
_subscription_search_semaphore = _runtime.subscription_search_semaphore
_subscription_search_semaphore_loop = _runtime.subscription_search_semaphore_loop


def _search_semaphore() -> asyncio.Semaphore:
    return _search_semaphore_impl()


def normalize_subscription(row) -> dict:
    return _normalize_subscription_impl(row)


def list_subscriptions(include_completed: bool = False) -> list[dict]:
    return _list_subscriptions_impl(include_completed)


def get_subscription(subscription_id: int) -> dict | None:
    return _get_subscription_impl(subscription_id)


def _active_subscriptions() -> list[dict]:
    return _active_subscriptions_impl()


async def sync_subscriptions_with_emby(force: bool = False) -> dict:
    return await sync_subscription_list_with_emby(list_subscriptions(include_completed=True), force=force)


def _duplicate_subscription(payload: SubscriptionCreate) -> dict | None:
    return _duplicate_subscription_impl(payload)


def _mark_subscription_checked(subscription_id: int) -> None:
    _mark_subscription_checked_impl(subscription_id)


async def _search_and_attach_resources_guarded(
    subscription_id: int,
    snapshot: dict[str, list[dict[str, Any]]] | None = None,
    *,
    incremental_telegram: bool = False,
) -> list[dict]:
    return await _search_and_attach_resources_guarded_impl(
        subscription_id,
        snapshot,
        incremental_telegram=incremental_telegram,
    )


async def _search_subscription_background(subscription_id: int) -> None:
    await _search_subscription_background_impl(subscription_id)


def schedule_subscription_search(subscription_id: int) -> dict:
    return _schedule_subscription_search_impl(subscription_id)


async def create_subscription(payload: SubscriptionCreate) -> dict:
    return await _create_subscription_impl(payload)


def update_subscription(subscription_id: int, payload: SubscriptionUpdate) -> dict:
    return _update_subscription_impl(subscription_id, payload)


def delete_subscription(subscription_id: int) -> None:
    _delete_subscription_impl(subscription_id)


def delete_subscriptions(subscription_ids: list[int]) -> int:
    return _delete_subscriptions_impl(subscription_ids)


def delete_subscription_by_title(title: str) -> int:
    return _delete_subscription_by_title_impl(title)


def list_failed_resources(limit: int = 100) -> list[dict]:
    return _list_failed_resources_impl(limit)


async def retry_failed_resources(limit: int = 20) -> dict:
    return await _retry_failed_resources_impl(limit, deliver_resource)


async def _library_snapshot_or_none(force: bool = False) -> dict[str, list[dict[str, Any]]] | None:
    return await _library_snapshot_or_none_impl(force=force)


async def search_and_attach_resources(
    subscription_id: int,
    snapshot: dict[str, list[dict[str, Any]]] | None = None,
    *,
    incremental_telegram: bool = False,
) -> list[dict]:
    return await _search_and_attach_resources_impl(
        subscription_id,
        snapshot,
        incremental_telegram=incremental_telegram,
    )


async def search_all_active_subscriptions() -> dict:
    return await _search_all_active_subscriptions_impl()


async def _search_all_background() -> None:
    await _search_all_background_impl()


def schedule_search_all_active_subscriptions() -> dict:
    return _schedule_search_all_active_subscriptions_impl()


async def attach_results_to_matching_subscriptions(
    results: list[SearchResult],
    message_text: str,
    snapshot: dict[str, list[dict[str, Any]]] | None = None,
) -> int:
    return await _attach_results_to_matching_subscriptions_impl(results, message_text, snapshot)


async def refresh_rss_sources(snapshot: dict[str, list[dict[str, Any]]] | None = None) -> dict:
    return await _refresh_rss_sources_impl(snapshot)


async def deliver_resource(resource_id: int) -> bool:
    return await _deliver_resource_impl(resource_id)
