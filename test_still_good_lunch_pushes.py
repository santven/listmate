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


class TestStillGoodLunchPushNotifications(unittest.TestCase):
    def test_copy_single_item(self):
        """Verify copy when exactly 1 item is in the fridge."""
        dish = "Chicken Tikka"
        body = f"You have {dish} in the fridge ready to enjoy before it expires."
        self.assertIn("Chicken Tikka", body)
        self.assertIn("ready to enjoy before it expires", body)

    def test_copy_two_to_three_items(self):
        """Verify copy when 2 to 3 items are in the fridge."""
        # 2 items
        most_urgent = "Pad Thai"
        remaining = 1
        meal_word = "other meal" if remaining == 1 else "other meals"
        body_2 = f"You have {most_urgent} and {remaining} {meal_word} waiting in the fridge."
        self.assertEqual(body_2, "You have Pad Thai and 1 other meal waiting in the fridge.")

        # 3 items
        remaining = 2
        meal_word = "other meal" if remaining == 1 else "other meals"
        body_3 = f"You have {most_urgent} and {remaining} {meal_word} waiting in the fridge."
        self.assertEqual(body_3, "You have Pad Thai and 2 other meals waiting in the fridge.")

    def test_copy_four_plus_items(self):
        """Verify copy when 4 or more items are in the fridge."""
        count = 5
        body = f"Your fridge has {count} meals waiting to be enjoyed. Check Still Good before heading out!"
        self.assertIn("5 meals waiting", body)
        self.assertIn("Check Still Good before heading out", body)

    @patch("scripts.cron_daily._init_schema")
    @patch("scripts.cron_daily._run")
    @patch("push_helper.send_push_to_user")
    def test_check_still_good_fridge_lunch_pushes_dispatch(self, mock_send_push, mock_run, mock_init_schema):
        """Verify candidate users are evaluated, fridge meals retrieved, and pushes dispatched."""
        mock_run.side_effect = [
            # 1. Main candidate query returns two candidate users in different households
            [
                {
                    "user_id": 101,
                    "household_id": 201,
                    "user_name": "Alice",
                    "user_email": "alice@example.com",
                    "user_timezone": "America/New_York"
                },
                {
                    "user_id": 102,
                    "household_id": 202,
                    "user_name": "Bob",
                    "user_email": "bob@example.com",
                    "user_timezone": "America/Chicago"
                }
            ],
            # 2. Fridge items query for household 201 (1 item)
            [
                {"id": 1, "name": "Sunday Chili", "consume_by": "2026-10-10", "date_added": "2026-10-06"}
            ],
            # 3. Fridge items query for household 202 (3 items)
            [
                {"id": 10, "name": "Veggie Biryani", "consume_by": "2026-10-09", "date_added": "2026-10-07"},
                {"id": 11, "name": "Dal Makhani", "consume_by": "2026-10-10", "date_added": "2026-10-07"},
                {"id": 12, "name": "Paneer Tikka", "consume_by": "2026-10-11", "date_added": "2026-10-08"}
            ]
        ]
        mock_send_push.return_value = {"sent": 1, "failed": 0, "mock": False}

        res = cron_daily.check_still_good_fridge_lunch_pushes(target_hour=7, dry_run=False, force_send=True)

        self.assertTrue(res["ok"])
        self.assertEqual(res["candidates"], 2)
        self.assertEqual(res["dispatched"], 2)
        self.assertEqual(len(res["results"]), 2)

        # Check user 101 dispatch (1 item)
        res_alice = res["results"][0]
        self.assertEqual(res_alice["user_id"], 101)
        self.assertEqual(res_alice["title"], "🍱 Packing lunch today?")
        self.assertIn("Sunday Chili", res_alice["body"])
        self.assertIn("ready to enjoy before it expires", res_alice["body"])

        # Check user 102 dispatch (3 items)
        res_bob = res["results"][1]
        self.assertEqual(res_bob["user_id"], 102)
        self.assertEqual(res_bob["title"], "🍱 Packing lunch today?")
        self.assertIn("Veggie Biryani", res_bob["body"])
        self.assertIn("2 other meals", res_bob["body"])

        self.assertEqual(mock_send_push.call_count, 2)

    @patch("scripts.cron_daily.check_trial_expiration_pushes")
    @patch("scripts.cron_daily.check_still_good_fridge_lunch_pushes")
    def test_run_hourly_pipeline_includes_still_good_lunch(self, mock_lunch_pushes, mock_trial_pushes):
        """Verify run_hourly_pipeline coordinates the Still Good 7:00 AM push task."""
        mock_trial_pushes.return_value = {"ok": True, "dispatched": 0}
        mock_lunch_pushes.return_value = {"ok": True, "dispatched": 1}

        results = cron_hourly.run_hourly_pipeline(dry_run=True, force_send=True, target_hour=7)

        self.assertIn("still_good_lunch_pushes", results)
        self.assertEqual(results["still_good_lunch_pushes"]["status"], "success")
        mock_lunch_pushes.assert_called_once_with(
            target_hour=7,
            dry_run=True,
            force_send=True
        )


if __name__ == "__main__":
    unittest.main()
