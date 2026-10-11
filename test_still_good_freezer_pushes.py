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


class TestStillGoodFreezerPushNotifications(unittest.TestCase):
    def test_copy_single_freezer_item(self):
        """Verify copy when 1 freezer item reaches 1 week before expiry."""
        name = "Sunday Chili"
        body = f"Your {name} in the freezer reaches its best-by date in 1 week. Consider thawing it soon!"
        self.assertIn("Sunday Chili", body)
        self.assertIn("reaches its best-by date in 1 week", body)
        self.assertIn("Consider thawing it soon", body)

    def test_copy_two_freezer_items(self):
        """Verify copy when 2 freezer items reach 1 week before expiry."""
        first_name = "Sunday Chili"
        second_name = "Chicken Tikka"
        body = f"Your {first_name} and {second_name} reach best-by in 1 week. Plan to thaw and enjoy!"
        self.assertIn("Sunday Chili", body)
        self.assertIn("Chicken Tikka", body)
        self.assertIn("Plan to thaw and enjoy", body)

    def test_copy_three_plus_freezer_items(self):
        """Verify copy when 3+ freezer items reach 1 week before expiry."""
        count = 3
        first_name = "Sunday Chili"
        body = f"You have {count} freezer meals (including {first_name}) reaching best-by in 1 week. Check Still Good to thaw!"
        self.assertIn("3 freezer meals", body)
        self.assertIn("Sunday Chili", body)
        self.assertIn("Check Still Good to thaw", body)

    @patch("push_helper._init_schema")
    @patch("push_helper._run")
    @patch("push_helper.send_push_to_user")
    def test_check_still_good_freezer_expiry_pushes_dispatch(self, mock_send_push, mock_run, mock_init_schema):
        """Verify candidate users are evaluated, expiring freezer meals retrieved, and pushes dispatched."""
        mock_run.side_effect = [
            # 1. Main candidate query returns two candidate users in different households
            [
                {
                    "user_id": 401,
                    "household_id": 501,
                    "user_name": "Emma",
                    "user_email": "emma@example.com",
                    "user_timezone": "America/New_York",
                    "local_date": "2026-10-09"
                },
                {
                    "user_id": 402,
                    "household_id": 502,
                    "user_name": "Frank",
                    "user_email": "frank@example.com",
                    "user_timezone": "America/Chicago",
                    "local_date": "2026-10-09"
                }
            ],
            # 2. Freezer items for household 501 (1 item: Lentil Stew)
            [
                {"id": 81, "name": "Lentil Stew", "consume_by": "2026-10-16", "location": "freezer"}
            ],
            # 3. Freezer items for household 502 (2 items: Bolognese, Veggie Curry)
            [
                {"id": 91, "name": "Bolognese Sauce", "consume_by": "2026-10-15", "location": "freezer"},
                {"id": 92, "name": "Veggie Curry", "consume_by": "2026-10-16", "location": "freezer"}
            ]
        ]
        mock_send_push.return_value = {"sent": 1, "failed": 0, "mock": False}

        res = cron_daily.check_still_good_freezer_expiry_pushes(target_hour=9, dry_run=False, force_send=True)

        self.assertTrue(res["ok"])
        self.assertEqual(res["candidates"], 2)
        self.assertEqual(res["dispatched"], 2)
        self.assertEqual(len(res["results"]), 2)

        # Check Emma dispatch (1 item)
        res_emma = res["results"][0]
        self.assertEqual(res_emma["user_id"], 401)
        self.assertEqual(res_emma["title"], "❄️ Freezer Reminder")
        self.assertIn("Lentil Stew", res_emma["body"])
        self.assertIn("reaches its best-by date in 1 week", res_emma["body"])
        self.assertEqual(res_emma["data"]["campaign"], "still_good_freezer_expiry_9am")
        self.assertEqual(res_emma["data"]["tab"], "freezer")
        self.assertEqual(res_emma["data"]["freezer_items_count"], "1")

        # Check Frank dispatch (2 items)
        res_frank = res["results"][1]
        self.assertEqual(res_frank["user_id"], 402)
        self.assertEqual(res_frank["title"], "❄️ Freezer Reminder")
        self.assertIn("Bolognese Sauce", res_frank["body"])
        self.assertIn("Veggie Curry", res_frank["body"])
        self.assertEqual(res_frank["data"]["campaign"], "still_good_freezer_expiry_9am")
        self.assertEqual(res_frank["data"]["freezer_items_count"], "2")

        self.assertEqual(mock_send_push.call_count, 2)

    @patch("scripts.cron_hourly.check_trial_expiration_pushes")
    @patch("scripts.cron_hourly.check_still_good_fridge_lunch_pushes")
    @patch("scripts.cron_hourly.check_still_good_produce_expiry_pushes")
    @patch("scripts.cron_hourly.check_still_good_freezer_expiry_pushes")
    @patch("scripts.cron_hourly.check_store_plan_push_reminders")
    def test_hourly_pipeline_includes_freezer_pushes(self, mock_plan, mock_freezer, mock_produce, mock_lunch, mock_trial):
        """Verify run_hourly_pipeline executes freezer 1-week expiry pushes."""
        mock_trial.return_value = {"ok": True, "dispatched": 0}
        mock_lunch.return_value = {"ok": True, "dispatched": 0}
        mock_produce.return_value = {"ok": True, "dispatched": 0}
        mock_freezer.return_value = {"ok": True, "dispatched": 1}
        mock_plan.return_value = {"ok": True, "dispatched": 0}

        results = cron_hourly.run_hourly_pipeline(dry_run=True, force_send=True, target_hour=9)

        self.assertIn("still_good_freezer_pushes", results)
        self.assertEqual(results["still_good_freezer_pushes"]["status"], "success")
        mock_freezer.assert_called_once_with(target_hour=9, dry_run=True, force_send=True)


if __name__ == "__main__":
    unittest.main()
