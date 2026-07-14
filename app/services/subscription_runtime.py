"""Compatibility shim. Prefer ``app.services.subscription.runtime``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_runtime is deprecated; import from app.services.subscription.runtime or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.runtime import *  # noqa: F403
