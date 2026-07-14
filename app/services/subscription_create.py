"""Compatibility shim. Prefer ``app.services.subscription.crud.create``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_create is deprecated; import from app.services.subscription.crud.create or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.crud.create import *  # noqa: F403
