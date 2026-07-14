"""Compatibility shim. Prefer ``app.services.subscription.episode.patterns``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_episode_patterns is deprecated; import from app.services.subscription.episode.patterns or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.episode.patterns import *  # noqa: F403
