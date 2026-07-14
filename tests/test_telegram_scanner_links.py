from __future__ import annotations

import unittest

from app.services.adapters.telegram.scan.scanner import TelegramMessageScanner


class Message:
    def __init__(self, text: str, message_id: int = 1) -> None:
        self.id = message_id
        self.raw_text = text
        self.message = text
        self.buttons = []
        self.grouped_id = None
        self.media = None


class TelegramScannerLinksTest(unittest.IsolatedAsyncioTestCase):
    async def test_combined_message_text_dedupes_related_and_extra_texts(self) -> None:
        scanner = TelegramMessageScanner()

        text = scanner._combined_message_text(
            [
                Message("\u5267\u96c6\u6807\u9898"),
                Message("\u5267\u96c6\u6807\u9898"),
                Message("\u94fe\u63a5\uff1ahttps://115.com/s/demo?password=1234"),
            ],
            ["\u5267\u96c6\u6807\u9898", "\u753b\u8d28\uff1a1080p"],
        )

        self.assertEqual(text, "\u5267\u96c6\u6807\u9898\n\u94fe\u63a5\uff1ahttps://115.com/s/demo?password=1234\n\u753b\u8d28\uff1a1080p")

    async def test_links_from_message_uses_extra_texts_without_neighbor_scan(self) -> None:
        scanner = TelegramMessageScanner()
        message = Message("\u5c06\u591c 2026", 12)

        results = await scanner._links_from_message(
            None,
            message,
            "telegram:test",
            extra_texts=["\u94fe\u63a5\uff1ahttps://115.com/s/demo?password=1234"],
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "https://115.com/s/demo?password=1234")
        self.assertEqual(results[0].source, "telegram:test")
        self.assertEqual(results[0].message_id, "12")

    async def test_links_from_message_uses_nearest_chinese_title_as_result_title(self) -> None:
        scanner = TelegramMessageScanner()
        text = "\n".join(
            [
                "\u7535\u89c6\u5267\uff1a\u7231\u604b (2024)",
                "\u94fe\u63a5\uff1ahttps://115.com/s/first?password=1111",
                "\u7535\u5f71\uff1a\u540e\u5ba4 2026",
                "\u94fe\u63a5\uff1ahttps://115.com/s/second?password=2222",
            ]
        )

        results = await scanner._links_from_message(None, Message(text), "telegram:test")

        second = next(item for item in results if item.url.endswith("second?password=2222"))
        self.assertEqual(second.title, "\u540e\u5ba4 2026")

    def test_external_resource_page_urls_are_deduped_and_host_limited(self) -> None:
        scanner = TelegramMessageScanner()

        urls = scanner._external_resource_page_urls(
            "https://telegra.ph/resource https://telegra.ph/resource https://example.com/ignore"
        )

        self.assertEqual(urls, ["https://telegra.ph/resource"])
