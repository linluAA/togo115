from __future__ import annotations

"""Process-local concurrency primitives used by search/adapters.

Kept outside the subscription package so adapters do not import domain internals.
"""

import asyncio

TELEGRAM_SOURCE_CONCURRENCY = 2
SUBSCRIPTION_SEARCH_CONCURRENCY = 4

telegram_source_locks: dict[str, asyncio.Lock] = {}
telegram_source_locks_loop: asyncio.AbstractEventLoop | None = None
subscription_search_semaphore: asyncio.Semaphore | None = None
subscription_search_semaphore_loop: asyncio.AbstractEventLoop | None = None
subscription_search_semaphore_limit: int = 0
subscription_locks: dict[int, asyncio.Lock] = {}
subscription_locks_loop: asyncio.AbstractEventLoop | None = None
telegram_dialog_semaphore: asyncio.Semaphore | None = None
telegram_dialog_semaphore_loop: asyncio.AbstractEventLoop | None = None
telegram_dialog_semaphore_limit: int = 0


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


def desired_telegram_dialog_concurrency() -> int:
    """Adaptive cross-dialog TG concurrency; same dialog remains serialized by lock."""
    base = TELEGRAM_SOURCE_CONCURRENCY
    try:
        from app.services.adapters.telegram.rate_limit import telegram_request_gate

        interval = float(telegram_request_gate.interval)
        if interval >= 0.8:
            return 1
        if interval >= 0.25:
            return max(1, min(2, base))
        return max(1, base)
    except Exception:
        return max(1, base)


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


def telegram_dialog_search_semaphore() -> asyncio.Semaphore:
    """Cross-dialog TG search ceiling that tracks FloodWait pressure."""
    global telegram_dialog_semaphore, telegram_dialog_semaphore_loop, telegram_dialog_semaphore_limit
    loop = asyncio.get_running_loop()
    desired = desired_telegram_dialog_concurrency()
    if (
        telegram_dialog_semaphore is None
        or telegram_dialog_semaphore_loop is not loop
        or telegram_dialog_semaphore_limit != desired
    ):
        current = telegram_dialog_semaphore
        if (
            current is not None
            and telegram_dialog_semaphore_loop is loop
            and telegram_dialog_semaphore_limit > 0
            and current._value < telegram_dialog_semaphore_limit
        ):
            return current
        telegram_dialog_semaphore = asyncio.Semaphore(desired)
        telegram_dialog_semaphore_loop = loop
        telegram_dialog_semaphore_limit = desired
    return telegram_dialog_semaphore


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
    # When TG pressure is low, launch a slightly wider wave than the hard semaphore
    # so finished tasks immediately fill the next slot.
    desired = desired_search_concurrency()
    if desired >= SUBSCRIPTION_SEARCH_CONCURRENCY:
        return min(desired + 1, 6)
    return desired
