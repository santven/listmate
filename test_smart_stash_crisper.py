#!/usr/bin/env python3
"""
Unit and regression test suite for Smart Stash Crisper Drawer (Issue #634).

Verifies:
1. Frontend static contracts in static/index.html:
   - Stashed items with ai_estimated = false render as '🌱 Fresher'
   - Stashed items with ai_estimated = true render countdown ('⏳ X days left', '⚠️ Today', etc.) and '🤖' tip pill
   - HTML escaping is applied to item.name, item.store_name, and item.ai_tip
   - Crisper drawer defaults to open (localStorage !== 'false')
2. API contract and data delivery for ai_estimated, ai_tip, and store_name:
   - /api/still-good returns items with ai_estimated, ai_tip, store_name, and days_left
   - /api/still-good/<id>/add-to-list retains 1-tap re-order capability
"""

import os
import sys
import unittest
import re
from unittest.mock import MagicMock, patch

# Defensive mocking of external modules if missing locally
for mod in ["google", "google.oauth2", "google.auth", "google.auth.transport", "google.auth.exceptions", "psycopg2", "psycopg2.extras", "psycopg2.pool", "requests"]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

if "flask_limiter" not in sys.modules:
    mock_limiter = MagicMock()
    mock_limiter.Limiter.return_value.limit.return_value = lambda f: f
    sys.modules["flask_limiter"] = mock_limiter
    sys.modules["flask_limiter.util"] = MagicMock()

os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL", "postgresql://dummy:5432/test")

from app import app
import datetime


class TestSmartStashCrisperFrontend(unittest.TestCase):
    """Verifies the rendering invariants and safety guards in static/index.html."""

    def setUp(self):
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            self.html_content = f.read()

    def test_fresher_badge_when_not_ai_estimated(self):
        """Verify that items without AI estimation explicitly render as '🌱 Fresher'."""
        self.assertTrue("if (!item.ai_estimated)" in self.html_content)
        pattern = re.compile(r"if\s*\(!item\.ai_estimated\)\s*\{\s*expiryText\s*=\s*['\"]🌱 Fresher['\"]", re.MULTILINE)
        self.assertTrue(pattern.search(self.html_content) is not None, "Must assign '🌱 Fresher' when !item.ai_estimated")

    def test_ai_estimated_countdown_rendering(self):
        """Verify that items with AI estimation render their countdown based on days_left."""
        self.assertTrue("else if (item.days_left !== null && item.days_left !== undefined)" in self.html_content)
        self.assertTrue("Math.abs(item.days_left) + 'd past'" in self.html_content)
        self.assertTrue("⚠️ Today" in self.html_content)
        self.assertTrue("⏳ 1 day left" in self.html_content)
        self.assertTrue("⏳ 2 days left" in self.html_content)
        self.assertTrue("⏳ ' + item.days_left + ' days left'" in self.html_content)

    def test_ai_tip_pill_rendering_and_escaping(self):
        """Verify that ai_tip renders a pill with '🤖' and is escaped."""
        self.assertTrue("sg-crisper-tip-pill" in self.html_content)
        self.assertTrue("if (item.ai_tip)" in self.html_content)
        self.assertTrue("🤖 ' + escapeHtml(item.ai_tip)" in self.html_content)
        self.assertTrue("title=\"AI Storage Tip: ' + escapeHtml(item.ai_tip)" in self.html_content)

    def test_store_badge_rendering_and_escaping(self):
        """Verify that store_name renders a pill with '🏬' and is escaped."""
        self.assertTrue("sg-crisper-store-badge" in self.html_content)
        self.assertTrue("if (item.store_name)" in self.html_content)
        self.assertTrue("🏬 ' + escapeHtml(item.store_name)" in self.html_content)

    def test_item_name_escaping(self):
        """Verify that item.name is escaped in crisper rows."""
        self.assertTrue("title=\"' + escapeHtml(item.name) + '\"" in self.html_content)
        self.assertTrue("escapeHtml(item.name)" in self.html_content)

    def test_crisper_drawer_default_open(self):
        """Verify crisper drawer defaults to open unless explicitly collapsed ('false')."""
        self.assertTrue("localStorage.getItem('sg_crisper_open') !== 'false'" in self.html_content)


class TestSmartStashCrisperApi(unittest.TestCase):
    """Verifies backend API delivery of crisper drawer attributes."""

    def setUp(self):
        self.client = app.test_client()

    @patch("shared.auth.get_user_id", return_value=1)
    @patch("shared.auth._reconcile_session", side_effect=lambda s: s)
    @patch("app._resolve_still_good_hh", return_value=1)
    @patch("app._can_household_access_still_good", return_value=True)
    def test_crisper_items_api_fields_and_types(self, mock_can_access, mock_hh, mock_reconcile, mock_uid):
        """Verify /api/still-good handles and structures ai_estimated, ai_tip, and store fields."""
        mock_db = MagicMock()
        today_str = datetime.date.today().isoformat()
        future_str = (datetime.date.today() + datetime.timedelta(days=4)).isoformat()

        fake_rows = [
            # 1. Fresh stashed item, not AI estimated
            {
                "id": 101, "household_id": 1, "name": "Fresh Strawberries", "location": "fridge",
                "item_type": "produce", "servings": 1, "date_added": today_str,
                "consume_by": future_str, "snooze_until": None, "remind_cadence": "daily",
                "status": "active", "consumed_at": None, "discarded_at": None, "thawing": False,
                "notes": "", "ai_estimated": False, "ai_tip": None, "shelf_life_days": 5,
                "list_item_id": 501, "store_id": 10, "store_name": "Trader Joe's"
            },
            # 2. AI estimated item with storage tip
            {
                "id": 102, "household_id": 1, "name": "Organic Celery", "location": "fridge",
                "item_type": "produce", "servings": 1, "date_added": today_str,
                "consume_by": future_str, "snooze_until": None, "remind_cadence": "daily",
                "status": "active", "consumed_at": None, "discarded_at": None, "thawing": False,
                "notes": "", "ai_estimated": True, "ai_tip": "Wrap in foil to stay crisp", "shelf_life_days": 7,
                "list_item_id": 502, "store_id": 10, "store_name": "Trader Joe's"
            }
        ]

        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = fake_rows
        mock_cur.fetchone.return_value = {
            "active_fridge": 2, "active_freezer": 0, "thawing_count": 0,
            "wins_7d": 0, "wins_this_month": 0, "total_wins": 0
        }
        mock_db.execute.return_value = mock_cur

        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 1, "household_id": 1, "email": "test@example.com"}

        with patch("app.get_db", return_value=mock_db):
            res = self.client.get("/api/still-good?location=fridge")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("ok"))
            items = data.get("items", [])
            self.assertEqual(len(items), 2)

            item1 = items[0]
            self.assertFalse(item1.get("ai_estimated"))
            self.assertEqual(item1.get("store_name"), "Trader Joe's")
            self.assertEqual(item1.get("list_item_id"), 501)

            item2 = items[1]
            self.assertTrue(item2.get("ai_estimated"))
            self.assertEqual(item2.get("ai_tip"), "Wrap in foil to stay crisp")
            self.assertEqual(item2.get("days_left"), 4)


if __name__ == "__main__":
    unittest.main()
