#!/usr/bin/env python3
"""One-shot P2 migration: move flat subscription_* modules into package subdirs."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "app" / "services"

# old module stem -> new dotted path under app.services
MOVE: dict[str, str] = {
    "subscription_runtime": "subscription.runtime",
    "subscription_create": "subscription.crud.create",
    "subscription_crud": "subscription.crud.service",
    "subscription_crud_duplicates": "subscription.crud.duplicates",
    "subscription_crud_rows": "subscription.crud.rows",
    "subscription_chinese_numbers": "subscription.episode.chinese_numbers",
    "subscription_episode_explicit": "subscription.episode.explicit",
    "subscription_episode_keys": "subscription.episode.keys",
    "subscription_episode_numbers": "subscription.episode.numbers",
    "subscription_episode_packs": "subscription.episode.packs",
    "subscription_episode_parser": "subscription.episode.parser",
    "subscription_episode_patterns": "subscription.episode.patterns",
    "subscription_episode_summary": "subscription.episode.summary",
    "subscription_match_core": "subscription.match.core",
    "subscription_matching": "subscription.match.matching",
    "subscription_identity": "subscription.match.identity",
    "subscription_quality": "subscription.match.quality",
    "subscription_skip_reasons": "subscription.match.skip_reasons",
    "subscription_text_utils": "subscription.match.text_utils",
    "subscription_title_identity": "subscription.match.title_identity",
    "subscription_tmdb_year_guard": "subscription.match.tmdb_year_guard",
    "subscription_source_identity": "subscription.match.source_identity",
    "subscription_candidate_decision": "subscription.match.candidate_decision",
    "subscription_result_utils": "subscription.match.result_utils",
    "subscription_search_terms": "subscription.match.search_terms",
    "subscription_resources": "subscription.resource.resources",
    "subscription_resource_ops": "subscription.resource.ops",
    "subscription_resource_duplicate": "subscription.resource.duplicate",
    "subscription_resource_fallback": "subscription.resource.fallback",
    "subscription_resource_guard": "subscription.resource.guard",
    "subscription_resource_matching": "subscription.resource.matching",
    "subscription_library": "subscription.library.service",
    "subscription_library_match": "subscription.library.match",
    "subscription_library_snapshot": "subscription.library.snapshot",
    "subscription_library_state": "subscription.library.state",
    "subscription_library_sync": "subscription.library.sync",
    "subscription_health": "subscription.library.health",
    "subscription_delivery": "subscription.delivery.service",
    "subscription_delivery_executor": "subscription.delivery.executor",
    "subscription_delivery_state": "subscription.delivery.state",
    "subscription_link_validation": "subscription.delivery.link_validation",
    "subscription_recheck": "subscription.delivery.recheck",
    "subscription_search": "subscription.search.service",
    "subscription_search_all": "subscription.search.all",
    "subscription_search_flow": "subscription.search.flow",
    "subscription_discovery": "subscription.search.discovery",
    "subscription_selection": "subscription.search.selection",
    "subscription_selection_fallback": "subscription.search.selection_fallback",
    "subscription_selection_logs": "subscription.search.selection_logs",
    "subscription_tasks": "subscription.search.tasks",
    "subscription_attach": "subscription.attach.service",
    "subscription_attach_match": "subscription.attach.match",
    "subscription_attach_queries": "subscription.attach.queries",
}


def new_path(dotted: str) -> Path:
    # app.services.<dotted> -> path
    parts = dotted.split(".")
    return SERVICES.joinpath(*parts).with_suffix(".py")


def rewrite_imports(text: str) -> str:
    # longest keys first to avoid partial replacements
    for old in sorted(MOVE.keys(), key=len, reverse=True):
        new = MOVE[old]
        text = text.replace(f"app.services.{old}", f"app.services.{new}")
        # from app.services import subscription_runtime
        text = re.sub(
            rf"(from\s+app\.services\s+import\s+){re.escape(old)}\b",
            rf"\1{new.split('.')[-1]}  # moved; use app.services.{new}",
            text,
        )
        # Path("app/services/subscription_xxx.py") style references in tests
        text = text.replace(
            f"app/services/{old}.py",
            f"app/services/{new.replace('.', '/')}.py",
        )
    # Fix "from app.services import runtime" style after naive rename of subscription_runtime
    # Prefer explicit package imports for runtime.
    text = text.replace(
        "from app.services import runtime  # moved; use app.services.subscription.runtime",
        "from app.services.subscription import runtime as subscription_runtime",
    )
    text = text.replace(
        "from app.services import subscription_runtime",
        "from app.services.subscription import runtime as subscription_runtime",
    )
    # Common alias usage after move: import module as runtime stays valid via shim.
    return text


def write_shim(old_stem: str, new_dotted: str) -> None:
    shim = SERVICES / f"{old_stem}.py"
    # Prefer explicit re-export of public names via import *
    content = (
        f'"""Compatibility shim. Prefer ``app.services.{new_dotted}``."""\n'
        f"from app.services.{new_dotted} import *  # noqa: F403\n"
        f"from app.services.{new_dotted} import __dict__ as _src\n"
        f"__all__ = [name for name in _src if not name.startswith('__')]\n"
    )
    # Simpler reliable shim without __dict__ trick:
    content = (
        f'"""Compatibility shim. Prefer ``app.services.{new_dotted}``."""\n'
        f"from app.services.{new_dotted} import *  # noqa: F403\n"
    )
    shim.write_text(content, encoding="utf-8")


def ensure_pkg_inits(path: Path) -> None:
    # ensure every package dir under subscription has __init__.py
    sub = SERVICES / "subscription"
    for directory in [path.parent, *path.parent.parents]:
        if not str(directory).startswith(str(sub)):
            break
        init = directory / "__init__.py"
        if directory == sub:
            continue  # already has real __init__
        if not init.exists():
            init.write_text('"""Subscription subpackage."""\n', encoding="utf-8")


def main() -> None:
    # 1) Move files
    for old, new in MOVE.items():
        src = SERVICES / f"{old}.py"
        if not src.exists():
            # already moved?
            dst = new_path(new)
            if dst.exists():
                print(f"skip existing {old} -> {new}")
                continue
            raise SystemExit(f"missing source {src}")
        dst = new_path(new)
        dst.parent.mkdir(parents=True, exist_ok=True)
        ensure_pkg_inits(dst)
        text = rewrite_imports(src.read_text(encoding="utf-8"))
        dst.write_text(text, encoding="utf-8")
        src.unlink()
        write_shim(old, new)
        print(f"moved {old} -> {new}")

    # 2) Rewrite imports in the rest of the repo (app + tests + package)
    for path in list((ROOT / "app").rglob("*.py")) + list((ROOT / "tests").rglob("*.py")):
        if path.name == "migrate_subscription_p2.py":
            continue
        original = path.read_text(encoding="utf-8")
        updated = rewrite_imports(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            print(f"rewrote imports: {path.relative_to(ROOT)}")

    # 3) Update package README
    readme = SERVICES / "subscription" / "README.md"
    readme.write_text(
        """# Subscription domain

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
""",
        encoding="utf-8",
    )
    print("done")


if __name__ == "__main__":
    main()
