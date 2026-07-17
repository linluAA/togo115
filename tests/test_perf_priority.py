from __future__ import annotations
import unittest
from app.services.magnet.constants import TG_BOT_MAGNET_GOOD_SCORE, TG_BOT_MAGNET_EARLY_STOP_MATCHES
from app.services.adapters.telegram.scan.message_index_query import _fts_match_query, _cjk_ngrams
from app.services.subscription.search.all import _prefer_incremental_telegram
from app.services.subscription.crud.rows import list_subscriptions, invalidate_subscription_list_cache, SUBSCRIPTION_LIST_CACHE_TTL
from app.services.metrics import record_magnet_search, record_index_query, metrics_snapshot, clear_metrics

class PerfPriorityTest(unittest.TestCase):
    def test_magnet_constants(self):
        self.assertGreaterEqual(TG_BOT_MAGNET_GOOD_SCORE, 100)
        self.assertEqual(TG_BOT_MAGNET_EARLY_STOP_MATCHES, 1)

    def test_fts_cjk_ngrams(self):
        grams = _cjk_ngrams("南来北往", size=2)
        self.assertIn("南来", grams)
        q = _fts_match_query(["南来北往"])
        self.assertIn("南来", q)

    def test_metrics_magnet_index(self):
        clear_metrics()
        record_magnet_search({"title": "x", "total_ms": 12, "candidates": 3, "matched": 1, "early_stop": True, "cache_hit": False})
        record_index_query({"path": "fts", "count": 2})
        snap = metrics_snapshot()
        self.assertEqual(snap["magnet"]["searches"], 1)
        self.assertEqual(snap["magnet"]["early_stops"], 1)
        self.assertEqual(snap["index"]["fts_hits"], 1)
        clear_metrics()

    def test_prefer_incremental_still(self):
        self.assertTrue(_prefer_incremental_telegram({"media_type": "movie"}))

if __name__ == "__main__":
    unittest.main()