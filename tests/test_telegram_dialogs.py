from __future__ import annotations

import unittest
from typing import Any

from app.services.adapters.telegram.session.dialogs import TelegramDialogsMixin


class FakeEntity:
    id = 1234567890
    username = "DramaChannel"
    broadcast = True
    megagroup = False


class FakeDialog:
    def __init__(self) -> None:
        self.entity = FakeEntity()
        self.name = "影视频道"


class FakeClient:
    def __init__(self) -> None:
        self.get_entity_calls: list[Any] = []
        self.iter_dialog_calls = 0

    async def iter_dialogs(self):
        self.iter_dialog_calls += 1
        yield FakeDialog()

    async def get_entity(self, candidate: Any):
        self.get_entity_calls.append(candidate)
        raise RuntimeError("should not resolve matched dialog again")


class DialogResolver(TelegramDialogsMixin):
    def _entity_source_id(self, entity: Any, fallback: str) -> str:
        return "-1001234567890"


class TelegramDialogsTest(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_dialogs_prefers_cached_dialog_entity_for_peer_id(self) -> None:
        resolver = DialogResolver()
        client = FakeClient()

        dialogs = await resolver._resolve_dialogs(client, ["-1001234567890"])

        self.assertEqual(len(dialogs), 1)
        self.assertIsInstance(dialogs[0]["entity"], FakeEntity)
        self.assertEqual(dialogs[0]["canonical"], "-1001234567890")
        self.assertEqual(client.get_entity_calls, [])

    async def test_resolve_dialogs_matches_username_without_at_prefix(self) -> None:
        resolver = DialogResolver()
        client = FakeClient()

        dialogs = await resolver._resolve_dialogs(client, ["@DramaChannel"])

        self.assertEqual(len(dialogs), 1)
        self.assertIsInstance(dialogs[0]["entity"], FakeEntity)
        self.assertEqual(client.get_entity_calls, [])

    async def test_resolve_dialogs_reuses_entity_map_cache_for_same_client(self) -> None:
        resolver = DialogResolver()
        client = FakeClient()

        first = await resolver._resolve_dialogs(client, ["-1001234567890"])
        second = await resolver._resolve_dialogs(client, ["@DramaChannel"])

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(client.iter_dialog_calls, 1)
