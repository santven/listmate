import unittest
from unittest.mock import patch, MagicMock
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


if __name__ == "__main__":
    unittest.main()
