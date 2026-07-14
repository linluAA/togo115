"""Compatibility shim. Prefer ``app.services.subscription.delivery.link_validation``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_link_validation is deprecated; import from app.services.subscription.delivery.link_validation or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.delivery.link_validation import *  # noqa: F403
