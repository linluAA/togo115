"""Compatibility shim. Prefer ``app.services.subscription.library.sync``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_library_sync is deprecated; import from app.services.subscription.library.sync or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.library.sync import *  # noqa: F403
