"""Subscription domain package.

Prefer::

    from app.services.subscription import create_subscription, schedule_subscription_search

Implementation remains in ``app.services.subscription_*`` modules for now;
this package is the stable public surface (P0/P1 facade).
"""

from app.services.subscription.api import *  # noqa: F403
from app.services.subscription.api import __all__

__all__ = list(__all__)
