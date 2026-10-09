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

import scripts.cron_daily as cron_daily
import email_helper


class TestStorePlanReminders(unittest.TestCase):

    @patch("scripts.cron_daily._run")
    @patch("scripts.cron_daily._one")
    @patch("push_helper.send_push_to_household")
    def test_check_store_plan_push_reminders_single_store(self, mock_send_push, mock_one, mock_run):
        # Candidate store with 6 items, no plan date
        mock_run.return_value = [
            {"store_id": 12, "store_name": "Costco", "household_id": 5, "items_count": 6}
        ]
        # No push sent in last 24h
        mock_one.return_value = None
        mock_send_push.return_value = {"sent": 1, "mock": False}

        res = cron_daily.check_store_plan_push_reminders(threshold_n=5, dry_run=False)

        self.assertTrue(res["ok"])
        self.assertEqual(res["candidates"], 1)
        self.assertEqual(res["dispatched"], 1)
        self.assertEqual(res["skipped_24h"], 0)
        mock_send_push.assert_called_once()
        args, kwargs = mock_send_push.call_args
        self.assertEqual(args[0], 5)  # household_id
        self.assertIn("Costco", args[1])  # title
        self.assertIn("6 items", args[2])  # body
        self.assertEqual(args[3]["url"], "/?store_id=12&action=plan")

    @patch("scripts.cron_daily._run")
    @patch("scripts.cron_daily._one")
    @patch("push_helper.send_push_to_household")
    def test_check_store_plan_push_reminders_multi_stores_combined(self, mock_send_push, mock_one, mock_run):
        # Household has two qualifying stores: Indian Store (12) and Costco (10)
        mock_run.return_value = [
            {"store_id": 31, "store_name": "Indian Store", "household_id": 1, "items_count": 12},
            {"store_id": 11, "store_name": "Costco", "household_id": 1, "items_count": 10}
        ]
        mock_one.return_value = None
        mock_send_push.return_value = {"sent": 1, "mock": False}

        res = cron_daily.check_store_plan_push_reminders(threshold_n=10, dry_run=False)

        self.assertTrue(res["ok"])
        self.assertEqual(res["candidates"], 2)
        self.assertEqual(res["dispatched"], 1)
        self.assertEqual(len(res["results"]), 1)
        mock_send_push.assert_called_once()
        args, kwargs = mock_send_push.call_args
        self.assertEqual(args[0], 1)  # household_id
        self.assertEqual(args[1], "📅 Plan your shopping trips")
        self.assertIn("Indian Store and Costco have 10+ items", args[2])
        self.assertEqual(args[3]["action"], "plan_modal")
        self.assertIn("/?action=plan_modal&stores=31,11", args[3]["url"])

    @patch("scripts.cron_daily._run")
    @patch("scripts.cron_daily._one")
    @patch("push_helper.send_push_to_household")
    def test_check_store_plan_push_reminders_general_list_only(self, mock_send_push, mock_one, mock_run):
        # Household has only General List with >= 10 items
        mock_run.return_value = [
            {"store_id": 1, "store_name": "General List", "household_id": 1, "items_count": 14}
        ]
        mock_one.return_value = None
        mock_send_push.return_value = {"sent": 1, "mock": False}

        res = cron_daily.check_store_plan_push_reminders(threshold_n=10, dry_run=False)

        self.assertTrue(res["ok"])
        self.assertEqual(res["candidates"], 1)
        self.assertEqual(res["dispatched"], 1)
        mock_send_push.assert_called_once()
        args, kwargs = mock_send_push.call_args
        self.assertEqual(args[0], 1)
        self.assertEqual(args[1], "📋 Organize your General List")
        self.assertIn("14 items in your General List", args[2])
        self.assertEqual(args[3]["action"], "general_list_info")
        self.assertIn("/?action=general_list_info&store_id=1", args[3]["url"])

    @patch("scripts.cron_daily._run")
    @patch("scripts.cron_daily._one")
    @patch("push_helper.send_push_to_household")
    def test_check_store_plan_push_reminders_general_list_excluded_from_multi(self, mock_send_push, mock_one, mock_run):
        # Household has Costco (12), Indian Store (11), and General List (15)
        mock_run.return_value = [
            {"store_id": 1, "store_name": "General List", "household_id": 1, "items_count": 15},
            {"store_id": 11, "store_name": "Costco", "household_id": 1, "items_count": 12},
            {"store_id": 31, "store_name": "Indian Store", "household_id": 1, "items_count": 11}
        ]
        mock_one.return_value = None
        mock_send_push.return_value = {"sent": 1, "mock": False}

        res = cron_daily.check_store_plan_push_reminders(threshold_n=10, dry_run=False)

        self.assertTrue(res["ok"])
        self.assertEqual(res["candidates"], 3)
        self.assertEqual(res["dispatched"], 1)
        mock_send_push.assert_called_once()
        args, kwargs = mock_send_push.call_args
        self.assertEqual(args[1], "📅 Plan your shopping trips")
        # General list should be excluded from the multi-store push text
        self.assertNotIn("General List", args[2])
        self.assertIn("Costco and Indian Store", args[2])

    @patch("scripts.cron_daily._run")
    @patch("scripts.cron_daily._one")
    @patch("push_helper.send_push_to_household")
    def test_check_store_plan_push_reminders_24h_dedup(self, mock_send_push, mock_one, mock_run):
        # Candidate store with 7 items
        mock_run.return_value = [
            {"store_id": 12, "store_name": "Costco", "household_id": 5, "items_count": 7}
        ]
        # Push WAS sent in last 24h
        mock_one.return_value = {"id": 999}

        res = cron_daily.check_store_plan_push_reminders(threshold_n=5, dry_run=False, force_send=False)

        self.assertTrue(res["ok"])
        self.assertEqual(res["candidates"], 1)
        self.assertEqual(res["dispatched"], 0)
        self.assertEqual(res["skipped_24h"], 1)
        mock_send_push.assert_not_called()

    @patch("scripts.cron_daily._run")
    @patch("scripts.cron_daily._one")
    @patch("push_helper.send_push_to_household")
    def test_check_store_plan_push_reminders_dry_run(self, mock_send_push, mock_one, mock_run):
        mock_run.return_value = [
            {"store_id": 14, "store_name": "Trader Joe's", "household_id": 8, "items_count": 5}
        ]
        mock_one.return_value = None

        res = cron_daily.check_store_plan_push_reminders(threshold_n=5, dry_run=True)

        self.assertTrue(res["ok"])
        self.assertEqual(res["candidates"], 1)
        self.assertEqual(res["dispatched"], 1)
        mock_send_push.assert_not_called()

    @patch("scripts.cron_daily._run")
    @patch("scripts.cron_daily._one")
    @patch("email_helper.send_store_plan_reminder_email")
    @patch("email_helper.is_email_suppressed_db")
    def test_check_store_plan_email_reminders_success(self, mock_suppressed, mock_send_email, mock_one, mock_run):
        # 1. Candidate query
        # 2. Members query
        # 3. Items query
        # 4. Insert email event
        mock_suppressed.return_value = False
        mock_send_email.return_value = True
        mock_one.return_value = None  # No email sent in last 24h

        def run_side_effect(query, params=None):
            if "COUNT(li.id)" in query:
                return [{"store_id": 20, "store_name": "Safeway", "household_id": 10, "items_count": 8}]
            elif "auth_household_members" in query or "auth_households" in query:
                return [{"user_id": 50, "user_name": "Alice", "email": "alice@example.com"}]
            elif "WHERE store_id =" in query:
                return [{"name": "Organic Milk", "quantity": "1 gal"}, {"name": "Sourdough Bread", "quantity": "1 loaf"}]
            elif "INSERT INTO email_events" in query:
                return []
            return []

        mock_run.side_effect = run_side_effect

        res = cron_daily.check_store_plan_email_reminders(threshold_n=5, dry_run=False)

        self.assertTrue(res["ok"])
        self.assertEqual(res["candidates"], 1)
        self.assertEqual(res["sent"], 1)
        self.assertEqual(res["skipped_24h"], 0)
        mock_send_email.assert_called_once()
        kwargs = mock_send_email.call_args[1]
        self.assertEqual(kwargs["to_email"], "alice@example.com")
        self.assertEqual(kwargs["store_name"], "Safeway")
        self.assertEqual(kwargs["items_count"], 8)
        self.assertEqual(len(kwargs["sample_items"]), 2)

    @patch("scripts.cron_daily._run")
    @patch("scripts.cron_daily._one")
    @patch("email_helper.send_store_plan_reminder_email")
    def test_check_store_plan_email_reminders_24h_dedup(self, mock_send_email, mock_one, mock_run):
        mock_run.return_value = [{"store_id": 20, "store_name": "Safeway", "household_id": 10, "items_count": 8}]
        mock_one.return_value = {"id": 123}  # Email was already sent in last 24h

        res = cron_daily.check_store_plan_email_reminders(threshold_n=5, dry_run=False)

        self.assertTrue(res["ok"])
        self.assertEqual(res["candidates"], 1)
        self.assertEqual(res["sent"], 0)
        self.assertEqual(res["skipped_24h"], 1)
        mock_send_email.assert_not_called()

    @patch("email_helper._send_via_api")
    def test_send_store_plan_reminder_email_payload(self, mock_send_api):
        mock_send_api.return_value = True
        with patch.dict(os.environ, {"SENDGRID_API_KEY": "fake_key"}):
            sent = email_helper.send_store_plan_reminder_email(
                to_email="test@example.com",
                user_name="John",
                store_name="Costco Wholesale",
                items_count=7,
                sample_items=["Greek Yogurt", "Paper Towels", "Avocados"],
                store_id=5,
                user_id=12,
                household_id=3
            )
            self.assertTrue(sent)
            mock_send_api.assert_called_once()
            payload = mock_send_api.call_args[0][1]
            self.assertIn("Costco Wholesale", payload["subject"])
            self.assertIn("7 items", payload["subject"])
            plain_val = payload["content"][0]["value"]
            self.assertIn("Greek Yogurt", plain_val)
            self.assertIn("Paper Towels", plain_val)
            self.assertIn("Costco Wholesale", plain_val)
            html_val = payload["content"][1]["value"]
            self.assertIn("Plan your trip to Costco Wholesale", html_val)


    @patch("shared.auth.get_active_tokens_for_household")
    @patch("shared.auth.log_push_dispatch")
    def test_send_push_to_household_empty_tokens_audit_log(self, mock_log_dispatch, mock_get_tokens):
        import push_helper
        mock_get_tokens.return_value = []

        res = push_helper.send_push_to_household(
            household_id=25,
            title="Plan trip",
            body="Check items",
            data={"url": "/?store_id=125"}
        )

        self.assertEqual(res["sent"], 0)
        self.assertEqual(res["message"], "No active tokens for household")
        mock_log_dispatch.assert_called_once()
        kwargs = mock_log_dispatch.call_args[1]
        self.assertEqual(kwargs["target_type"], "household")
        self.assertEqual(kwargs["target_id"], 25)
        self.assertEqual(kwargs["tokens_count"], 0)
        self.assertEqual(kwargs["sent_count"], 0)
        self.assertIn("No active push tokens for household", kwargs["errors"])

    @patch("scripts.cron_hourly._run")
    @patch("scripts.cron_hourly._one")
    @patch("push_helper.send_push_to_household")
    def test_cron_hourly_check_store_plan_push_reminders_no_tokens(self, mock_send_push, mock_one, mock_run):
        import scripts.cron_hourly as cron_hourly
        mock_run.return_value = [
            {"store_id": 125, "store_name": "ValliProduce", "household_id": 25, "items_count": 10}
        ]
        mock_one.return_value = None
        mock_send_push.return_value = {"sent": 0, "failed": 0, "message": "No active tokens for household"}

        res = cron_hourly.check_store_plan_push_reminders(threshold_n=10, dry_run=False)

        self.assertTrue(res["ok"])
        self.assertEqual(res["candidates"], 1)
        self.assertEqual(res["dispatched"], 0)
        self.assertEqual(res["results"][0]["status"], "skipped_no_tokens")

    @patch("scripts.cron_hourly._run")
    @patch("scripts.cron_hourly._one")
    @patch("push_helper.send_push_to_household")
    def test_dynamic_threshold_env_var(self, mock_send_push, mock_one, mock_run):
        import scripts.cron_hourly as cron_hourly
        mock_run.return_value = []
        with patch.dict(os.environ, {"STORE_PLAN_REMINDER_THRESHOLD": "15"}):
            cron_hourly.check_store_plan_push_reminders(dry_run=True)
            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            self.assertEqual(args[1]["threshold"], 15)


if __name__ == "__main__":
    unittest.main()
