"""Compatibility shim. Prefer ``app.services.subscription.attach.queries``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_attach_queries is deprecated; import from app.services.subscription.attach.queries or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.attach.queries import *  # noqa: F403
