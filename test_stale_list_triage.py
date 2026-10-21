#!/usr/bin/env python3
"""
Unit and Integration Tests for Stale List Items Selective Triage and Saturday 10am Push (Issue #721).
"""

import datetime
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Defensive mocking of external C-extensions/cloud SDKs if missing in local dev
for mod in [
    "google",
    "google.oauth2",
    "google.auth",
    "google.auth.transport",
    "google.auth.exceptions",
    "psycopg2",
    "psycopg2.extras",
    "psycopg2.pool",
    "requests",
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

if "flask_limiter" not in sys.modules:
    mock_limiter = MagicMock()
    mock_limiter.Limiter.return_value.limit.return_value = lambda f: f
    sys.modules["flask_limiter"] = mock_limiter
    sys.modules["flask_limiter.util"] = MagicMock()

os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL", "postgresql://dummy:5432/test")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from push_helper import check_dormant_list_triage_pushes
from email_helper import send_reengagement_notice


class TestStaleListTriageEndpoints(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    @patch("app._hh")
    @patch("app.get_db")
    def test_get_stale_list_items(self, mock_get_db, mock_hh):
        mock_hh.return_value = 42
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        dt_stale = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=16)
        mock_db.execute.return_value.fetchall.return_value = [
            {
                "id": 101,
                "name": "AA Batteries",
                "category": "Hardware",
                "quantity": "1 pack",
                "store_id": 10,
                "store_name": "Target",
                "added_at": dt_stale,
                "days_ago": 16.0
            },
            {
                "id": 102,
                "name": "Whole Milk",
                "category": "Dairy",
                "quantity": "1 gal",
                "store_id": 12,
                "store_name": "Trader Joe's",
                "added_at": dt_stale,
                "days_ago": 16.0
            }
        ]

        with patch("shared.auth._get", return_value={"id": 1, "email": "user@example.com"}):
            resp = self.app.get("/api/list/stale-items")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("ok"))
            self.assertEqual(data.get("count"), 2)
            items = data.get("items")
            self.assertEqual(items[0]["name"], "AA Batteries")
            self.assertEqual(items[0]["store_name"], "Target")
            self.assertEqual(items[1]["name"], "Whole Milk")
            self.assertEqual(items[1]["store_name"], "Trader Joe's")

    @patch("app.get_display_name", return_value="Tester")
    @patch("shared.auth.get_user_id", return_value=1)
    @patch("app._hh", return_value=42)
    @patch("app.get_db")
    def test_triage_stale_items_retain_and_purchase(self, mock_get_db, mock_hh, mock_uid, mock_name):
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        # Mock cleared rows
        mock_db.execute.return_value.fetchall.return_value = [
            {"id": 102, "name": "Whole Milk", "category": "Dairy", "store_id": 12}
        ]
        mock_db.execute.return_value.fetchone.return_value = {"id": 99}

        payload = {
            "retain_item_ids": [101],
            "clear_item_ids": [102],
            "clear_action": "purchased"
        }

        with patch("shared.auth._get", return_value={"id": 1, "email": "user@example.com"}):
            resp = self.app.post("/api/list/triage-stale", json=payload)
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("ok"))
            self.assertEqual(data.get("retained_count"), 1)
            self.assertEqual(data.get("cleared_count"), 1)
            self.assertEqual(data.get("clear_action"), "purchased")

        exec_calls = [str(call[0][0]) for call in mock_db.execute.call_args_list]
        self.assertTrue(any("UPDATE list_items SET added_at = NOW()" in c for c in exec_calls))
        self.assertTrue(any("UPDATE list_items SET purchased = TRUE" in c for c in exec_calls))
        self.assertTrue(mock_db.commit.called)

    @patch("app.get_display_name", return_value="Tester")
    @patch("shared.auth.get_user_id", return_value=1)
    @patch("app._hh", return_value=42)
    @patch("app.get_db")
    def test_triage_stale_items_delete(self, mock_get_db, mock_hh, mock_uid, mock_name):
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        payload = {
            "retain_item_ids": [],
            "clear_item_ids": [103, 104],
            "clear_action": "delete"
        }

        with patch("shared.auth._get", return_value={"id": 1, "email": "user@example.com"}):
            resp = self.app.post("/api/list/triage-stale", json=payload)
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get("ok"))
            self.assertEqual(data.get("retained_count"), 0)
            self.assertEqual(data.get("cleared_count"), 2)
            self.assertEqual(data.get("clear_action"), "delete")

        exec_calls = [str(call[0][0]) for call in mock_db.execute.call_args_list]
        self.assertTrue(any("DELETE FROM list_items WHERE id IN" in c for c in exec_calls))
        self.assertTrue(mock_db.commit.called)


