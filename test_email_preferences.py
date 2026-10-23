#!/usr/bin/env python3
"""
Unit and integration test suite for the ListMate Email Preference & Granular Unsubscribe System.
Covers:
1. Cryptographic HMAC token generation, verification, tamper-proofing, and legacy fallback.
2. Category resolution mapping engine.
3. Database preference CRUD and multi-category isolation.
4. Defense-in-depth delivery gating (hard suppression vs category opt-outs).
5. SendGrid API pre-flight gating and RFC 8058 header injection.
6. Public web endpoints (/email/unsubscribe, /email/resubscribe, /email/preferences, RFC list-unsubscribe).
7. In-app settings endpoints (/api/user/email-preferences).
8. Daily cron event pruning for opted-out categories.
"""

import os
import sys
import json
import time
import base64
import unittest
from unittest.mock import patch, MagicMock

# Environment setup
os.environ["SENDGRID_API_KEY"] = "test_sg_key_12345"
os.environ["SECRET_KEY"] = "test-secret-key-unit-tests"
os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL", "postgresql://dummy:5432/test")

# Defensive mocking of external libraries if missing in test environment
for mod in ["google", "google.oauth2", "google.auth", "google.auth.transport", "google.auth.exceptions", "psycopg2", "psycopg2.extras", "psycopg2.pool", "requests"]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

if "flask_limiter" not in sys.modules:
    mock_limiter = MagicMock()
    mock_limiter.Limiter.return_value.limit.return_value = lambda f: f
    sys.modules["flask_limiter"] = mock_limiter
    sys.modules["flask_limiter.util"] = MagicMock()

import email_helper
import shared.auth as auth
from app import app


