from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.auth import current_user
from app.schemas import ProxyTestRequest, RssSourceTestRequest, SettingPayload
from app.services.settings_store import export_backup, import_backup, list_settings, save_setting
from app.services.source_stats import list_source_stats
from app.services.sources.rss_torznab import RssTorznabAdapter

router = APIRouter()

@router.get("/api/settings")
async def get_settings(user: dict = Depends(current_user)) -> dict:
    return await asyncio.to_thread(list_settings)


@router.get("/api/backup/export")
async def export_backup_route(user: dict = Depends(current_user)) -> dict:
    return await asyncio.to_thread(export_backup)


@router.post("/api/backup/import")
async def import_backup_route(payload: dict[str, Any], user: dict = Depends(current_user)) -> dict:
    result = await asyncio.to_thread(import_backup, payload)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "备份格式错误")
    return result


@router.put("/api/settings/{key}")
async def put_setting(key: str, payload: SettingPayload, user: dict = Depends(current_user)) -> dict:
    return await asyncio.to_thread(save_setting, key, payload.value)


@router.get("/api/source-stats")
async def source_stats(user: dict = Depends(current_user)) -> list[dict[str, Any]]:
    return await asyncio.to_thread(list_source_stats)


@router.post("/api/rss-sources/test")
async def test_rss_source(payload: RssSourceTestRequest, user: dict = Depends(current_user)) -> dict[str, Any]:
    try:
        return await RssTorznabAdapter().test_source(payload.source, payload.query)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc



@router.post("/api/proxy/test")
async def test_proxy(payload: ProxyTestRequest, user: dict = Depends(current_user)) -> dict[str, Any]:
    proxy_url = str(payload.url or "").strip()
    modules = [str(item).strip() for item in payload.modules if str(item).strip()]
    targets = {
        "github": "https://github.com/",
        "google": "https://www.google.com/generate_204",
    }
    results = {name: await _probe_proxy_target(url, proxy_url) for name, url in targets.items()}
    return {"ok": True, "modules": modules, "results": results}


async def _probe_proxy_target(url: str, proxy_url: str) -> dict[str, Any]:
    if not proxy_url:
        return {"ok": False, "latency_ms": 0, "error": "代理地址为空"}
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(proxy=proxy_url, timeout=12, follow_redirects=True) as client:
            response = await client.get(url)
        return {
            "ok": response.status_code < 500,
            "status_code": response.status_code,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "error": "" if response.status_code < 500 else f"HTTP {response.status_code}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "error": type(exc).__name__,
        }
