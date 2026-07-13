from __future__ import annotations

import unittest

from app.services.adapters.telegram_history_config import build_history_options, server_search_queries


class TelegramHistoryConfigTest(unittest.TestCase):
    def test_build_history_options_clamps_values(self) -> None:
        options = build_history_options(
            {
                "history_limit": 9999,
                "fallback_scan_limit": 1,
                "messages_per_query": 9999,
                "history_timeout": 9999,
                "history_query_timeout": 9999,
                "history_fallback_timeout": 9999,
            }
        )

        self.assertEqual(options.history_limit, 500)
        self.assertEqual(options.fallback_scan_limit, 20)
        self.assertEqual(options.messages_per_query, 500)
        self.assertEqual(options.total_budget, 18.0)
        self.assertEqual(options.query_budget, 2.0)
        self.assertEqual(options.recent_budget, 4.0)

    def test_server_search_queries_prefers_year_query(self) -> None:
        queries = server_search_queries(["将夜 2026", "将夜", " 将夜 ", "Jiang Ye 2026", ""])

        self.assertEqual(queries, ["Jiang Ye 2026"])

