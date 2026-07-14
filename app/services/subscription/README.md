# Subscription domain

## Public entry

```python
from app.services.subscription import (
    create_subscription,
    schedule_subscription_search,
    search_and_attach_resources,
    deliver_resource,
    list_subscriptions,
)
```

Subpackages also expose focused public helpers, e.g.:

```python
from app.services.subscription.match.core import result_matches_subscription
from app.services.subscription.delivery.executor import deliver_resource_url
from app.services.subscription.resource.matching import matching_results
```

## Layout

```text
subscription/
  api.py              # stable public API (lazy via package __init__)
  runtime.py
  crud/               # create/list/update/delete
  episode/            # episode parsing
  match/              # title/year/quality matching
  resource/           # resource rows, dedupe, guards
  library/            # Emby sync / completion
  delivery/           # deliver + 115 recheck
  search/             # TG/RSS search orchestration + tasks
  attach/             # realtime attach to subscriptions
```

## Conventions

- Prefer the package public API above for routers, monitor, bot, and new code.
- Cross-subpackage helpers used outside their defining module should be
  **public names** (no leading `_`).
- Leading `_` means module-local implementation detail.
- Flat `app.services.subscription_*` modules have been removed (P4).

## Next

- Telegram mixin → pipeline (separate domain)
- Optionally collapse pure re-export barrels inside `match/`
