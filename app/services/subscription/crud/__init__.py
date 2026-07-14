"""CRUD: create/list/update/delete subscriptions.

Prefer concrete modules::

    from app.services.subscription.crud.create import create_subscription

Lazy re-exports below avoid circular imports when submodules load each other.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ['active_subscriptions', 'create_subscription', 'delete_subscription', 'delete_subscription_by_title', 'delete_subscriptions', 'duplicate_subscription', 'get_subscription', 'list_subscriptions', 'mark_subscription_checked', 'normalize_subscription', 'update_subscription']

_RESOLVE = {'create_subscription': 'app.services.subscription.crud.create', 'active_subscriptions': 'app.services.subscription.crud.rows', 'mark_subscription_checked': 'app.services.subscription.crud.rows', 'normalize_subscription': 'app.services.subscription.crud.rows', 'get_subscription': 'app.services.subscription.crud.rows', 'list_subscriptions': 'app.services.subscription.crud.rows', 'duplicate_subscription': 'app.services.subscription.crud.duplicates', 'delete_subscription': 'app.services.subscription.crud.service', 'delete_subscription_by_title': 'app.services.subscription.crud.service', 'delete_subscriptions': 'app.services.subscription.crud.service', 'update_subscription': 'app.services.subscription.crud.service'}


def __getattr__(name: str) -> Any:
    if name not in _RESOLVE:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(_RESOLVE[name]), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
