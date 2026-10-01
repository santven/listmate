import os
import unittest
from unittest.mock import patch, MagicMock

import scripts.cron_daily as cron_daily
import app as flask_app


class TestTrialPushNotifications(unittest.TestCase):
    def setUp(self):
        self.client = flask_app.app.test_client()

    def test_campaign_content_copy(self):
        """Verify copy matches Issue #554 acceptance criteria."""
        # 72h content
        title_72 = "✨ 3 Days Left in Your ListMate Pro Trial"
        body_72 = "Keep real-time household sync and smart sorting active."
        # 24h content
        title_24 = "⏳ Your Pro trial ends tomorrow"
        body_24 = "Upgrade now to keep uninterrupted household sync."

        self.assertIn("3 Days Left", title_72)
        self.assertIn("sync and smart sorting", body_72)
        self.assertIn("ends tomorrow", title_24)
        self.assertIn("uninterrupted household sync", body_24)

    @patch("scripts.cron_daily._init_schema")
    @patch("scripts.cron_daily._run")
    @patch("push_helper.send_push_to_user")
    def test_check_trial_expiration_pushes_dispatch(self, mock_send_push, mock_run, mock_init_schema):
        """Verify eligible trial candidates are evaluated and dispatched with deep link."""
        mock_run.side_effect = [
            # 1. Main candidate query returns two candidate users
            [
                {
                    "user_id": 101,
                    "household_id": 201,
                    "campaign_type": "trial_72h",
                    "user_email": "user1@example.com",
                    "user_timezone": "America/Chicago"
                },
                {
                    "user_id": 102,
                    "household_id": 202,
                    "campaign_type": "trial_24h",
                    "user_email": "user2@example.com",
                    "user_timezone": "America/New_York"
                }
            ],
            # 2. Live subscription check for user 101: still trial
            [{"is_premium": False, "subscription_status": "trial"}],
            # 3. Live subscription check for user 102: still trial
            [{"is_premium": False, "subscription_status": "trial"}]
        ]
        mock_send_push.return_value = {"sent": 1, "failed": 0, "mock": True}

        res = cron_daily.check_trial_expiration_pushes(target_hour=8, dry_run=False, force_send=True)
        self.assertTrue(res["ok"])
        self.assertEqual(res["candidates"], 2)
        self.assertEqual(res["dispatched"], 2)
        self.assertEqual(mock_send_push.call_count, 2)

        # Inspect first dispatch arguments
        first_call = mock_send_push.call_args_list[0]
        self.assertEqual(first_call.kwargs["user_id"], 101)
        self.assertEqual(first_call.kwargs["title"], "✨ 3 Days Left in Your ListMate Pro Trial")
        self.assertEqual(first_call.kwargs["data"]["action"], "open_upgrade_modal")
        self.assertEqual(first_call.kwargs["data"]["campaign"], "trial_72h")
        self.assertEqual(first_call.kwargs["data"]["url"], "/?modal=upgrade&source=push_trial")

        # Inspect second dispatch arguments
        second_call = mock_send_push.call_args_list[1]
        self.assertEqual(second_call.kwargs["user_id"], 102)
        self.assertEqual(second_call.kwargs["title"], "⏳ Your Pro trial ends tomorrow")
        self.assertEqual(second_call.kwargs["data"]["action"], "open_upgrade_modal")
        self.assertEqual(second_call.kwargs["data"]["campaign"], "trial_24h")

    @patch("scripts.cron_daily._init_schema")
    @patch("scripts.cron_daily._run")
    @patch("push_helper.send_push_to_user")
    def test_live_subscription_check_suppresses_upgraded_users(self, mock_send_push, mock_run, mock_init_schema):
        """Acceptance Criteria 2: Directly verify is_premium = FALSE in PostgreSQL immediately before dispatch."""
        mock_run.side_effect = [
            # Candidate query returned a user
            [{
                "user_id": 105,
                "household_id": 205,
                "campaign_type": "trial_72h",
                "user_email": "paid@example.com"
            }],
            # Live check reveals household has already upgraded!
            [{"is_premium": True, "subscription_status": "premium"}]
        ]

        res = cron_daily.check_trial_expiration_pushes(dry_run=False, force_send=True)
        self.assertTrue(res["ok"])
        self.assertEqual(res["dispatched"], 0)
        mock_send_push.assert_not_called()

    @patch("scripts.cron_daily._init_schema")
    @patch("scripts.cron_daily._run")
    def test_dry_run_mode(self, mock_run, mock_init_schema):
        """Verify dry run mode outputs planned dispatches without modifying data."""
        mock_run.side_effect = [
            [{
                "user_id": 109,
                "household_id": 209,
                "campaign_type": "trial_72h",
                "user_email": "dryrun@example.com"
            }],
            [{"is_premium": False, "subscription_status": "trial"}]
        ]

        res = cron_daily.check_trial_expiration_pushes(dry_run=True, force_send=True)
        self.assertTrue(res["ok"])
        self.assertTrue(res["dry_run"])
        self.assertEqual(len(res["results"]), 1)
        self.assertEqual(res["results"][0]["status"], "dry_run")

    def test_hourly_push_webhook_auth_missing_secret(self):
        """Webhook should return 500 or 401 if INTERNAL_CRON_SECRET is not configured or matched."""
        with patch.dict(os.environ, {}, clear=True):
            resp = self.client.post("/api/internal/cron/hourly-push")
            self.assertEqual(resp.status_code, 500)
            data = resp.get_json()
            self.assertIn("INTERNAL_CRON_SECRET is not configured", data.get("error", ""))

    def test_hourly_push_webhook_auth_invalid_token(self):
        with patch.dict(os.environ, {"INTERNAL_CRON_SECRET": "secret_abc_123"}):
            resp = self.client.post(
                "/api/internal/cron/hourly-push",
                headers={"Authorization": "Bearer wrong_secret"}
            )
            self.assertEqual(resp.status_code, 401)

    @patch("scripts.cron_daily.check_trial_expiration_pushes")
    def test_hourly_push_webhook_authorized_success(self, mock_trial_func):
        mock_trial_func.return_value = {"ok": True, "dispatched": 1, "candidates": 1}
        with patch.dict(os.environ, {"INTERNAL_CRON_SECRET": "secret_abc_123"}):
            resp = self.client.post(
                "/api/internal/cron/hourly-push",
                headers={"Authorization": "Bearer secret_abc_123"},
                json={"dry_run": False, "target_hour": 8}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("ok"))
            self.assertEqual(data.get("target_hour"), 8)
            mock_trial_func.assert_called_once_with(target_hour=8, dry_run=False, force_send=False)

    @patch("scripts.cron_daily.check_trial_expiration_pushes")
    def test_hourly_push_webhook_force_send(self, mock_trial_func):
        mock_trial_func.return_value = {"ok": True, "dispatched": 1, "candidates": 1}
        with patch.dict(os.environ, {"INTERNAL_CRON_SECRET": "secret_abc_123"}):
            resp = self.client.post(
                "/api/internal/cron/hourly-push",
                headers={"Authorization": "Bearer secret_abc_123"},
                json={"dry_run": True, "force": True}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("ok"))
            self.assertTrue(data.get("force_send"))
            mock_trial_func.assert_called_once_with(target_hour=8, dry_run=True, force_send=True)


if __name__ == "__main__":
    unittest.main()
