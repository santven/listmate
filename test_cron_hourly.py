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

    @patch("scripts.cron_hourly.check_post_shopping_smart_stash_pushes")
    @patch("scripts.cron_hourly.check_store_plan_push_reminders")
    @patch("scripts.cron_hourly.check_trial_expiration_pushes")
    def test_run_hourly_pipeline_dispatch(self, mock_trial_pushes, mock_plan_pushes, mock_smart_stash):
        mock_trial_pushes.return_value = {"ok": True, "dispatched": 2, "candidates": 2}
        mock_plan_pushes.return_value = {"ok": True, "dispatched": 1, "candidates": 1}
        mock_smart_stash.return_value = {"ok": True, "dispatched": 3, "candidates": 3}
        results = cron_hourly.run_hourly_pipeline(dry_run=True, force_send=True, target_hour=9)

        self.assertIn("trial_expiration_pushes", results)
        self.assertEqual(results["trial_expiration_pushes"]["status"], "success")
        mock_trial_pushes.assert_called_once_with(
            target_hour=9,
            dry_run=True,
            force_send=True
        )

        self.assertIn("store_plan_push_reminders", results)
        self.assertEqual(results["store_plan_push_reminders"]["status"], "success")
        mock_plan_pushes.assert_called_once_with(
            dry_run=True,
            force_send=True
        )

        self.assertIn("smart_stash_pushes", results)
        self.assertEqual(results["smart_stash_pushes"]["status"], "success")
        mock_smart_stash.assert_called_once_with(
            dry_run=True,
            force_send=True
        )

    @patch("scripts.cron_hourly.check_post_shopping_smart_stash_pushes")
    @patch("scripts.cron_hourly.check_store_plan_push_reminders")
    @patch("scripts.cron_hourly.check_trial_expiration_pushes")
    @patch("scripts.cron_hourly.check_still_good_fridge_lunch_pushes")
    @patch("scripts.cron_hourly.check_still_good_produce_expiry_pushes")
    @patch("still_good_ai.enhance_still_good_shelf_life_batch")
    def test_still_good_ai_4x_daily_schedule(self, mock_ai, mock_produce, mock_lunch, mock_trial, mock_plan, mock_smart_stash):
        """Verify Still Good AI runs at 00:00, 06:00, 12:00, 18:00 UTC (12a, 6a, 12p, 6p GMT) and skips other hours."""
        import datetime
        mock_ai.return_value = {"ok": True, "processed": 5}
        mock_trial.return_value = {"ok": True}
        mock_lunch.return_value = {"ok": True}
        mock_produce.return_value = {"ok": True}
        mock_plan.return_value = {"ok": True}
        mock_smart_stash.return_value = {"ok": True}

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


class TestStillGoodFridgeLunchCadenceAndPostExpiry(unittest.TestCase):
    @patch("push_helper._init_schema")
    @patch("push_helper._run")
    @patch("push_helper.send_push_to_user")
    def test_morning_push_suppresses_items_expired_yesterday(self, mock_send_push, mock_run, mock_init_schema):
        """Test 1: Morning push suppresses items expired yesterday (consume_by < today)."""
        import push_helper
        captured_queries = []

        def fake_run(query, params=None):
            captured_queries.append(query)
            if "FROM auth_users u" in query:
                # Return 1 candidate user
                return [{
                    "user_id": 101,
                    "household_id": 201,
                    "user_name": "Alice",
                    "user_email": "alice@example.com",
                    "user_timezone": "America/Chicago"
                }]
            elif "FROM still_good_items" in query and "household_id = %s" in query:
                # In SQL, items where consume_by < CURRENT_DATE are filtered out,
                # so if the fridge only has expired items, empty list is returned.
                return []
            return []

        mock_run.side_effect = fake_run

        res = push_helper.check_still_good_fridge_lunch_pushes(target_hour=7, dry_run=False, force_send=False)

        # Verify candidate query contains post-expiry suppression check
        cand_q = captured_queries[0]
        self.assertIn("sgi.consume_by >= (NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago'))::DATE", cand_q)

        # Verify fridge items query contains post-expiry suppression check
        fridge_q = captured_queries[1]
        self.assertIn("consume_by >= CURRENT_DATE", fridge_q)

        # Candidate user has no unexpired fridge items, so no push is sent
        self.assertEqual(res["dispatched"], 0)
        self.assertEqual(mock_send_push.call_count, 0)

    @patch("push_helper._init_schema")
    @patch("push_helper._run")
    @patch("push_helper.send_push_to_user")
    def test_morning_push_respects_alternate_day_throttle(self, mock_send_push, mock_run, mock_init_schema):
        """Test 2: Morning push respects alternate-day throttle (skipped if pushed yesterday when no item expires today)."""
        import push_helper
        captured_queries = []

        def fake_run(query, params=None):
            captured_queries.append(query)
            # Candidate query filters out user because they were pushed yesterday and have no day-0 item
            return []

        mock_run.side_effect = fake_run

        res = push_helper.check_still_good_fridge_lunch_pushes(target_hour=7, dry_run=False, force_send=False)

        # Verify candidate query contains the alternate-day throttle check
        cand_q = captured_queries[0]
        self.assertIn("pnl_y.created_at >= NOW() - INTERVAL '36 hours'", cand_q)
        self.assertIn("sgi_today.consume_by = DATE(NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago'))", cand_q)

        self.assertEqual(res["candidates"], 0)
        self.assertEqual(res["dispatched"], 0)
        self.assertEqual(mock_send_push.call_count, 0)

        # Verify force_send=True bypasses cadence checks
        captured_queries.clear()
        res_forced = push_helper.check_still_good_fridge_lunch_pushes(target_hour=7, dry_run=False, force_send=True)
        forced_q = captured_queries[0]
        self.assertNotIn("pnl_y.created_at >= NOW() - INTERVAL '36 hours'", forced_q)

    @patch("push_helper._init_schema")
    @patch("push_helper._run")
    @patch("push_helper.send_push_to_user")
    def test_day_0_override_pings_user_even_if_pushed_yesterday(self, mock_send_push, mock_run, mock_init_schema):
        """Test 3: Day-0 override pings user even if pushed yesterday when an item expires today!"""
        import push_helper
        import datetime
        today_str = datetime.date.today().isoformat()
        mock_send_push.return_value = {"sent": 1, "failed": 0, "mock": False}

        def fake_run(query, params=None):
            if "FROM auth_users u" in query:
                # User qualified because sgi_today.consume_by = today matched the override!
                return [{
                    "user_id": 105,
                    "household_id": 205,
                    "user_name": "Charlie",
                    "user_email": "charlie@example.com",
                    "user_timezone": "America/Chicago"
                }]
            elif "FROM still_good_items" in query and "household_id = %s" in query:
                return [{
                    "id": 88,
                    "name": "Roast Chicken",
                    "consume_by": today_str,
                    "date_added": today_str
                }]
            return []

        mock_run.side_effect = fake_run

        res = push_helper.check_still_good_fridge_lunch_pushes(target_hour=7, dry_run=False, force_send=False)

        self.assertTrue(res["ok"])
        self.assertEqual(res["candidates"], 1)
        self.assertEqual(res["dispatched"], 1)
        self.assertEqual(len(res["results"]), 1)
        dispatched_push = res["results"][0]
        self.assertEqual(dispatched_push["user_id"], 105)
        self.assertIn("Roast Chicken", dispatched_push["body"])
        self.assertIn("ready to enjoy before it expires", dispatched_push["body"])
        mock_send_push.assert_called_once()


if __name__ == "__main__":
    unittest.main()
