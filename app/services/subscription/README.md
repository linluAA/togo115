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
from app.services.subscription.match import result_matches_subscription
from app.services.subscription.delivery import deliver_resource_url
from app.services.subscription.resource import matching_results
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

## Compatibility

Flat modules like `app.services.subscription_crud` remain as **deprecated shims**
(re-export + `DeprecationWarning`). Prefer package paths or the public API.

## Conventions (P3)

- Cross-subpackage helpers used outside their defining module should be
  **public names** (no leading `_`).
- Leading `_` means package-local implementation detail.
- Do not import private helpers from outside `app.services.subscription.*`.

## Next

- Remove flat shims after callers migrate
- Telegram mixin → pipeline (separate domain)