class TestEmailPreferences(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.app_ctx = app.app_context()
        self.app_ctx.push()

    def tearDown(self):
        self.app_ctx.pop()

    # ─────────────────────────────────────────────────────────────
    # 1. Cryptographic Token Integrity Tests
    # ─────────────────────────────────────────────────────────────
    def test_token_generation_and_verification(self):
        email = "shopper@example.com"
        cat = "shopping_reminders"
        uid = 42

        token = auth.generate_email_token(email, category=cat, user_id=uid)
        self.assertIn(".", token)

        payload = auth.verify_email_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["email"], "shopper@example.com")
        self.assertEqual(payload["cat"], "shopping_reminders")
        self.assertEqual(payload["uid"], 42)
        self.assertGreater(payload["ts"], 0)

    def test_token_tampering_rejected(self):
        token = auth.generate_email_token("user@example.com", "billing_account", 10)
        # Tamper with the signature portion
        parts = token.split(".")
        tampered_token = parts[0] + ".invalidsignature"
        self.assertIsNone(auth.verify_email_token(tampered_token))

    def test_token_expiration(self):
        # Create token with a timestamp from 200 days ago
        old_ts = int(time.time()) - (200 * 86400)
        payload = {"email": "old@example.com", "uid": 1, "cat": "product_updates", "ts": old_ts}
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        import hmac, hashlib
        sig = hmac.new(auth.get_email_token_secret(), payload_b64.encode(), hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
        expired_token = f"{payload_b64}.{sig_b64}"

        # Should be rejected with max_age_days=180
        self.assertIsNone(auth.verify_email_token(expired_token, max_age_days=180))

    def test_legacy_base64_fallback(self):
        legacy_data = {"email": "legacy@example.com", "uid": 88}
        legacy_token = base64.urlsafe_b64encode(json.dumps(legacy_data).encode()).decode()
        payload = auth.verify_email_token(legacy_token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["email"], "legacy@example.com")
        self.assertEqual(payload["uid"], 88)
        self.assertTrue(payload.get("legacy"))

    # ─────────────────────────────────────────────────────────────
    # 2. Category Mapping Engine Tests
    # ─────────────────────────────────────────────────────────────
    def test_category_resolution(self):
        self.assertEqual(email_helper.resolve_category_for_campaign("trip_completed"), "household_activity")
        self.assertEqual(email_helper.resolve_category_for_campaign("invite_reminder_day2"), "household_activity")
        self.assertEqual(email_helper.resolve_category_for_campaign("store_plan"), "shopping_reminders")
        self.assertEqual(email_helper.resolve_category_for_campaign("store_plan_reminder_42"), "shopping_reminders")
        self.assertEqual(email_helper.resolve_category_for_campaign("trial_exp_today"), "billing_account")
        self.assertEqual(email_helper.resolve_category_for_campaign("sub_exp_3days"), "billing_account")
        self.assertEqual(email_helper.resolve_category_for_campaign("nourish_announcement_premium"), "product_updates")
        self.assertEqual(email_helper.resolve_category_for_campaign("still_good_announcement_trial"), "product_updates")
        self.assertEqual(email_helper.resolve_category_for_campaign("solo_nudge"), "tips_reengagement")
        self.assertEqual(email_helper.resolve_category_for_campaign("signup_abandon_day5"), "tips_reengagement")

    # ─────────────────────────────────────────────────────────────
    # 3. Preference CRUD and Category Isolation Tests
    # ─────────────────────────────────────────────────────────────
    @patch("shared.auth._one")
    @patch("shared.auth._run")
    def test_default_preferences_all_active(self, mock_run, mock_one):
        mock_one.return_value = None  # No prior row in email_preferences
        prefs = auth.get_email_preferences("newuser@example.com")
        self.assertTrue(prefs["household_activity"])
        self.assertTrue(prefs["shopping_reminders"])
        self.assertTrue(prefs["billing_account"])
        self.assertTrue(prefs["product_updates"])
        self.assertTrue(prefs["tips_reengagement"])
        self.assertFalse(prefs["unsubscribed_all"])

    @patch("shared.auth.get_email_preferences")
    @patch("shared.auth.update_email_preferences")
    @patch("shared.auth._run")
    def test_granular_unsubscribe_single_category(self, mock_run, mock_update, mock_get):
        mock_get.return_value = {
            "email": "user@example.com",
            "household_activity": True,
            "shopping_reminders": True,
            "billing_account": True,
            "product_updates": True,
            "tips_reengagement": True,
            "unsubscribed_all": False
        }
        auth.unsubscribe_email_category("user@example.com", "shopping_reminders")
        mock_update.assert_called_once()
        saved_prefs = mock_update.call_args[0][1]
        self.assertFalse(saved_prefs["shopping_reminders"])
        self.assertTrue(saved_prefs["household_activity"])
        self.assertTrue(saved_prefs["billing_account"])

    @patch("shared.auth.get_email_preferences")
    @patch("shared.auth.update_email_preferences")
    def test_unsubscribe_all_disables_all_categories(self, mock_update, mock_get):
        mock_get.return_value = {
            "email": "user@example.com",
            "household_activity": True,
            "shopping_reminders": True,
            "billing_account": True,
            "product_updates": True,
            "tips_reengagement": True,
            "unsubscribed_all": False
        }
        auth.unsubscribe_email_category("user@example.com", "all")
        mock_update.assert_called_once()
        saved_prefs = mock_update.call_args[0][1]
        self.assertTrue(saved_prefs["unsubscribed_all"])
        self.assertFalse(saved_prefs["household_activity"])
        self.assertFalse(saved_prefs["shopping_reminders"])
        self.assertFalse(saved_prefs["billing_account"])

    # ─────────────────────────────────────────────────────────────
    # 4. Delivery Gating Tests (Defense-in-Depth)
    # ─────────────────────────────────────────────────────────────
    @patch("shared.auth.is_email_suppressed")
    @patch("shared.auth.get_email_preferences")
    def test_delivery_gating_respects_category_opt_out(self, mock_prefs, mock_suppressed):
        mock_suppressed.return_value = False
        mock_prefs.return_value = {
            "shopping_reminders": False,
            "household_activity": True,
            "billing_account": True,
            "unsubscribed_all": False
        }
        # Shopping reminders should be blocked
        self.assertFalse(auth.is_email_category_allowed("user@example.com", "shopping_reminders"))
        # Other categories remain allowed
        self.assertTrue(auth.is_email_category_allowed("user@example.com", "household_activity"))
        self.assertTrue(auth.is_email_category_allowed("user@example.com", "billing_account"))

    @patch("shared.auth.is_email_suppressed")
    @patch("shared.auth.get_email_preferences")
    def test_hard_suppression_blocks_all_categories(self, mock_prefs, mock_suppressed):
        mock_suppressed.return_value = True  # Hard bounce / spam report
        mock_prefs.return_value = {
            "shopping_reminders": True,
            "household_activity": True,
            "unsubscribed_all": False
        }
        self.assertFalse(auth.is_email_category_allowed("bounced@example.com", "household_activity"))
        self.assertFalse(auth.is_email_category_allowed("bounced@example.com", "billing_account"))

    # ─────────────────────────────────────────────────────────────
    # 5. SendGrid API Gating and RFC 8058 Header Injection Tests
    # ─────────────────────────────────────────────────────────────
    @patch("email_helper.is_email_suppressed_db")
    @patch("shared.auth.is_email_category_allowed")
    @patch("urllib.request.urlopen")
    def test_sendgrid_api_gating_skips_opted_out_recipient(self, mock_urlopen, mock_allowed, mock_supp):
        mock_supp.return_value = False
        mock_allowed.return_value = False  # Opted out of shopping_reminders

        payload = {
            "personalizations": [{"to": [{"email": "optout@example.com"}]}],
            "custom_args": {"campaign": "store_plan"}
        }
        result = email_helper._send_via_api("fake_key", payload)
        self.assertFalse(result)
        mock_urlopen.assert_not_called()

    @patch("email_helper.is_email_suppressed_db")
    @patch("shared.auth.is_email_category_allowed")
    @patch("urllib.request.urlopen")
    def test_sendgrid_api_injects_rfc8058_headers(self, mock_urlopen, mock_allowed, mock_supp):
        mock_supp.return_value = False
        mock_allowed.return_value = True
        mock_resp = MagicMock()
        mock_resp.status = 202
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        payload = {
            "personalizations": [{"to": [{"email": "active@example.com"}]}],
            "custom_args": {"campaign": "store_plan"}
        }
        result = email_helper._send_via_api("fake_key", payload)
        self.assertTrue(result)
        self.assertIn("headers", payload)
        self.assertIn("List-Unsubscribe", payload["headers"])
        self.assertEqual(payload["headers"]["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")

    # ─────────────────────────────────────────────────────────────
    # 6. Web Endpoints Tests
    # ─────────────────────────────────────────────────────────────
    @patch("shared.auth.unsubscribe_email_category")
    def test_web_unsubscribe_endpoint_success(self, mock_unsub):
        token = auth.generate_email_token("shopper@example.com", "shopping_reminders", 42)
        resp = self.client.get(f"/email/unsubscribe?cat=shopping_reminders&token={token}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Unsubscribed Successfully", resp.data)
        self.assertIn(b"shopper@example.com", resp.data)
        self.assertIn(b"Shopping &amp; Store Plans", resp.data)
        self.assertIn(b"Undo Unsubscribe", resp.data)
        mock_unsub.assert_called_once_with("shopper@example.com", "shopping_reminders", 42)

    @patch("shared.auth.resubscribe_email_category")
    def test_web_resubscribe_endpoint_success(self, mock_resub):
        token = auth.generate_email_token("shopper@example.com", "shopping_reminders", 42)
        resp = self.client.get(f"/email/resubscribe?cat=shopping_reminders&token={token}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Resubscribed!", resp.data)
        mock_resub.assert_called_once_with("shopper@example.com", "shopping_reminders", 42)

    @patch("shared.auth.get_email_preferences")
    def test_web_preferences_page_renders_5_categories(self, mock_get):
        mock_get.return_value = {
            "email": "user@example.com",
            "household_activity": True,
            "shopping_reminders": True,
            "billing_account": True,
            "product_updates": False,
            "tips_reengagement": True,
            "unsubscribed_all": False
        }
        token = auth.generate_email_token("user@example.com")
        resp = self.client.get(f"/email/preferences?token={token}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Email Preferences", resp.data)
        self.assertIn(b"Household Activity", resp.data)
        self.assertIn(b"Shopping &amp; Store Plans", resp.data)
        self.assertIn(b"Account &amp; Subscription", resp.data)
        self.assertIn(b"Product &amp; Feature Updates", resp.data)
        self.assertIn(b"Tips &amp; Household Coaching", resp.data)

    @patch("shared.auth.update_email_preferences")
    def test_api_email_preferences_post_success(self, mock_update):
        mock_update.return_value = {"ok": True}
        token = auth.generate_email_token("user@example.com", user_id=15)
        resp = self.client.post("/api/email/preferences", json={
            "token": token,
            "preferences": {
                "shopping_reminders": False,
                "household_activity": True
            }
        })
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get("ok"))
        mock_update.assert_called_once()

    @patch("shared.auth.unsubscribe_email_category")
    def test_rfc8058_list_unsubscribe_post(self, mock_unsub):
        token = auth.generate_email_token("client@example.com", "product_updates")
        resp = self.client.post(f"/api/email/list-unsubscribe?cat=product_updates&token={token}")
        self.assertEqual(resp.status_code, 200)
        mock_unsub.assert_called_once_with("client@example.com", "product_updates", 0)

    # ─────────────────────────────────────────────────────────────
    # 7. In-App User Settings API Tests
    # ─────────────────────────────────────────────────────────────
    @patch("shared.auth.is_logged_in", return_value=True)
    @patch("shared.auth.get_user_id")
    @patch("shared.auth.get_email")
    @patch("shared.auth.get_email_preferences")
    def test_inapp_user_email_preferences_get(self, mock_get_prefs, mock_email, mock_uid, mock_logged_in):
        mock_uid.return_value = 101
        mock_email.return_value = "appuser@example.com"
        mock_get_prefs.return_value = {
            "email": "appuser@example.com",
            "household_activity": True,
            "shopping_reminders": True,
            "billing_account": True,
            "product_updates": True,
            "tips_reengagement": True,
            "unsubscribed_all": False
        }

        # Mock logged-in session
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 101, "email": "appuser@example.com"}

        resp = self.client.get("/api/user/email-preferences")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data.get("ok"))
        self.assertIn("preferences", data)
        self.assertIn("metadata", data)

    # ─────────────────────────────────────────────────────────────
    # 8. Cron Daily Event Pruning Tests
    # ─────────────────────────────────────────────────────────────
    @patch("scripts.cron_daily._run")
    @patch("scripts.cron_daily.is_email_suppressed", return_value=False)
    @patch("shared.auth.is_email_category_allowed")
    @patch("scripts.cron_daily.send_subscription_notice")
    @patch("email_helper.send_store_plan_reminder_email")
    def test_cron_daily_prunes_opted_out_category(self, mock_send_plan, mock_send_sub, mock_allowed, mock_supp, mock_run):
        from scripts.cron_daily import process_email_events

        mock_supp.return_value = False
        # Recipient opted out of shopping_reminders, but accepts billing_account
        def side_effect_allowed(email, cat):
            if cat == "shopping_reminders":
                return False
            return True
        mock_allowed.side_effect = side_effect_allowed
        mock_send_sub.return_value = True

        events = {
            "expiration": {"is_trial": True, "days_left": 0, "can_extend": True, "extension_tier": "15d"},
            "store_plan": {"store_id": 10, "store_name": "Costco", "items_count": 6}
        }

        # Dispatch
        success = process_email_events("member@example.com", "Member", events, user_id=5, household_id=10)
        self.assertTrue(success)
        # Store plan should have been pruned and NEVER sent
        mock_send_plan.assert_not_called()
        # Expiration notice should have been delivered
        mock_send_sub.assert_called_once()


if __name__ == "__main__":
    unittest.main()
