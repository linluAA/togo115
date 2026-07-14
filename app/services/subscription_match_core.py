"""Compatibility shim. Prefer ``app.services.subscription.match.core``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_match_core is deprecated; import from app.services.subscription.match.core or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.match.core import *  # noqa: F403
