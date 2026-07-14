"""Compatibility shim. Prefer ``app.services.subscription.episode.keys``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_episode_keys is deprecated; import from app.services.subscription.episode.keys or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.episode.keys import *  # noqa: F403
