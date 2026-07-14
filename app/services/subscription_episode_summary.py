"""Compatibility shim. Prefer ``app.services.subscription.episode.summary``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_episode_summary is deprecated; import from app.services.subscription.episode.summary or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.episode.summary import *  # noqa: F403
