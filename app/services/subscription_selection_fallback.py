"""Compatibility shim. Prefer ``app.services.subscription.search.selection_fallback``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_selection_fallback is deprecated; import from app.services.subscription.search.selection_fallback or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.search.selection_fallback import *  # noqa: F403
