"""Compatibility shim. Prefer ``app.services.subscription.match.search_terms``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_search_terms is deprecated; import from app.services.subscription.match.search_terms or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.match.search_terms import *  # noqa: F403
