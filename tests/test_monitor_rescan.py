from __future__ import annotations

import unittest
from unittest.mock import patch

from app.config import settings
from app.services.monitor import MonitorService


class MonitorRescanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.old_interval = settings.subscription_rescan_interval_seconds

    def tearDown(self) -> None:
        settings.subscription_rescan_interval_seconds = self.old_interval

    def test_rescan_disabled_when_interval_zero(self) -> None:
        settings.subscription_rescan_interval_seconds = 0
        monitor = MonitorService()
        with patch("app.services.monitor.schedule_search_all_active_subscriptions") as schedule:
            self.assertIsNone(monitor._maybe_schedule_subscription_rescan(100.0))
            schedule.assert_not_called()

    def test_rescan_triggers_and_respects_interval(self) -> None:
        settings.subscription_rescan_interval_seconds = 1800
        monitor = MonitorService()
        with patch(
            "app.services.monitor.schedule_search_all_active_subscriptions",
            return_value={"ok": True, "queued": True, "running": True},
        ) as schedule:
            # First tick only arms the timer.
            armed = monitor._maybe_schedule_subscription_rescan(100.0)
            self.assertIsNone(armed)
            schedule.assert_not_called()

            # Within interval: still no trigger.
            within = monitor._maybe_schedule_subscription_rescan(100.0 + 1799)
            self.assertIsNone(within)
            schedule.assert_not_called()

            # After interval: queue a full rescan.
            first = monitor._maybe_schedule_subscription_rescan(100.0 + 1800)
            self.assertEqual(first, {"ok": True, "queued": True, "running": True})
            schedule.assert_called_once()

            # After another interval: trigger again even if previous search is still running.
            schedule.return_value = {"ok": True, "queued": False, "running": True}
            second = monitor._maybe_schedule_subscription_rescan(100.0 + 3600)
            self.assertEqual(second, {"ok": True, "queued": False, "running": True})
            self.assertEqual(schedule.call_count, 2)
