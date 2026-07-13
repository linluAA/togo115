from __future__ import annotations

from app.services.subscription_crud import _active_subscriptions
from app.services.subscription_matching import _extra_search_keywords, _subscription_search_title


def _active_subscription_queries() -> list[str]:
    queries: list[str] = []
    for subscription in _active_subscriptions():
        title = _subscription_search_title(subscription)
        if not title:
            continue
        queries.append(title)
        for keyword in _extra_search_keywords(subscription):
            keyword = str(keyword or "").strip()
            if keyword and keyword != title:
                queries.append(f"{title} {keyword}")
    return queries
