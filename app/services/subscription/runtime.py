from __future__ import annotations

import asyncio


TELEGRAM_SEARCH_TIMEOUT_SECONDS = 75
RSS_SEARCH_TIMEOUT_SECONDS = 60
SUBSCRIPTION_SEARCH_TIMEOUT_SECONDS = 120
SEARCH_ALL_START_DELAY_SECONDS = 0.35
EMBY_SYNC_START_DELAY_SECONDS = 0.1
SEARCH_ALL_BETWEEN_SUBSCRIPTIONS_DELAY_SECONDS = 0.05
SUBSCRIPTION_SEARCH_CONCURRENCY = 3

search_all_task: asyncio.Task | None = None
emby_sync_task: asyncio.Task | None = None
subscription_search_tasks: dict[int, asyncio.Task] = {}
subscription_search_semaphore: asyncio.Semaphore | None = None
subscription_search_semaphore_loop: asyncio.AbstractEventLoop | None = None
subscription_locks: dict[int, asyncio.Lock] = {}
subscription_locks_loop: asyncio.AbstractEventLoop | None = None


def search_semaphore() -> asyncio.Semaphore:
    global subscription_search_semaphore, subscription_search_semaphore_loop
    loop = asyncio.get_running_loop()
    if subscription_search_semaphore is None or subscription_search_semaphore_loop is not loop:
        subscription_search_semaphore = asyncio.Semaphore(SUBSCRIPTION_SEARCH_CONCURRENCY)
        subscription_search_semaphore_loop = loop
    return subscription_search_semaphore


def subscription_lock(subscription_id: int) -> asyncio.Lock:
    global subscription_locks, subscription_locks_loop
    loop = asyncio.get_running_loop()
    if subscription_locks_loop is not loop:
        subscription_locks = {}
        subscription_locks_loop = loop
    lock = subscription_locks.get(int(subscription_id))
    if lock is None:
        lock = asyncio.Lock()
        subscription_locks[int(subscription_id)] = lock
    return lock
