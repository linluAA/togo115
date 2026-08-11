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
    base = max(2, TELEGRAM_SOURCE_CONCURRENCY)
    try:
        from app.services.adapters.telegram.rate_limit import telegram_request_gate

        interval = float(telegram_request_gate.interval)
        if interval >= 0.8:
            return 1
        if interval >= 0.25:
            return max(1, min(2, base))
        # Low pressure: a slightly wider fan-out fills idle slots faster.
        return max(1, min(3, base + 1))
    except Exception:
        return max(1, base)


def search_semaphore() -> asyncio.Semaphore:
    """Return process/loop-local semaphore, refreshing limit when pressure changes.

    When the desired limit decreases we immediately shrink the semaphore's _value
    so new acquirers see the tighter ceiling.  In-flight holders are unaffected
    but the burst window is capped at the number of already-acquired permits
    rather than the old limit.  When the semaphore is idle (all permits
    available), we rebuild it to avoid accumulating stale state.
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
        # When pressure rises (desired < limit), shrink the existing semaphore
        # immediately rather than waiting for all in-flight holders to drain.
        if (
            current is not None
            and subscription_search_semaphore_loop is loop
            and desired < subscription_search_semaphore_limit
        ):
            # If idle (all permits available), rebuild with the tighter limit.
            if current._value >= subscription_search_semaphore_limit:
                subscription_search_semaphore = asyncio.Semaphore(desired)
                subscription_search_semaphore_loop = loop
                subscription_search_semaphore_limit = desired
                return subscription_search_semaphore
            # Otherwise, shrink in place to preserve in-flight holders.
            current._value = min(current._value, desired)
            subscription_search_semaphore_limit = desired
            return current
        # When pressure eases (desired > limit), rebuild with a higher limit.
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
        # Shrink immediately when pressure rises.
        if (
            current is not None
            and telegram_dialog_semaphore_loop is loop
            and desired < telegram_dialog_semaphore_limit
        ):
            # If idle (all permits available), rebuild with the tighter limit.
            if current._value >= telegram_dialog_semaphore_limit:
                telegram_dialog_semaphore = asyncio.Semaphore(desired)
                telegram_dialog_semaphore_loop = loop
                telegram_dialog_semaphore_limit = desired
                return telegram_dialog_semaphore
            # Otherwise, shrink in place to preserve in-flight holders.
            current._value = min(current._value, desired)
            telegram_dialog_semaphore_limit = desired
            return current
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


# Cap on lock dictionaries: once exceeded, stale entries are evicted.
_MAX_LOCKS = 256


def _evict_stale_locks(locks: dict, max_size: int = _MAX_LOCKS) -> None:
    """Remove locks that are not held (no current waiters) when the dict is too large."""
    if len(locks) <= max_size:
        return
    stale = [key for key, lock in locks.items() if not lock.locked()]
    for key in stale:
        locks.pop(key, None)


def subscription_lock(subscription_id: int) -> asyncio.Lock:
    global subscription_locks, subscription_locks_loop
    loop = asyncio.get_running_loop()
    if subscription_locks_loop is not loop:
        subscription_locks = {}
        subscription_locks_loop = loop
    _evict_stale_locks(subscription_locks)
    sid = int(subscription_id)
    lock = subscription_locks.get(sid)
    if lock is None:
        lock = asyncio.Lock()
        subscription_locks[sid] = lock
    return lock


def telegram_source_lock(source: str) -> asyncio.Lock:
    """Serialize remote work for the same Telegram dialog/source."""
    global telegram_source_locks, telegram_source_locks_loop
    loop = asyncio.get_running_loop()
    if telegram_source_locks_loop is not loop:
        telegram_source_locks = {}
        telegram_source_locks_loop = loop
    _evict_stale_locks(telegram_source_locks)
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
