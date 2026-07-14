"""Compatibility shim. Prefer ``app.services.subscription.attach.match``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_attach_match is deprecated; import from app.services.subscription.attach.match or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.attach.match import *  # noqa: F403
