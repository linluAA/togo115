"""Compatibility shim. Prefer ``app.services.subscription.delivery.executor``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_delivery_executor is deprecated; import from app.services.subscription.delivery.executor or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.delivery.executor import *  # noqa: F403
