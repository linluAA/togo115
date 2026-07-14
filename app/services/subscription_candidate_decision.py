"""Compatibility shim. Prefer ``app.services.subscription.match.candidate_decision``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_candidate_decision is deprecated; import from app.services.subscription.match.candidate_decision or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.match.candidate_decision import *  # noqa: F403
