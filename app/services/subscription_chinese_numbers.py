"""Compatibility shim. Prefer ``app.services.subscription.episode.chinese_numbers``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_chinese_numbers is deprecated; import from app.services.subscription.episode.chinese_numbers or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.episode.chinese_numbers import *  # noqa: F403
