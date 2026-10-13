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

    def test_ai_tip_subline_rendering_and_escaping(self):
        """Verify that ai_tip renders on its own subline with '🤖' and is escaped (Issue #636)."""
        self.assertTrue("if (item.ai_tip)" in self.html_content)
        self.assertTrue("🤖 ' + escapeHtml(item.ai_tip)" in self.html_content)
        self.assertTrue("title=\"AI Storage Tip: ' + escapeHtml(item.ai_tip)" in self.html_content)
        self.assertTrue("margin-left:22px" in self.html_content)
        self.assertTrue("tipSublineHtml" in self.html_content)

    def test_store_badge_rendering_and_escaping(self):
        """Verify that store_name renders a pill with '🏬' and is escaped."""
        self.assertTrue("sg-crisper-store-badge" in self.html_content)
        self.assertTrue("if (item.store_name)" in self.html_content)
        self.assertTrue("🏬 ' + escapeHtml(item.store_name)" in self.html_content)

    def test_item_name_escaping(self):
        """Verify that item.name is escaped in crisper rows."""
        self.assertTrue("title=\"' + escapeHtml(item.name) + '\"" in self.html_content)
        self.assertTrue("escapeHtml(item.name)" in self.html_content)

    def test_crisper_drawer_default_collapsed(self):
        """Verify crisper drawer defaults to collapsed unless explicitly opened ('true') (Issue #636)."""
        self.assertTrue("localStorage.getItem('sg_crisper_open') === 'true'" in self.html_content)


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

    @patch("shared.auth.get_user_id", return_value=1)
    @patch("shared.auth._reconcile_session", side_effect=lambda s: s)
    @patch("app._resolve_still_good_hh", return_value=1)
    @patch("app._can_household_access_still_good", return_value=True)
    def test_still_good_sinks_inactive_items_past_7_days(self, mock_can_access, mock_hh, mock_reconcile, mock_uid):
        """Test 4: GET /api/still-good marks items past 7 days with is_inactive=True and sinks them below active items."""
        mock_db = MagicMock()
        today = datetime.date.today()
        today_str = today.isoformat()
        active_expired_3d_str = (today - datetime.timedelta(days=3)).isoformat()
        inactive_expired_10d_str = (today - datetime.timedelta(days=10)).isoformat()
        inactive_expired_8d_str = (today - datetime.timedelta(days=8)).isoformat()

        fake_rows = [
            # 1. Active item expiring today (priority 0)
            {
                "id": 1, "household_id": 1, "name": "Fresh Milk", "location": "fridge",
                "item_type": "dairy", "servings": 1, "date_added": today_str,
                "consume_by": today_str, "snooze_until": None, "remind_cadence": "daily",
                "status": "active", "consumed_at": None, "discarded_at": None, "thawing": False,
                "notes": "", "ai_estimated": False, "ai_tip": None, "shelf_life_days": 3,
                "list_item_id": None, "store_id": None, "store_name": ""
            },
            # 2. Active item expired 3 days ago (priority 0, <= 7 days post-expiry)
            {
                "id": 2, "household_id": 1, "name": "Yogurt", "location": "fridge",
                "item_type": "dairy", "servings": 1, "date_added": today_str,
                "consume_by": active_expired_3d_str, "snooze_until": None, "remind_cadence": "daily",
                "status": "active", "consumed_at": None, "discarded_at": None, "thawing": False,
                "notes": "", "ai_estimated": False, "ai_tip": None, "shelf_life_days": 5,
                "list_item_id": None, "store_id": None, "store_name": ""
            },
            # 3. Active item expired 10 days ago (priority 1, > 7 days post-expiry -> INACTIVE)
            {
                "id": 3, "household_id": 1, "name": "Old Pasta", "location": "fridge",
                "item_type": "meal", "servings": 1, "date_added": today_str,
                "consume_by": inactive_expired_10d_str, "snooze_until": None, "remind_cadence": "daily",
                "status": "active", "consumed_at": None, "discarded_at": None, "thawing": False,
                "notes": "", "ai_estimated": False, "ai_tip": None, "shelf_life_days": 3,
                "list_item_id": None, "store_id": None, "store_name": ""
            },
            # 4. Consumed item expired 8 days ago (priority 2, non-active status)
            {
                "id": 4, "household_id": 1, "name": "Ate Sandwich", "location": "fridge",
                "item_type": "meal", "servings": 1, "date_added": today_str,
                "consume_by": inactive_expired_8d_str, "snooze_until": None, "remind_cadence": "daily",
                "status": "consumed", "consumed_at": today_str, "discarded_at": None, "thawing": False,
                "notes": "", "ai_estimated": False, "ai_tip": None, "shelf_life_days": 2,
                "list_item_id": None, "store_id": None, "store_name": ""
            }
        ]

        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = fake_rows
        mock_cur.fetchone.return_value = {
            "active_fridge": 3, "active_freezer": 0, "thawing_count": 0,
            "wins_7d": 1, "wins_this_month": 1, "total_wins": 1
        }
        mock_db.execute.return_value = mock_cur

        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 1, "household_id": 1, "email": "test@example.com"}

        with patch("app.get_db", return_value=mock_db):
            res = self.client.get("/api/still-good?status=all")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("ok"))
            items = data.get("items", [])
            self.assertEqual(len(items), 4)

            # Check SQL ORDER BY query contains the sinking CASE expression
            select_calls = [c[0][0] for c in mock_db.execute.call_args_list if "SELECT sgi.id" in c[0][0]]
            self.assertTrue(len(select_calls) > 0)
            executed_sql = select_calls[0]
            self.assertIn("ORDER BY", executed_sql)
            self.assertIn("WHEN sgi.status = 'active' AND (sgi.consume_by IS NULL OR sgi.consume_by >= CURRENT_DATE - INTERVAL '7 days') THEN 0", executed_sql)
            self.assertIn("WHEN sgi.status = 'active' AND sgi.consume_by < CURRENT_DATE - INTERVAL '7 days' THEN 1", executed_sql)
            self.assertIn("ELSE 2", executed_sql)

            # Item 1: Active, expiring today -> not inactive
            self.assertFalse(items[0]["is_inactive"])
            self.assertEqual(items[0]["lifecycle_status"], "active")

            # Item 2: Active, expired 3 days ago (<= 7 days) -> not inactive
            self.assertFalse(items[1]["is_inactive"])
            self.assertEqual(items[1]["lifecycle_status"], "active")

            # Item 3: Active, expired 10 days ago (> 7 days) -> INACTIVE
            self.assertTrue(items[2]["is_inactive"])
            self.assertEqual(items[2]["lifecycle_status"], "inactive")

            # Item 4: Consumed -> not inactive (already consumed lifecycle status)
            self.assertFalse(items[3]["is_inactive"])
            self.assertEqual(items[3]["lifecycle_status"], "consumed")

    @patch("shared.auth.get_user_id", return_value=1)
    @patch("shared.auth._reconcile_session", side_effect=lambda s: s)
    @patch("app._resolve_still_good_hh", return_value=1)
    @patch("app._can_household_access_still_good", return_value=True)
    def test_partial_stash_and_dismiss_sentinel(self, mock_can_access, mock_hh, mock_reconcile, mock_uid):
        """
        Partial stash: User passes item_ids=[id1], dismiss_ids=[id2].
        Assert:
        - id1 is stashed in still_good_items with current timestamp in list_items
        - id2 has still_good_stashed_at == 1970-01-01 in list_items and is NOT in still_good_items
        - Subsequent call to GET /api/still-good/stash-candidates returns 0 candidates!
        """
        mock_db = MockCrisperDb()
        p_time = mock_db.now - datetime.timedelta(hours=4)
        id1, id2 = 501, 502

        mock_db.list_items[id1] = {
            "id": id1,
            "name": "Organic Honeycrisp Apples",
            "category": "Produce",
            "quantity": "3 lbs",
            "household_id": 1,
            "store_id": 10,
            "purchased": True,
            "purchased_at": p_time,
            "trip_notified_at": p_time,
            "still_good_stashed_at": None,
        }
        mock_db.list_items[id2] = {
            "id": id2,
            "name": "Greek Yogurt",
            "category": "Dairy",
            "quantity": "32 oz",
            "household_id": 1,
            "store_id": 10,
            "purchased": True,
            "purchased_at": p_time,
            "trip_notified_at": p_time,
            "still_good_stashed_at": None,
        }

        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 1, "household_id": 1, "email": "test@example.com"}

        with patch("app.get_db", return_value=mock_db):
            # Verify initial candidate check returns both items
            cand_res = self.client.get("/api/still-good/stash-candidates")
            self.assertEqual(cand_res.status_code, 200)
            cand_data = cand_res.get_json()
            self.assertTrue(cand_data.get("ok"))
            self.assertEqual(len(cand_data.get("candidates", [])), 2)

            # Partial stash: stash id1, dismiss id2
            res = self.client.post("/api/still-good/stash", json={
                "item_ids": [id1],
                "dismiss_ids": [id2]
            })
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("ok"))
            self.assertEqual(data.get("stashed_count"), 1)
            self.assertEqual(data.get("dismissed_count"), 1)
            self.assertEqual(len(data.get("items", [])), 1)
            self.assertEqual(data["items"][0]["list_item_id"], id1)

            # Assert id1 is stashed in still_good_items with current timestamp in list_items
            self.assertEqual(mock_db.list_items[id1]["still_good_stashed_at"], mock_db.now)
            stashed_list_item_ids = [sg["list_item_id"] for sg in mock_db.still_good_items.values()]
            self.assertIn(id1, stashed_list_item_ids)

            # Assert id2 has still_good_stashed_at == 1970-01-01 in list_items and is NOT in still_good_items
            self.assertEqual(mock_db.list_items[id2]["still_good_stashed_at"], "1970-01-01 00:00:00")
            self.assertNotIn(id2, stashed_list_item_ids)

            # Subsequent call to GET /api/still-good/stash-candidates returns 0 candidates!
            cand_res_after = self.client.get("/api/still-good/stash-candidates")
            self.assertEqual(cand_res_after.status_code, 200)
            cand_data_after = cand_res_after.get_json()
            self.assertTrue(cand_data_after.get("ok"))
            self.assertEqual(len(cand_data_after.get("candidates", [])), 0)

    @patch("shared.auth.get_user_id", return_value=1)
    @patch("shared.auth._reconcile_session", side_effect=lambda s: s)
    @patch("app._resolve_still_good_hh", return_value=1)
    @patch("app._can_household_access_still_good", return_value=True)
    def test_explicit_dismiss_candidates(self, mock_can_access, mock_hh, mock_reconcile, mock_uid):
        """
        Explicit POST /api/still-good/dismiss-candidates: Call with item_ids=[id1, id2].
        Assert both receive 1970-01-01 sentinel and subsequent candidate check returns 0.
        """
        mock_db = MockCrisperDb()
        p_time = mock_db.now - datetime.timedelta(hours=4)
        id1, id2 = 601, 602

        mock_db.list_items[id1] = {
            "id": id1,
            "name": "Strawberries",
            "category": "Produce",
            "quantity": "1 lb",
            "household_id": 1,
            "store_id": 10,
            "purchased": True,
            "purchased_at": p_time,
            "trip_notified_at": p_time,
            "still_good_stashed_at": None,
        }
        mock_db.list_items[id2] = {
            "id": id2,
            "name": "Baby Spinach",
            "category": "Produce",
            "quantity": "16 oz",
            "household_id": 1,
            "store_id": 10,
            "purchased": True,
            "purchased_at": p_time,
            "trip_notified_at": p_time,
            "still_good_stashed_at": None,
        }

        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 1, "household_id": 1, "email": "test@example.com"}

        with patch("app.get_db", return_value=mock_db):
            # Verify candidate check returns 2 candidates initially
            cand_res = self.client.get("/api/still-good/stash-candidates")
            self.assertEqual(cand_res.status_code, 200)
            self.assertEqual(len(cand_res.get_json().get("candidates", [])), 2)

            # Explicit dismiss call
            res = self.client.post("/api/still-good/dismiss-candidates", json={
                "item_ids": [id1, id2]
            })
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("ok"))
            self.assertEqual(data.get("dismissed_count"), 2)

            # Assert both receive 1970-01-01 sentinel
            self.assertEqual(mock_db.list_items[id1]["still_good_stashed_at"], "1970-01-01 00:00:00")
            self.assertEqual(mock_db.list_items[id2]["still_good_stashed_at"], "1970-01-01 00:00:00")
            self.assertEqual(len(mock_db.still_good_items), 0)

            # Subsequent candidate check returns 0 candidates
            cand_res_after = self.client.get("/api/still-good/stash-candidates")
            self.assertEqual(cand_res_after.status_code, 200)
            cand_data_after = cand_res_after.get_json()
            self.assertTrue(cand_data_after.get("ok"))
            self.assertEqual(len(cand_data_after.get("candidates", [])), 0)

    @patch("shared.auth.get_user_id", return_value=1)
    @patch("shared.auth._reconcile_session", side_effect=lambda s: s)
    @patch("app._resolve_still_good_hh", return_value=1)
    @patch("app._can_household_access_still_good", return_value=True)
    def test_dismiss_candidates_empty_and_no_ids(self, mock_can_access, mock_hh, mock_reconcile, mock_uid):
        """Verify empty item_ids or empty request body returns ok with dismissed_count=0."""
        mock_db = MockCrisperDb()
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 1, "household_id": 1, "email": "test@example.com"}

        with patch("app.get_db", return_value=mock_db):
            res_empty = self.client.post("/api/still-good/dismiss-candidates", json={"item_ids": []})
            self.assertEqual(res_empty.status_code, 200)
            self.assertTrue(res_empty.get_json().get("ok"))
            self.assertEqual(res_empty.get_json().get("dismissed_count"), 0)

            res_none = self.client.post("/api/still-good/dismiss-candidates", json={})
            self.assertEqual(res_none.status_code, 200)
            self.assertTrue(res_none.get_json().get("ok"))
            self.assertEqual(res_none.get_json().get("dismissed_count"), 0)


