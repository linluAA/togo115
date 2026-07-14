"""Compatibility shim. Prefer ``app.services.subscription.match.skip_reasons``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_skip_reasons is deprecated; import from app.services.subscription.match.skip_reasons or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.match.skip_reasons import *  # noqa: F403
