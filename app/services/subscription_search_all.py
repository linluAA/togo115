"""Compatibility shim. Prefer ``app.services.subscription.search.all``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_search_all is deprecated; import from app.services.subscription.search.all or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.search.all import *  # noqa: F403
