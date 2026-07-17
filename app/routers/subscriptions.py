from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import current_user
from app.schemas import ResourceBulkDeleteRequest, SearchRequest, SubscriptionBulkDeleteRequest, SubscriptionCreate, SubscriptionUpdate
from app.services.application import (
    create_subscription,
    delete_subscription,
    delete_subscriptions,
    deliver_resource,
    get_subscription,
    list_failed_resources,
    list_subscriptions,
    retry_failed_resources as retry_failed_resources_impl,
    schedule_emby_subscription_sync,
    schedule_search_all_active_subscriptions,
    schedule_subscription_search,
    update_subscription,
)
from app.services.jobs import list_jobs
from app.services.manual_search import manual_search_resources
from app.services.resource_queries import clear_resources, delete_resources, list_recent_resources


router = APIRouter()


@router.get("/api/subscriptions")
async def subscriptions(user: dict = Depends(current_user)) -> list[dict]:
    return await asyncio.to_thread(list_subscriptions)


@router.post("/api/subscriptions/sync-emby")
async def sync_subscription_emby_status(user: dict = Depends(current_user)) -> dict:
    return schedule_emby_subscription_sync()


@router.post("/api/subscriptions/search-all")
async def search_all_subscriptions(user: dict = Depends(current_user)) -> dict:
    return schedule_search_all_active_subscriptions()


@router.post("/api/subscriptions/bulk-delete")
async def bulk_delete_subscriptions(payload: SubscriptionBulkDeleteRequest, user: dict = Depends(current_user)) -> dict:
    deleted = await asyncio.to_thread(delete_subscriptions, payload.ids)
    return {"ok": True, "deleted": deleted}


@router.post("/api/subscriptions")
async def post_subscription(payload: SubscriptionCreate, user: dict = Depends(current_user)) -> dict:
    return await create_subscription(payload)


@router.put("/api/subscriptions/{subscription_id}")
async def put_subscription(subscription_id: int, payload: SubscriptionUpdate, user: dict = Depends(current_user)) -> dict:
    try:
        return await asyncio.to_thread(update_subscription, subscription_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/api/subscriptions/{subscription_id}")
async def remove_subscription(subscription_id: int, user: dict = Depends(current_user)) -> dict:
    await asyncio.to_thread(delete_subscription, subscription_id)
    return {"ok": True}


@router.post("/api/subscriptions/{subscription_id}/search")
async def search_subscription(subscription_id: int, user: dict = Depends(current_user)) -> dict:
    if not await asyncio.to_thread(get_subscription, subscription_id):
        raise HTTPException(status_code=404, detail="订阅不存在")
    return schedule_subscription_search(subscription_id)


@router.get("/api/resources")
async def resources(
    limit: int = Query(80, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict = Depends(current_user),
) -> list[dict]:
    return await asyncio.to_thread(list_recent_resources, limit, offset)


@router.post("/api/resources/bulk-delete")
async def bulk_delete_resources(payload: ResourceBulkDeleteRequest, user: dict = Depends(current_user)) -> dict:
    deleted = await asyncio.to_thread(delete_resources, payload.ids)
    return {"ok": True, "deleted": deleted}


@router.post("/api/resources/clear")
async def clear_recent_resources(user: dict = Depends(current_user)) -> dict:
    deleted = await asyncio.to_thread(clear_resources)
    return {"ok": True, "deleted": deleted}


@router.post("/api/resources/{resource_id}/deliver")
async def post_deliver_resource(resource_id: int, user: dict = Depends(current_user)) -> dict:
    return {"ok": await deliver_resource(resource_id)}


@router.get("/api/jobs")
async def jobs(limit: int = 50, status: str | None = None, user: dict = Depends(current_user)) -> list[dict]:
    return await asyncio.to_thread(list_jobs, limit, status)


@router.get("/api/tasks/failed")
async def failed_tasks(user: dict = Depends(current_user)) -> list[dict]:
    return await asyncio.to_thread(list_failed_resources)


@router.post("/api/tasks/retry-failed")
async def retry_failed_tasks(user: dict = Depends(current_user)) -> dict:
    return await retry_failed_resources_impl(20, deliver_resource)


@router.post("/api/search")
async def manual_search(payload: SearchRequest, user: dict = Depends(current_user)) -> dict:
    return await manual_search_resources(payload)
