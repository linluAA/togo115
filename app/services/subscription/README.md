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

## Layout (P2)

```text
subscription/
  api.py              # stable public API
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

Flat modules like ``app.services.subscription_crud`` remain as **shims** that
re-export the new locations. Prefer the package paths or the public API.

## Next

- Stop using private ``_`` imports across packages
- Collapse pure re-export barrels
- Telegram mixin → pipeline (separate domain)
