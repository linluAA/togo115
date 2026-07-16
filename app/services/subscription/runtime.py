from __future__ import annotations

import asyncio


TELEGRAM_SEARCH_TIMEOUT_SECONDS = 75
RSS_SEARCH_TIMEOUT_SECONDS = 60
SUBSCRIPTION_SEARCH_TIMEOUT_SECONDS = 120
SEARCH_ALL_START_DELAY_SECONDS = 0.35
EMBY_SYNC_START_DELAY_SECONDS = 0.1
SEARCH_ALL_BETWEEN_SUBSCRIPTIONS_DELAY_SECONDS = 0.02
SEARCH_ALL_WAVE_STAGGER_SECONDS = 0.05
SUBSCRIPTION_SEARCH_CONCURRENCY = 3
TELEGRAM_SOURCE_CONCURRENCY = 1

search_all_task: asyncio.Task | None = None
emby_sync_task: asyncio.Task | None = None
subscription_search_tasks: dict[int, asyncio.Task] = {}
subscription_search_semaphore: asyncio.Semaphore | None = None
subscription_search_semaphore_loop: asyncio.AbstractEventLoop | None = None
subscription_search_semaphore_limit: int = 0
subscription_locks: dict[int, asyncio.Lock] = {}
subscription_locks_loop: asyncio.AbstractEventLoop | None = None
telegram_source_locks: dict[str, asyncio.Lock] = {}
telegram_source_locks_loop: asyncio.AbstractEventLoop | None = None


def desired_search_concurrency() -> int:
    """Adaptive subscription concurrency from recent FloodWait pressure."""
    concurrency = SUBSCRIPTION_SEARCH_CONCURRENCY
    try:
        from app.services.adapters.telegram.rate_limit import telegram_request_gate

        interval = float(telegram_request_gate.interval)
        if interval >= 0.8:
            concurrency = 1
        elif interval >= 0.25:
            concurrency = 2
        else:
            concurrency = SUBSCRIPTION_SEARCH_CONCURRENCY
    except Exception:
        concurrency = SUBSCRIPTION_SEARCH_CONCURRENCY
    return max(1, int(concurrency))


def search_semaphore() -> asyncio.Semaphore:
    """Return process/loop-local semaphore, refreshing limit when pressure changes.

    asyncio.Semaphore cannot shrink in-flight holders, so when the desired limit
    decreases we only create a tighter ceiling for new acquirers after all current
    holders release the previous instance. When pressure eases we rebuild with a
    higher limit on the next call after the previous object is idle enough, or
    immediately when nobody holds it.
    """
    global subscription_search_semaphore, subscription_search_semaphore_loop, subscription_search_semaphore_limit
    loop = asyncio.get_running_loop()
    desired = desired_search_concurrency()
    if (
        subscription_search_semaphore is None
        or subscription_search_semaphore_loop is not loop
        or subscription_search_semaphore_limit != desired
    ):
        current = subscription_search_semaphore
        # If the existing semaphore still has holders, keep it until free when
        # shrinking/expanding would race with in-flight work.
        if (
            current is not None
            and subscription_search_semaphore_loop is loop
            and subscription_search_semaphore_limit > 0
            and current._value < subscription_search_semaphore_limit
        ):
            return current
        subscription_search_semaphore = asyncio.Semaphore(desired)
        subscription_search_semaphore_loop = loop
        subscription_search_semaphore_limit = desired
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


def telegram_source_lock(source: str) -> asyncio.Lock:
    """Serialize remote work for the same Telegram dialog/source."""
    global telegram_source_locks, telegram_source_locks_loop
    loop = asyncio.get_running_loop()
    if telegram_source_locks_loop is not loop:
        telegram_source_locks = {}
        telegram_source_locks_loop = loop
    key = str(source or "").strip() or "_unknown_"
    lock = telegram_source_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        telegram_source_locks[key] = lock
    return lock


def search_all_wave_size() -> int:
    """How many subscriptions to launch per wave during search-all."""
    return desired_search_concurrency()
