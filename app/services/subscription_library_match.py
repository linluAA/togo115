"""Compatibility shim. Prefer ``app.services.subscription.library.match``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_library_match is deprecated; import from app.services.subscription.library.match or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.library.match import *  # noqa: F403
