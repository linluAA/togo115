"""Compatibility shim. Prefer ``app.services.subscription.episode.explicit``.

This module re-exports the new package path and will be removed in a future cleanup.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "subscription_episode_explicit is deprecated; import from app.services.subscription.episode.explicit or app.services.subscription",
    DeprecationWarning,
    stacklevel=2,
)

from app.services.subscription.episode.explicit import *  # noqa: F403