class TestDormantPushNotification(unittest.TestCase):
    @patch("push_helper._run")
    @patch("push_helper.send_push_to_user")
    def test_check_dormant_list_triage_pushes_dispatch(self, mock_send_push, mock_run):
        mock_run.side_effect = [
            # 1. candidate query
            [
                {
                    "user_id": 5,
                    "user_name": "Alice",
                    "user_email": "alice@example.com",
                    "user_timezone": "America/Chicago",
                    "current_local_dow": 6,
                    "current_local_hour": 10,
                    "household_id": 42,
                    "household_name": "Alice & Bob"
                }
            ],
            # 2. store items preview query
            [
                {
                    "store_name": "Trader Joe's",
                    "store_id": 12,
                    "items_count": 3,
                    "item_names": ["Whole Milk", "Avocados", "Dish Soap"]
                }
            ]
        ]

        mock_send_push.return_value = {"sent": 1, "failed": 0, "mock": False}

        res = check_dormant_list_triage_pushes(target_hour=10, dry_run=False, force_send=True)
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("candidates"), 1)
        self.assertEqual(res.get("dispatched"), 1)

        mock_send_push.assert_called_once()
        args, kwargs = mock_send_push.call_args
        self.assertEqual(kwargs["user_id"], 5)
        self.assertIn("Trader Joe's", kwargs["title"])
        self.assertIn("Whole Milk, Avocados...", kwargs["body"])
        self.assertEqual(kwargs["data"]["action"], "triage_stale")
        self.assertEqual(kwargs["data"]["campaign"], "dormant_list_triage_saturday_10am")
        self.assertEqual(kwargs["data"]["url"], "/?action=triage_stale&source=push_dormant_triage_10am")

    @patch("push_helper._run")
    def test_check_dormant_list_triage_pushes_dry_run(self, mock_run):
        mock_run.side_effect = [
            [
                {
                    "user_id": 5,
                    "user_name": "Alice",
                    "user_email": "alice@example.com",
                    "user_timezone": "America/Chicago",
                    "current_local_dow": 6,
                    "current_local_hour": 10,
                    "household_id": 42,
                    "household_name": "Alice & Bob"
                }
            ],
            [
                {
                    "store_name": "Costco",
                    "store_id": 14,
                    "items_count": 1,
                    "item_names": ["AA Batteries"]
                }
            ]
        ]

        res = check_dormant_list_triage_pushes(target_hour=10, dry_run=True, force_send=True)
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("candidates"), 1)
        self.assertEqual(len(res["results"]), 1)
        self.assertEqual(res["results"][0]["status"], "dry_run")
        self.assertIn("AA Batteries", res["results"][0]["body"])


class TestEnhancedEmailHelper(unittest.TestCase):
    @patch("email_helper._send_via_api", return_value=True)
    @patch.dict("os.environ", {"SENDGRID_API_KEY": "SG.test-fake-key"})
    def test_send_reengagement_notice_with_items_preview(self, mock_send):
        sent = send_reengagement_notice(
            to_email="test@example.com",
            user_name="John",
            user_id=10,
            household_id=20,
            store_name="Trader Joe's",
            items=["Whole Milk", "Avocados", "Eggs"]
        )
        self.assertTrue(sent)
        mock_send.assert_called_once()
        payload = mock_send.call_args[0][1]

        self.assertIn("Still need items at Trader Joe's?", payload["subject"])
        txt_content = payload["content"][0]["value"]
        self.assertIn("Whole Milk", txt_content)
        self.assertIn("Avocados", txt_content)
        self.assertIn("Eggs", txt_content)
        self.assertIn("triage_stale", txt_content)

        html_content = payload["content"][1]["value"]
        self.assertIn("Review & Clean Your List", html_content)
        self.assertIn("triage_stale", html_content)


if __name__ == "__main__":
    unittest.main()
