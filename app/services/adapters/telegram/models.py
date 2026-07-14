from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class TelegramHistoryOptions:
    history_limit: int
    fallback_scan_limit: int
    messages_per_query: int
    total_budget: float
    query_budget: float
    recent_budget: float


class TelegramSearchBudget:
    def __init__(self, seconds: float) -> None:
        self.total = seconds
        self.deadline = time.monotonic() + seconds

    @property
    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def exhausted(self, reserve: float = 0.05) -> bool:
        return self.remaining <= reserve

    def timeout(self, cap: float) -> float:
        return max(0.05, min(cap, self.remaining))
