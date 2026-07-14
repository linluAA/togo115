from __future__ import annotations

import unittest

from app.services.adapters.telegram.pipeline import TelegramPipelineStats, TelegramPipelineMixin
from app.services.types import SearchResult


class Message:
    def __init__(self, message_id: int, text: str = "message") -> None:
        self.id = message_id
        self.raw_text = text
        self.message = text


class PipelineHarness(TelegramPipelineMixin):
    def __init__(self) -> None:
        self.calls = 0

    async def _links_from_message(self, client, message, source, entity=None, match_queries=None, extra_texts=None):
        self.calls += 1
        return [SearchResult(title="Drama", url=f"https://115.com/s/{message.id}?password=8888", source=source)]


class TelegramPipelineTest(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_skips_duplicate_messages_and_tracks_links(self) -> None:
        harness = PipelineHarness()
        seen: set[int] = set()
        stats = TelegramPipelineStats()

        first = await harness._pipeline_extract_message_links(None, None, "telegram", Message(10), [], None, seen, stats, stage="test")
        second = await harness._pipeline_extract_message_links(None, None, "telegram", Message(10), [], None, seen, stats, stage="test")

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(harness.calls, 1)
        self.assertEqual(stats.extracted_links, 1)
        self.assertEqual(stats.duplicate_messages, 1)

    def test_pipeline_stats_payload_keeps_stage_counts(self) -> None:
        stats = TelegramPipelineStats(read=3)
        stats.bump("title_matched", 2)
        stats.bump("custom", 4)

        self.assertEqual(stats.as_payload()["read"], 3)
        self.assertEqual(stats.as_payload()["title_matched"], 2)
        self.assertEqual(stats.as_payload()["custom"], 4)
