from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import settings
from app.db import init_db
from app.services.adapters.telegram.scan.message_index import index_telegram_messages, search_telegram_message_index


class DummyMessage:
    def __init__(self, message_id: int, text: str) -> None:
        self.id = message_id
        self.raw_text = text
        self.message = text
        self.text = text
        self.buttons = []
        self.media = None


class TelegramMessageIndexTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_data_dir = settings.data_dir
        self.old_database_path = settings.database_path
        settings.data_dir = Path(self.temp_dir.name)
        settings.database_path = settings.data_dir / "togo115-test.sqlite3"
        init_db()

    def tearDown(self) -> None:
        settings.data_dir = self.old_data_dir
        settings.database_path = self.old_database_path
        self.temp_dir.cleanup()

    def test_index_search_uses_nearby_context_for_link_message(self) -> None:
        count = index_telegram_messages(
            "-1001",
            [
                DummyMessage(10, "剧集：南部档案 2026 第 12 集 1080p"),
                DummyMessage(11, "链接：https://115.com/s/south?password=3333"),
            ],
        )

        results = search_telegram_message_index(["-1001"], ["南部档案 1080p"], 5)

        assert count == 2
        assert len(results) == 1
        assert results[0].url == "https://115.com/s/south?password=3333"
        assert str(results[0].source).startswith("TelegramIndex")
        assert "南部档案" in results[0].context

    def test_index_search_ignores_unmatched_context(self) -> None:
        index_telegram_messages("-1001", [DummyMessage(20, "链接：https://115.com/s/other?password=1111")])

        results = search_telegram_message_index(["-1001"], ["南部档案"], 5)

        assert results == []


    def test_index_search_does_not_attach_neighbor_link(self) -> None:
        index_telegram_messages(
            "-1001",
            [
                DummyMessage(30, "剧集：野狗骨头 2026 第 20 集 1080p"),
                DummyMessage(31, "链接：https://115.com/s/ydgtlink?password=1111"),
                DummyMessage(32, "名称: 念念相忘.Just.for.Meeting.You.2023.2160p"),
                DummyMessage(33, "链接：https://115.com/s/swsbls23ndb?password=KMKM"),
            ],
        )

        results = search_telegram_message_index(["-1001"], ["野狗骨头"], 10)
        urls = [item.url for item in results]

        assert "https://115.com/s/ydgtlink?password=1111" in urls
        assert "https://115.com/s/swsbls23ndb?password=KMKM" not in urls
        assert all("念念相忘" not in (item.title or "") for item in results)



    def test_index_search_requires_link_on_same_message(self) -> None:
        index_telegram_messages(
            "-1001",
            [
                DummyMessage(40, "剧集：野狗骨头 2026 第 20 集 1080p"),
                DummyMessage(41, "名称: 念念相忘.Just.for.Meeting.You.2023.2160p"),
                DummyMessage(42, "链接：https://115.com/s/swsbls23ndb?password=KMKM"),
            ],
        )

        results = search_telegram_message_index(["-1001"], ["野狗骨头"], 10)
        urls = [item.url for item in results]

        # Title-only rows must not pull a later neighbor share just because the window includes it.
        assert urls == []

    def test_index_search_scopes_single_link_window(self) -> None:
        index_telegram_messages(
            "-1001",
            [
                DummyMessage(50, "剧集：野狗骨头 2026 第 20 集 1080p\n名称: 念念相忘.Just.for.Meeting.You.2023.2160p\n链接：https://115.com/s/swsbls23ndb?password=KMKM"),
            ],
        )

        results = search_telegram_message_index(["-1001"], ["野狗骨头"], 10)
        urls = [item.url for item in results]

        # Nearest title above the share is 念念相忘; 野狗骨头 must not claim this share.
        assert "https://115.com/s/swsbls23ndb?password=KMKM" not in urls
        assert all("念念相忘" not in (item.title or "") or "野狗骨头" not in (item.title or "") for item in results)


    def test_index_search_only_uses_immediate_previous_title(self) -> None:
        index_telegram_messages(
            "-1001",
            [
                DummyMessage(60, "剧集：野狗骨头 2026 第 20 集 1080p"),
                DummyMessage(61, "名称: 念念相忘.Just.for.Meeting.You.2023.2160p"),
                DummyMessage(62, "链接：https://115.com/s/swsbls23ndb?password=KMKM"),
            ],
        )

        results = search_telegram_message_index(["-1001"], ["野狗骨头"], 10)
        assert results == []

        results = search_telegram_message_index(["-1001"], ["念念相忘"], 10)
        assert len(results) == 1
        assert results[0].url == "https://115.com/s/swsbls23ndb?password=KMKM"
