from __future__ import annotations

from app.services.subscription.crud.service import active_subscriptions
from app.services.subscription.match.matching import extra_search_keywords, subscription_search_title


def _active_subscription_queries() -> list[str]:
    queries: list[str] = []
    for subscription in active_subscriptions():
        title = subscription_search_title(subscription)
        if not title:
            continue
        queries.append(title)
        for keyword in extra_search_keywords(subscription):
            keyword = str(keyword or "").strip()
            if keyword and keyword != title:
                queries.append(f"{title} {keyword}")
    return queries
