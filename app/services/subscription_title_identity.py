"""Compatibility shim. Prefer ``app.services.subscription.match.title_identity``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_title_identity is deprecated; import from app.services.subscription.match.title_identity or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.match.title_identity import *  # noqa: F403
