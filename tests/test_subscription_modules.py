import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from app.config import settings
from app.db import db, init_db, json_dumps, utc_now
from app.schemas import SubscriptionCreate
from app.services.subscription.crud import service as subscription_crud
from app.services.subscription.delivery import service as subscription_delivery
from app.services.subscription.search import tasks as subscription_tasks


class SplitSubscriptionModuleTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_data_dir = settings.data_dir
        self.old_database_path = settings.database_path
        settings.data_dir = Path(self.temp_dir.name)
        settings.database_path = settings.data_dir / "togo115-split-test.sqlite3"
        init_db()

    def tearDown(self) -> None:
        settings.data_dir = self.old_data_dir
        settings.database_path = self.old_database_path
        self.temp_dir.cleanup()

    async def test_crud_create_keeps_subscription_schedule_hook_patchable(self) -> None:
        payload = SubscriptionCreate(title="Drama", media_type="tv", keywords=["Drama"], target_path="/tv/Drama")

        with patch.object(subscription_tasks, "schedule_subscription_search", Mock(return_value={"ok": True})) as schedule, patch(
            "app.services.subscription.crud.create.sync_subscription_list_with_emby", AsyncMock(return_value={"ok": True, "updated": 0})
        ) as sync_emby:
            created = await subscription_crud.create_subscription(payload)
            duplicate = await subscription_crud.create_subscription(payload)

        self.assertEqual(created["title"], "Drama")
        self.assertEqual(duplicate["id"], created["id"])
        schedule.assert_called_once_with(created["id"])
        sync_emby.assert_awaited_once()

    async def test_crud_create_returns_emby_synced_episode_count(self) -> None:
        payload = SubscriptionCreate(title="Drama", media_type="tv", keywords=["Drama"], target_path="/tv/Drama")

        async def sync_created(items):
            subscription_id = int(items[0]["id"])
            with db() as conn:
                conn.execute(
                    "UPDATE subscriptions SET emby_count = ?, emby_episode_keys = ? WHERE id = ?",
                    (3, json_dumps(["1x1", "1x2", "1x3"]), subscription_id),
                )
            return {"ok": True, "updated": 1}

        with patch.object(subscription_tasks, "schedule_subscription_search", Mock(return_value={"ok": True})), patch(
            "app.services.subscription.crud.create.sync_subscription_list_with_emby", AsyncMock(side_effect=sync_created)
        ):
            created = await subscription_crud.create_subscription(payload)

        self.assertEqual(created["emby_count"], 3)
        self.assertEqual(created["emby_episode_keys"], ["1x1", "1x2", "1x3"])

    async def test_delivery_module_accepts_injected_adapters(self) -> None:
        now = utc_now()
        with db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO subscriptions
                    (title, media_type, keywords, quality_rules, delivery_mode, target_path, created_at, updated_at)
                VALUES ('Drama', 'tv', '[]', '{}', '115', '/tv/Drama', ?, ?)
                """,
                (now, now),
            )
            subscription_id = int(cursor.lastrowid)
            cursor = conn.execute(
                """
                INSERT INTO resources (subscription_id, source, title, url, status, created_at)
                VALUES (?, 'site_plugin:test', 'Drama S01E01', 'magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'pending', ?)
                """,
                (subscription_id, now),
            )
            resource_id = int(cursor.lastrowid)

        pan = Mock()
        pan.offline_download = AsyncMock(return_value=True)
        bot = Mock()
        bot.forward_to_bot = AsyncMock(return_value=False)

        ok = await subscription_delivery.deliver_resource(
            resource_id,
            get_setting_func=lambda key, default=None: {"mode": "115"},
            pan115_adapter_cls=Mock(return_value=pan),
            telegram_bot_adapter_cls=Mock(return_value=bot),
        )

        self.assertTrue(ok)
        pan.offline_download.assert_awaited_once_with("magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "/tv/Drama")
        bot.forward_to_bot.assert_not_called()
        with db() as conn:
            row = conn.execute("SELECT status FROM resources WHERE id = ?", (resource_id,)).fetchone()
        self.assertEqual(row["status"], "delivered")


def test_subscription_module_import_graph_has_no_static_cycles() -> None:
    import ast

    service_dir = Path(__file__).resolve().parents[1] / "app" / "services"
    module_paths = {path.stem: path for path in service_dir.glob("subscription*.py")}
    graph: dict[str, set[str]] = {name: set() for name in module_paths}
    for name, module_path in module_paths.items():
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if node.module.startswith("app.services.subscription"):
                dep = node.module.rsplit(".", 1)[-1]
                if dep in graph and dep != name:
                    graph[name].add(dep)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str, path: tuple[str, ...] = ()) -> None:
        if name in visited:
            return
        if name in visiting:
            cycle = " -> ".join((*path, name))
            raise AssertionError(f"subscription module import cycle: {cycle}")
        visiting.add(name)
        for dep in graph[name]:
            visit(dep, (*path, name))
        visiting.remove(name)
        visited.add(name)

    for name in graph:
        visit(name)
