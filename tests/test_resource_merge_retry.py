from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.services.resource_queries import merge_resource_rows
from app.services.subscription.delivery.service import select_retryable_failed_resources, _retry_due
from app.services.subscription.delivery.state import classify_delivery_failure, delivery_failed_status


class ResourceMergeRetryTest(unittest.TestCase):
    def test_merge_same_magnet_hash(self) -> None:
        rows = [
            {
                "id": 2,
                "subscription_id": 1,
                "subscription_title": "野狗骨头",
                "title": "野狗骨头 S01E03",
                "url": "magnet:?xt=urn:btih:ABCDEF1234567890ABCDEF1234567890ABCDEF12",
                "status": "delivered",
                "source": "telegram:x",
            },
            {
                "id": 1,
                "subscription_id": 1,
                "subscription_title": "野狗骨头",
                "title": "野狗骨头 03",
                "url": "magnet:?xt=urn:btih:abcdef1234567890abcdef1234567890abcdef12&dn=dup",
                "status": "delivered",
                "source": "telegram:x",
            },
        ]
        merged = merge_resource_rows(rows)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["group_count"], 2)
        self.assertIn(2, merged[0]["group_ids"])

    def test_merge_same_episode_delivered(self) -> None:
        rows = [
            {
                "id": 5,
                "subscription_id": 9,
                "subscription_title": "千香",
                "title": "千香 S01E30",
                "url": "https://115.com/s/aaa?password=1111",
                "status": "delivered",
                "source": "a",
            },
            {
                "id": 4,
                "subscription_id": 9,
                "subscription_title": "千香",
                "title": "千香 第30集",
                "url": "https://115.com/s/bbb?password=2222",
                "status": "delivered",
                "source": "b",
            },
            {
                "id": 3,
                "subscription_id": 9,
                "subscription_title": "千香",
                "title": "千香 第31集",
                "url": "https://115.com/s/ccc?password=3333",
                "status": "failed",
                "source": "c",
                "last_error": "timeout",
            },
        ]
        merged = merge_resource_rows(rows)
        # E30 delivered rows merge; failed E31 stays separate
        self.assertEqual(len(merged), 2)
        delivered = next(item for item in merged if item.get("status") == "delivered")
        self.assertGreaterEqual(delivered["group_count"], 2)

    def test_classify_failures(self) -> None:
        self.assertEqual(classify_delivery_failure("request timeout"), "timeout")
        self.assertEqual(classify_delivery_failure("FLOOD_WAIT_30"), "flood")
        self.assertEqual(classify_delivery_failure("115 分享链接已失效"), "invalid")
        self.assertEqual(delivery_failed_status("timeout"), "delivery_failed_retryable")
        self.assertEqual(delivery_failed_status("链接已失效"), "link_invalid")

    def test_retry_due_backoff(self) -> None:
        now = datetime.now(timezone.utc)
        recent = {
            "retry_count": 0,
            "updated_at": (now - timedelta(seconds=10)).isoformat(),
        }
        old = {
            "retry_count": 0,
            "updated_at": (now - timedelta(minutes=10)).isoformat(),
        }
        self.assertFalse(_retry_due(recent, "timeout", now))
        self.assertTrue(_retry_due(old, "timeout", now))


if __name__ == "__main__":
    unittest.main()
