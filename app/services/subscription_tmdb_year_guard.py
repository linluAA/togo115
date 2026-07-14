"""Compatibility shim. Prefer ``app.services.subscription.match.tmdb_year_guard``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_tmdb_year_guard is deprecated; import from app.services.subscription.match.tmdb_year_guard or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.match.tmdb_year_guard import *  # noqa: F403
