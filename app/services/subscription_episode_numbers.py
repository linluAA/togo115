"""Compatibility shim. Prefer ``app.services.subscription.episode.numbers``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_episode_numbers is deprecated; import from app.services.subscription.episode.numbers or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.episode.numbers import *  # noqa: F403
