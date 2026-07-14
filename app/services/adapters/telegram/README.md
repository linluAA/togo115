# Telegram adapters package

## Public entry

```python
from app.services.adapters.telegram import TelegramClientAdapter, TelegramBotAdapter
```

## Layout

```text
telegram/
  __init__.py          # TelegramClientAdapter composition + exports
  models.py            # history options / search budget
  pipeline.py          # shared extract pipeline stats/helpers
  monitor.py           # realtime NewMessage listener
  bot/                 # Bot API: polling / commands / callbacks / messages
  session/             # login, dialogs, session config
  history/             # full / fast / recent history search
  scan/                # message link extraction scanner
```

## Composition

`TelegramClientAdapter` is an explicit composition of:

- `TelegramSessionMixin`
- `TelegramHistorySearchMixin`
- `TelegramMonitorMixin`
- `TelegramMessageScanner`

`TelegramBotAdapter` composes bot polling/commands/callbacks/messages.

Mixin class names are public for tests and composition clarity; methods that are
implementation details may still use a leading `_`.

## Notes

Flat `app.services.adapters.telegram_*` modules have been removed. Import from
this package (or its submodules) only.
