"""Compatibility shim. Prefer ``app.services.subscription.delivery.service``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_delivery is deprecated; import from app.services.subscription.delivery.service or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.delivery.service import *  # noqa: F403