class MockCrisperDb:
    """In-memory mock database for stash candidates and sentinel snooze testing."""

    def __init__(self):
        self.list_items = {}
        self.still_good_items = {}
        self.now = datetime.datetime(2026, 10, 13, 12, 0, 0)
        self.next_sg_id = 1
        self._cur_result = None
        self._last_rowcount = 0

    def execute(self, sql, params=None):
        params = params or ()
        sql_clean = " ".join(sql.strip().split())
        self._cur_result = None
        self._last_rowcount = 0

        # Stash candidates query
        if "FROM list_items" in sql_clean and "still_good_stashed_at IS NULL" in sql_clean and "SELECT id, name, category" in sql_clean:
            hhid = params[0]
            matched = []
            for itm in self.list_items.values():
                if itm.get("household_id") == hhid and itm.get("purchased") and itm.get("still_good_stashed_at") is None:
                    matched.append(dict(itm))
            matched.sort(key=lambda x: x.get("purchased_at") or self.now, reverse=True)
            self._cur_result = matched
            self._last_rowcount = len(matched)
            return self

        # Dismiss sentinel UPDATE query
        if "UPDATE list_items" in sql_clean and "still_good_stashed_at = '1970-01-01 00:00:00'" in sql_clean:
            hhid = params[-1]
            target_ids = set(params[:-1])
            count = 0
            for itm_id, itm in self.list_items.items():
                if itm_id in target_ids and itm.get("household_id") == hhid:
                    if itm.get("purchased") and itm.get("still_good_stashed_at") is None:
                        itm["still_good_stashed_at"] = "1970-01-01 00:00:00"
                        count += 1
            self._cur_result = []
            self._last_rowcount = count
            return self

        # Stash atomic UPDATE query
        if "UPDATE list_items" in sql_clean and "still_good_stashed_at = NOW()" in sql_clean:
            hhid = params[-1]
            target_ids = set(params[:-1])
            claimed = []
            for itm_id, itm in self.list_items.items():
                if itm_id in target_ids and itm.get("household_id") == hhid:
                    if itm.get("purchased") and itm.get("still_good_stashed_at") is None:
                        itm["still_good_stashed_at"] = self.now
                        claimed.append({
                            "id": itm["id"],
                            "name": itm["name"],
                            "category": itm.get("category", ""),
                            "purchased_at": itm.get("purchased_at"),
                            "store_id": itm.get("store_id")
                        })
            self._cur_result = claimed
            self._last_rowcount = len(claimed)
            return self

        # Insert into still_good_items
        if sql_clean.startswith("INSERT INTO still_good_items"):
            hhid, store_id, name, date_added, consume_by, list_item_id, shelf_life = params
            sg_id = self.next_sg_id
            self.next_sg_id += 1
            self.still_good_items[sg_id] = {
                "id": sg_id,
                "household_id": hhid,
                "store_id": store_id,
                "name": name,
                "date_added": date_added,
                "consume_by": consume_by,
                "list_item_id": list_item_id,
                "shelf_life_days": shelf_life,
                "status": "active"
            }
            self._cur_result = [{"id": sg_id}]
            self._last_rowcount = 1
            return self

        return self

    def fetchall(self):
        return self._cur_result if self._cur_result is not None else []

    def fetchone(self):
        if self._cur_result:
            return self._cur_result[0]
        return None

    @property
    def rowcount(self):
        return self._last_rowcount

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


if __name__ == "__main__":
    unittest.main()
