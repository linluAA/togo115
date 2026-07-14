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

`app.services.subscription.api` is the stable surface.  
`app.services.subscription` (this package) re-exports it.

## Compatibility

- Legacy module path `app.services.subscription` **as a single file** is gone;
  imports of `app.services.subscription` now resolve to this package.
- Old flat modules (`subscription_crud.py`, `subscription_tasks.py`, …) still
  exist and hold implementation. Internal code may keep using them until later
  phases move files into subpackages.
- Prefer the public API above for routers, monitor, Telegram bot, and new code.

## Next phases (not done yet)

1. Move match / search / delivery files into subpackages under this directory.
2. Stop cross-module imports of `_private` helpers.
3. Replace Telegram mixin chains with an explicit pipeline.
