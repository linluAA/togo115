from __future__ import annotations

import asyncio

from app.services.concurrency import (
    SUBSCRIPTION_SEARCH_CONCURRENCY,
    TELEGRAM_SOURCE_CONCURRENCY,
    desired_search_concurrency,
    search_all_wave_size,
    search_semaphore,
    subscription_lock,
    telegram_source_lock,
)

TELEGRAM_SEARCH_TIMEOUT_SECONDS = 75
RSS_SEARCH_TIMEOUT_SECONDS = 60
SUBSCRIPTION_SEARCH_TIMEOUT_SECONDS = 120
SEARCH_ALL_START_DELAY_SECONDS = 0.35
EMBY_SYNC_START_DELAY_SECONDS = 0.1
SEARCH_ALL_BETWEEN_SUBSCRIPTIONS_DELAY_SECONDS = 0.02
SEARCH_ALL_WAVE_STAGGER_SECONDS = 0.05

search_all_task: asyncio.Task | None = None
emby_sync_task: asyncio.Task | None = None
subscription_search_tasks: dict[int, asyncio.Task] = {}

__all__ = [
    "TELEGRAM_SEARCH_TIMEOUT_SECONDS",
    "RSS_SEARCH_TIMEOUT_SECONDS",
    "SUBSCRIPTION_SEARCH_TIMEOUT_SECONDS",
    "SEARCH_ALL_START_DELAY_SECONDS",
    "EMBY_SYNC_START_DELAY_SECONDS",
    "SEARCH_ALL_BETWEEN_SUBSCRIPTIONS_DELAY_SECONDS",
    "SEARCH_ALL_WAVE_STAGGER_SECONDS",
    "SUBSCRIPTION_SEARCH_CONCURRENCY",
    "TELEGRAM_SOURCE_CONCURRENCY",
    "search_all_task",
    "emby_sync_task",
    "subscription_search_tasks",
    "desired_search_concurrency",
    "search_semaphore",
    "subscription_lock",
    "telegram_source_lock",
    "search_all_wave_size",
]
