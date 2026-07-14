"""Compatibility shim. Prefer ``app.services.subscription.search.selection_logs``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_selection_logs is deprecated; import from app.services.subscription.search.selection_logs or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.search.selection_logs import *  # noqa: F403
