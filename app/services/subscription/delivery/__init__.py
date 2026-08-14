"""Delivery service.

Prefer concrete modules::

    from app.services.subscription.delivery.service import deliver_resource

Lazy re-exports below avoid circular imports when submodules load each other.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ['deliver_resource', 'deliver_resource_url', 'delivery_failed_status', 'list_failed_resources', 'retry_failed_resources']

_RESOLVE = {'deliver_resource': 'app.services.subscription.delivery.service', 'list_failed_resources': 'app.services.subscription.delivery.service', 'retry_failed_resources': 'app.services.subscription.delivery.service', 'deliver_resource_url': 'app.services.subscription.delivery.executor', 'delivery_failed_status': 'app.services.subscription.delivery.state'}


def __getattr__(name: str) -> Any:
    if name not in _RESOLVE:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(_RESOLVE[name]), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))