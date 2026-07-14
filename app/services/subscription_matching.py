"""Compatibility shim. Prefer ``app.services.subscription.match.matching``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_matching is deprecated; import from app.services.subscription.match.matching or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.match.matching import *  # noqa: F403
