"""Compatibility shim. Prefer ``app.services.subscription.resource.matching``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_resource_matching is deprecated; import from app.services.subscription.resource.matching or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.resource.matching import *  # noqa: F403
