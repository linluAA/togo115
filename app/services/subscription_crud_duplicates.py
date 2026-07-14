"""Compatibility shim. Prefer ``app.services.subscription.crud.duplicates``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_crud_duplicates is deprecated; import from app.services.subscription.crud.duplicates or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.crud.duplicates import *  # noqa: F403
