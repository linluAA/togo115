"""Resource persistence helpers.

Prefer concrete modules::

    from app.services.subscription.resource.ops import matching_results

Lazy re-exports below avoid circular imports when submodules load each other.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ['best_fallback_result', 'existing_resource_rows', 'fallback_blocked_by_primary_resource', 'fallback_result_candidates', 'insert_resource_safely', 'matching_results', 'resource_already_exists', 'resource_dedupe_key', 'unmatched_results']

_RESOLVE = {'best_fallback_result': 'app.services.subscription.resource.fallback', 'fallback_blocked_by_primary_resource': 'app.services.subscription.resource.fallback', 'fallback_result_candidates': 'app.services.subscription.resource.fallback', 'matching_results': 'app.services.subscription.resource.matching', 'unmatched_results': 'app.services.subscription.resource.matching', 'insert_resource_safely': 'app.services.subscription.resource.ops', 'resource_already_exists': 'app.services.subscription.resource.duplicate', 'existing_resource_rows': 'app.services.subscription.resource.resources', 'resource_dedupe_key': 'app.services.subscription.resource.resources'}


def __getattr__(name: str) -> Any:
    if name not in _RESOLVE:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(_RESOLVE[name]), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
