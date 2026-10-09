import os
import sys
import unittest
from unittest.mock import patch, MagicMock

if "psycopg2" not in sys.modules:
    mock_psycopg2 = MagicMock()
    sys.modules["psycopg2"] = mock_psycopg2
    sys.modules["psycopg2.extras"] = MagicMock()
    sys.modules["psycopg2.pool"] = MagicMock()

if "requests" not in sys.modules:
    sys.modules["requests"] = MagicMock()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import scripts.cron_hourly as cron_hourly


class TestCronHourly(unittest.TestCase):
    def test_safe_execute_task_success(self):
        mock_fn = MagicMock(return_value={"dispatched": 3})
        res = cron_hourly.safe_execute_task("Sample Task", mock_fn, 1, key="val")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["result"], {"dispatched": 3})
        self.assertGreaterEqual(res["duration_ms"], 0)
        mock_fn.assert_called_once_with(1, key="val")

    def test_safe_execute_task_failure_isolation(self):
        mock_fn = MagicMock(side_effect=RuntimeError("Database connection timed out"))
        res = cron_hourly.safe_execute_task("Failing Task", mock_fn)
        self.assertEqual(res["status"], "error")
        self.assertIn("Database connection timed out", res["error"])
        self.assertGreaterEqual(res["duration_ms"], 0)

    @patch("scripts.cron_daily.check_trial_expiration_pushes")
    def test_run_hourly_pipeline_dispatch(self, mock_trial_pushes):
        mock_trial_pushes.return_value = {"ok": True, "dispatched": 2, "candidates": 2}
        results = cron_hourly.run_hourly_pipeline(dry_run=True, force_send=True, target_hour=9)

        self.assertIn("trial_expiration_pushes", results)
        self.assertEqual(results["trial_expiration_pushes"]["status"], "success")
        mock_trial_pushes.assert_called_once_with(
            target_hour=9,
            dry_run=True,
            force_send=True
        )

    @patch("scripts.cron_daily.check_trial_expiration_pushes")
    @patch("scripts.cron_daily.check_still_good_fridge_lunch_pushes")
    @patch("scripts.cron_daily.check_still_good_produce_expiry_pushes")
    @patch("still_good_ai.enhance_still_good_shelf_life_batch")
    def test_still_good_ai_4x_daily_schedule(self, mock_ai, mock_produce, mock_lunch, mock_trial):
        """Verify Still Good AI runs at 00:00, 06:00, 12:00, 18:00 UTC (12a, 6a, 12p, 6p GMT) and skips other hours."""
        import datetime
        mock_ai.return_value = {"ok": True, "processed": 5}
        mock_trial.return_value = {"ok": True}
        mock_lunch.return_value = {"ok": True}
        mock_produce.return_value = {"ok": True}

        # Test hours: 0, 6, 12, 18 (should trigger)
        for h in [0, 6, 12, 18]:
            fake_now = datetime.datetime(2026, 10, 9, h, 0, 0, tzinfo=datetime.timezone.utc)
            results = cron_hourly.run_hourly_pipeline(dry_run=True, force_send=False, now_utc=fake_now)
            self.assertIn("still_good_ai", results, f"Still Good AI should run at {h}:00 UTC")
            self.assertEqual(results["still_good_ai"]["status"], "success")

        # Test other hours: 1, 7, 13, 23 (should NOT trigger when force_send=False)
        for h in [1, 7, 13, 23]:
            fake_now = datetime.datetime(2026, 10, 9, h, 0, 0, tzinfo=datetime.timezone.utc)
            results = cron_hourly.run_hourly_pipeline(dry_run=True, force_send=False, now_utc=fake_now)
            self.assertNotIn("still_good_ai", results, f"Still Good AI should NOT run at {h}:00 UTC")


if __name__ == "__main__":
    unittest.main()
