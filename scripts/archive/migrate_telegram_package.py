#!/usr/bin/env python3
"""Move flat telegram adapter modules into app.services.adapters.telegram package."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = ROOT / "app" / "services" / "adapters"

# stem -> path under adapters.telegram (relative module parts)
MOVE: dict[str, str] = {
    # keep public entrypoints at package root via special handling
    "telegram_bot": "telegram.bot.adapter",
    "telegram_bot_callbacks": "telegram.bot.callbacks",
    "telegram_bot_commands": "telegram.bot.commands",
    "telegram_bot_messages": "telegram.bot.messages",
    "telegram_bot_polling": "telegram.bot.polling",
    "telegram_button_links": "telegram.scan.button_links",
    "telegram_cursor": "telegram.history.cursor",
    "telegram_dialogs": "telegram.session.dialogs",
    "telegram_history": "telegram.history.search",
    "telegram_history_config": "telegram.history.config",
    "telegram_history_fast": "telegram.history.fast",
    "telegram_history_recent": "telegram.history.recent",
    "telegram_login": "telegram.session.login",
    "telegram_message_candidates": "telegram.scan.message_candidates",
    "telegram_message_context": "telegram.scan.message_context",
    "telegram_message_index": "telegram.scan.message_index",
    "telegram_message_links": "telegram.scan.message_links",
    "telegram_models": "telegram.models",
    "telegram_monitor": "telegram.monitor",
    "telegram_pipeline": "telegram.pipeline",
    "telegram_scanner": "telegram.scan.scanner",
    "telegram_session": "telegram.session.mixin",
    "telegram_session_config": "telegram.session.config",
}


def dst_path(dotted: str) -> Path:
    return ADAPTERS.joinpath(*dotted.split(".")).with_suffix(".py")


def rewrite(text: str) -> str:
    # Rewrite imports of old flat modules to new package paths.
    for old in sorted(MOVE.keys(), key=len, reverse=True):
        new = f"app.services.adapters.{MOVE[old]}"
        text = text.replace(f"app.services.adapters.{old}", new)
    # telegram.py entry module path used as app.services.adapters.telegram
    # becomes package; leave "app.services.adapters.telegram" alone when followed
    # by end or non-underscore continuation carefully handled by MOVE keys first.
    return text


def ensure_inits(path: Path) -> None:
    package_root = ADAPTERS / "telegram"
    for directory in [path.parent, *path.parents]:
        if not str(directory).startswith(str(package_root)):
            break
        init = directory / "__init__.py"
        if not init.exists():
            if directory == package_root:
                continue  # written separately
            init.write_text('"""Telegram adapter subpackage."""\n', encoding="utf-8")


def write_shim(old: str, new_dotted: str) -> None:
    target = f"app.services.adapters.{new_dotted}"
    (ADAPTERS / f"{old}.py").write_text(
        f'"""Compatibility shim. Prefer ``{target}``."""\n'
        f"from {target} import *  # noqa: F403\n",
        encoding="utf-8",
    )


def main() -> None:
    # 1) Move implementation files (not telegram.py yet)
    for old, new in MOVE.items():
        src = ADAPTERS / f"{old}.py"
        if not src.exists():
            if dst_path(new).exists():
                print("skip", old)
                continue
            raise SystemExit(f"missing {src}")
        dst = dst_path(new)
        dst.parent.mkdir(parents=True, exist_ok=True)
        ensure_inits(dst)
        text = rewrite(src.read_text(encoding="utf-8"))
        dst.write_text(text, encoding="utf-8")
        src.unlink()
        write_shim(old, new)
        print(f"moved {old} -> {new}")

    # 2) Create package __init__ from old telegram.py
    entry_src = ADAPTERS / "telegram.py"
    if entry_src.exists() and entry_src.is_file():
        text = entry_src.read_text(encoding="utf-8")
        text = rewrite(text)
        # rewrite relative class imports already absolute
        package_init = ADAPTERS / "telegram" / "__init__.py"
        package_init.parent.mkdir(parents=True, exist_ok=True)
        # Ensure package init exports public adapters
        package_init.write_text(text, encoding="utf-8")
        entry_src.unlink()
        print("package __init__ from telegram.py")

    # 3) Rewrite remaining repo imports
    for path in list((ROOT / "app").rglob("*.py")) + list((ROOT / "tests").rglob("*.py")):
        original = path.read_text(encoding="utf-8")
        updated = rewrite(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            print("rewrote", path.relative_to(ROOT))

    # 4) README
    (ADAPTERS / "telegram" / "README.md").write_text(
        """# Telegram adapters package

## Public entry

```python
from app.services.adapters.telegram import TelegramClientAdapter, TelegramBotAdapter
```

## Layout

```text
telegram/
  __init__.py          # TelegramClientAdapter composition + exports
  models.py
  pipeline.py
  monitor.py
  bot/                 # TG Bot API polling/commands/callbacks/messages
  session/             # login, dialogs, session config
  history/             # full/fast/recent history search
  scan/                # message link extraction / scanner
```

Flat `telegram_*.py` modules under `adapters/` remain as temporary shims.
""",
        encoding="utf-8",
    )
    print("done")


if __name__ == "__main__":
    main()
