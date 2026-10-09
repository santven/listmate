import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Mock psycopg2 and requests if not installed in local environment
if "psycopg2" not in sys.modules:
    mock_psycopg2 = MagicMock()
    sys.modules["psycopg2"] = mock_psycopg2
    sys.modules["psycopg2.extras"] = MagicMock()
    sys.modules["psycopg2.pool"] = MagicMock()

if "requests" not in sys.modules:
    sys.modules["requests"] = MagicMock()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import scripts.cron_daily as cron_daily
import scripts.cron_hourly as cron_hourly


class TestStillGoodProducePushNotifications(unittest.TestCase):
    def test_copy_single_item_today(self):
        """Verify copy when 1 produce item expires today."""
        name = "Strawberries"
        body = f"Your {name} needs to be used today before it spoils."
        self.assertIn("Strawberries", body)
        self.assertIn("needs to be used today before it spoils", body)

    def test_copy_single_item_tomorrow(self):
        """Verify copy when 1 produce item expires tomorrow."""
        name = "Fresh Cilantro"
        body = f"Your {name} expires tomorrow. Plan to enjoy or use it soon!"
        self.assertIn("Fresh Cilantro", body)
        self.assertIn("expires tomorrow", body)

    def test_copy_both_today_and_tomorrow(self):
        """Verify copy when items expire today and tomorrow."""
        first_name = "Strawberries"
        tom_text = "1 more tomorrow"
        body = f"Your {first_name} expires today, plus {tom_text}. Check Still Good!"
        self.assertIn("Strawberries", body)
        self.assertIn("1 more tomorrow", body)

    @patch("scripts.cron_daily._init_schema")
    @patch("scripts.cron_daily._run")
    @patch("push_helper.send_push_to_user")
    def test_check_still_good_produce_expiry_pushes_dispatch(self, mock_send_push, mock_run, mock_init_schema):
        """Verify candidate users are evaluated, expiring produce retrieved, and pushes dispatched."""
        mock_run.side_effect = [
            # 1. Main candidate query returns two candidate users in different households
            [
                {
                    "user_id": 201,
                    "household_id": 301,
                    "user_name": "Carol",
                    "user_email": "carol@example.com",
                    "user_timezone": "America/New_York",
                    "local_date": "2026-10-09"
                },
                {
                    "user_id": 202,
                    "household_id": 302,
                    "user_name": "Dave",
                    "user_email": "dave@example.com",
                    "user_timezone": "America/Chicago",
                    "local_date": "2026-10-09"
                }
            ],
            # 2. Expiring produce for household 301 (Strawberries today)
            [
                {"id": 51, "name": "Organic Strawberries", "consume_by": "2026-10-09", "location": "fridge"}
            ],
            # 3. Expiring produce for household 302 (Spinach tomorrow)
            [
                {"id": 61, "name": "Baby Spinach", "consume_by": "2026-10-10", "location": "fridge"}
            ]
        ]
        mock_send_push.return_value = {"sent": 1, "failed": 0, "mock": False}

        res = cron_daily.check_still_good_produce_expiry_pushes(target_hour=10, dry_run=False, force_send=True)

        self.assertTrue(res["ok"])
        self.assertEqual(res["candidates"], 2)
        self.assertEqual(res["dispatched"], 2)
        self.assertEqual(len(res["results"]), 2)

        # Check Carol dispatch (expires today)
        res_carol = res["results"][0]
        self.assertEqual(res_carol["user_id"], 201)
        self.assertEqual(res_carol["title"], "⏳ Fresh Produce: Use Today")
        self.assertIn("Organic Strawberries", res_carol["body"])
        self.assertIn("needs to be used today before it spoils", res_carol["body"])
        self.assertEqual(res_carol["data"]["campaign"], "still_good_produce_expiry_10am")
        self.assertEqual(res_carol["data"]["today_count"], "1")
        self.assertEqual(res_carol["data"]["tomorrow_count"], "0")

        # Check Dave dispatch (expires tomorrow)
        res_dave = res["results"][1]
        self.assertEqual(res_dave["user_id"], 202)
        self.assertEqual(res_dave["title"], "🥗 Fresh Produce Reminder")
        self.assertIn("Baby Spinach", res_dave["body"])
        self.assertIn("expires tomorrow", res_dave["body"])
        self.assertEqual(res_dave["data"]["campaign"], "still_good_produce_expiry_10am")
        self.assertEqual(res_dave["data"]["today_count"], "0")
        self.assertEqual(res_dave["data"]["tomorrow_count"], "1")

        self.assertEqual(mock_send_push.call_count, 2)

    @patch("scripts.cron_daily.check_trial_expiration_pushes")
    @patch("scripts.cron_daily.check_still_good_fridge_lunch_pushes")
    @patch("scripts.cron_daily.check_still_good_produce_expiry_pushes")
    def test_run_hourly_pipeline_includes_produce_pushes(self, mock_produce_pushes, mock_lunch_pushes, mock_trial_pushes):
        """Verify run_hourly_pipeline coordinates the Still Good 10:00 AM produce expiry push task."""
        mock_trial_pushes.return_value = {"ok": True, "dispatched": 0}
        mock_lunch_pushes.return_value = {"ok": True, "dispatched": 0}
        mock_produce_pushes.return_value = {"ok": True, "dispatched": 1}

        results = cron_hourly.run_hourly_pipeline(dry_run=True, force_send=True, target_hour=10)

        self.assertIn("still_good_produce_pushes", results)
        self.assertEqual(results["still_good_produce_pushes"]["status"], "success")
        mock_produce_pushes.assert_called_once_with(
            target_hour=10,
            dry_run=True,
            force_send=True
        )


if __name__ == "__main__":
    unittest.main()
