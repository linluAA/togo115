"""Compatibility shim. Prefer ``app.services.subscription.resource.ops``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_resource_ops is deprecated; import from app.services.subscription.resource.ops or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.resource.ops import *  # noqa: F403
