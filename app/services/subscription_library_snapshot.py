"""Compatibility shim. Prefer ``app.services.subscription.library.snapshot``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_library_snapshot is deprecated; import from app.services.subscription.library.snapshot or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.library.snapshot import *  # noqa: F403
