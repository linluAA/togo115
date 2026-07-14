"""Compatibility shim. Prefer ``app.services.subscription.library.health``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_health is deprecated; import from app.services.subscription.library.health or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.library.health import *  # noqa: F403
