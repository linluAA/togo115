"""Compatibility shim. Prefer ``app.services.subscription.match.text_utils``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_text_utils is deprecated; import from app.services.subscription.match.text_utils or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.match.text_utils import *  # noqa: F403
