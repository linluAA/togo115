"""Compatibility shim. Prefer ``app.services.subscription.delivery.recheck``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_recheck is deprecated; import from app.services.subscription.delivery.recheck or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.delivery.recheck import *  # noqa: F403
