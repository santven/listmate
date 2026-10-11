#!/usr/bin/env python3
"""
Test Suite for Still Good multi-tenant isolation & household auth scoping (Issue #626).

Verifies:
1. Unauthenticated access returns 401 across all Still Good endpoints.
2. Logged-in users without a household association return 401 and NEVER touch Household 1 data.
3. Multi-tenant isolation: Household A cannot read, update, action, or delete Household B items (404).
4. Bulk operations (snooze-all, vacation-freeze) strictly scope to the calling household.
5. Full CRUD lifecycle for legitimate Pro/Premium household users.
6. The Falsiness Rule: _resolve_still_good_hh(db) explicitly checks for not None and > 0, returning None instead of 1.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Defensive mocking of external C-extensions if missing locally
for mod in ["google", "google.oauth2", "google.auth", "google.auth.transport", "google.auth.exceptions", "psycopg2", "psycopg2.extras", "psycopg2.pool", "requests"]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

if "flask_limiter" not in sys.modules:
    mock_limiter = MagicMock()
    mock_limiter.Limiter.return_value.limit.return_value = lambda f: f
    sys.modules["flask_limiter"] = mock_limiter
    sys.modules["flask_limiter.util"] = MagicMock()

os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL", "postgresql://dummy:5432/test")

from app import app, _resolve_still_good_hh
import shared.auth as authmod


class InMemoryStillGoodDb:
    """In-memory mock database tracking still_good_items table."""
    def __init__(self):
        self.items = {}  # id -> dict
        self.users = {}  # user_id -> dict
        self.next_id = 1
        self._cur_result = None
        self._last_rowcount = 0
        self.executed_queries = []

    def execute(self, sql, params=None):
        params = params or ()
        sql_clean = " ".join(sql.strip().split())
        self.executed_queries.append((sql_clean, params))
        self._cur_result = None
        self._last_rowcount = 0

        if sql_clean.startswith("ALTER TABLE"):
            return self

        # User household resolution
        if "SELECT household_id FROM auth_users WHERE id = ?" in sql_clean:
            uid = params[0]
            user = self.users.get(uid)
            if user:
                self._cur_result = [{"household_id": user.get("household_id")}]
            else:
                self._cur_result = []
            return self

        # List items query
        if "SELECT id, household_id, name, location" in sql_clean:
            hhid = params[0]
            matched = [dict(v) for v in self.items.values() if v.get("household_id") == hhid]
            if "AND status = ?" in sql_clean:
                st = params[1]
                matched = [m for m in matched if m.get("status") == st]
            if "AND location = ?" in sql_clean:
                loc = params[-1]
                matched = [m for m in matched if m.get("location") == loc]
            self._cur_result = matched
            return self

        # Stats query
        if "COUNT(*) FILTER" in sql_clean:
            hhid = params[0]
            hh_items = [v for v in self.items.values() if v.get("household_id") == hhid]
            self._cur_result = [{
                "active_fridge": sum(1 for x in hh_items if x.get("status") == "active" and x.get("location") == "fridge"),
                "active_freezer": sum(1 for x in hh_items if x.get("status") == "active" and x.get("location") == "freezer"),
                "thawing_count": sum(1 for x in hh_items if x.get("status") == "active" and x.get("thawing")),
                "wins_7d": sum(1 for x in hh_items if x.get("status") == "consumed"),
                "wins_this_month": sum(1 for x in hh_items if x.get("status") == "consumed"),
                "total_wins": sum(1 for x in hh_items if x.get("status") == "consumed"),
            }]
            return self

        # Insert item
        if sql_clean.startswith("INSERT INTO still_good_items"):
            hhid, name, loc, itype, servings, consume_by, snooze_until, remind_cadence, notes = params
            item_id = self.next_id
            self.next_id += 1
            item = {
                "id": item_id,
                "household_id": hhid,
                "name": name,
                "location": loc,
                "item_type": itype,
                "servings": servings,
                "date_added": "2026-10-10",
                "consume_by": consume_by,
                "snooze_until": snooze_until,
                "remind_cadence": remind_cadence,
                "status": "active",
                "consumed_at": None,
                "discarded_at": None,
                "thawing": False,
                "notes": notes,
                "ai_estimated": False,
                "ai_estimated_at": None,
                "shelf_life_days": 3,
                "ai_tip": "",
                "created_at": "2026-10-10 12:00:00",
                "updated_at": "2026-10-10 12:00:00"
            }
            self.items[item_id] = item
            self._cur_result = [{
                "id": item_id,
                "date_added": "2026-10-10",
                "consume_by": consume_by,
                "snooze_until": snooze_until,
                "remind_cadence": remind_cadence
            }]
            self._last_rowcount = 1
            return self

        # Single item lookups scoped by household_id
        if "SELECT id, location, item_type, thawing, status FROM still_good_items WHERE id = ? AND household_id = ?" in sql_clean or \
           "SELECT id, location, consume_by, status FROM still_good_items WHERE id = ? AND household_id = ?" in sql_clean or \
           "SELECT name, location, item_type, servings, notes, consume_by, ai_estimated FROM still_good_items WHERE id = ? AND household_id = ?" in sql_clean or \
           "SELECT id FROM still_good_items WHERE id = ? AND household_id = ?" in sql_clean:
            i_id, hhid = params
            item = self.items.get(i_id)
            if item and item.get("household_id") == hhid:
                self._cur_result = [dict(item)]
            else:
                self._cur_result = []
            return self

        # Vacation freeze search
        if "SELECT id, name, item_type FROM still_good_items WHERE household_id = ? AND location = 'fridge' AND status = 'active'" in sql_clean:
            hhid = params[0]
            matched = [dict(v) for v in self.items.values() if v.get("household_id") == hhid and v.get("location") == "fridge" and v.get("status") == "active"]
            self._cur_result = matched
            return self

        # Snooze lookup
        if "SELECT TO_CHAR(snooze_until, 'YYYY-MM-DD') as snooze_until, remind_cadence FROM still_good_items WHERE id = ? AND household_id = ?" in sql_clean:
            i_id, hhid = params
            item = self.items.get(i_id)
            if item and item.get("household_id") == hhid:
                self._cur_result = [{"snooze_until": item.get("snooze_until"), "remind_cadence": item.get("remind_cadence")}]
            else:
                self._cur_result = []
            return self

        # Updates
        if sql_clean.startswith("UPDATE still_good_items"):
            if "status = 'consumed'" in sql_clean:
                i_id, hhid = params
                if i_id in self.items and self.items[i_id]["household_id"] == hhid:
                    self.items[i_id]["status"] = "consumed"
                    self._last_rowcount = 1
            elif "status = 'discarded'" in sql_clean:
                i_id, hhid = params
                if i_id in self.items and self.items[i_id]["household_id"] == hhid:
                    self.items[i_id]["status"] = "discarded"
                    self._last_rowcount = 1
            elif "thawing = ?" in sql_clean:
                thaw, i_id, hhid = params
                if i_id in self.items and self.items[i_id]["household_id"] == hhid:
                    self.items[i_id]["thawing"] = thaw
                    self._last_rowcount = 1
            elif "location = 'freezer'" in sql_clean and "WHERE id = ? AND household_id = ?" in sql_clean:
                freeze_days, i_id, hhid = params
                if i_id in self.items and self.items[i_id]["household_id"] == hhid:
                    self.items[i_id]["location"] = "freezer"
                    self.items[i_id]["thawing"] = False
                    self.items[i_id]["snooze_until"] = None
                    self.items[i_id]["remind_cadence"] = "1_week_before"
                    self._last_rowcount = 1
            elif "location = 'fridge'" in sql_clean and "WHERE id = ? AND household_id = ?" in sql_clean:
                fridge_days, i_id, hhid = params
                if i_id in self.items and self.items[i_id]["household_id"] == hhid:
                    self.items[i_id]["location"] = "fridge"
                    self.items[i_id]["thawing"] = False
                    self.items[i_id]["snooze_until"] = None
                    self.items[i_id]["remind_cadence"] = "daily"
                    self._last_rowcount = 1
            elif "WHERE household_id = ? AND status = 'active' AND location = 'fridge'" in sql_clean:
                hhid = params[-1]
                count = 0
                for v in self.items.values():
                    if v.get("household_id") == hhid and v.get("status") == "active" and v.get("location") == "fridge":
                        if "snooze_until = NULL" in sql_clean:
                            v["snooze_until"] = None
                        else:
                            v["snooze_until"] = "2026-10-15"
                        count += 1
                self._last_rowcount = count
            elif "WHERE id = ? AND household_id = ?" in sql_clean:
                i_id = params[-2]
                hhid = params[-1]
                if i_id in self.items and self.items[i_id]["household_id"] == hhid:
                    item = self.items[i_id]
                    if "snooze_until = CURRENT_DATE" in sql_clean or "snooze_until = ?::date" in sql_clean:
                        item["snooze_until"] = "2026-10-15"
                    elif "snooze_until = NULL" in sql_clean:
                        item["snooze_until"] = None
                    for p in params[:-2]:
                        if isinstance(p, str) and p in ["fridge", "freezer"]:
                            item["location"] = p
                        elif isinstance(p, str) and p in ["produce", "home_cooked", "restaurant", "batch_cook", "other"]:
                            item["item_type"] = p
                        elif isinstance(p, int):
                            item["servings"] = p
                        elif isinstance(p, str) and len(p) == 10 and p[4] == "-" and p[7] == "-":
                            item["consume_by"] = p
                        elif isinstance(p, str):
                            item["name"] = p
                    self._last_rowcount = 1
            return self

        # Delete
        if sql_clean.startswith("DELETE FROM still_good_items WHERE id = ? AND household_id = ?"):
            i_id, hhid = params
            if i_id in self.items and self.items[i_id]["household_id"] == hhid:
                del self.items[i_id]
                self._last_rowcount = 1
            else:
                self._last_rowcount = 0
            return self

        return self

    def fetchone(self):
        if self._cur_result is not None and len(self._cur_result) > 0:
            return self._cur_result[0]
        return None

    def fetchall(self):
        if self._cur_result is not None:
            return list(self._cur_result)
        return []

    @property
    def total_changes(self):
        return self._last_rowcount

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class TestStillGoodAuthScoping(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.mock_db = InMemoryStillGoodDb()

        # Prepopulate items in Household 1 (to ensure it is never touched by unassociated users)
        self.mock_db.items[1] = {
            "id": 1,
            "household_id": 1,
            "name": "Household 1 Lasagna",
            "location": "fridge",
            "item_type": "home_cooked",
            "servings": 4,
            "date_added": "2026-10-01",
            "consume_by": "2026-10-05",
            "snooze_until": None,
            "remind_cadence": "daily",
            "status": "active",
            "thawing": False,
            "notes": "Original HH1 meal",
            "ai_estimated": False,
            "created_at": "2026-10-01 10:00:00"
        }

        # Start patches
        self.patcher_reconcile = patch("shared.auth._reconcile_session", side_effect=lambda s: s)
        self.patcher_db = patch("app.get_db", return_value=self.mock_db)
        self.patcher_auth_one = patch("shared.auth._one", side_effect=self._mock_auth_one)

        self.patcher_reconcile.start()
        self.patcher_db.start()
        self.patcher_auth_one.start()

    def tearDown(self):
        self.patcher_auth_one.stop()
        self.patcher_db.stop()
        self.patcher_reconcile.stop()

    def _mock_auth_one(self, query, params=None):
        params = params or ()
        if "FROM auth_households" in query or "WHERE id = ?" in query:
            hhid = params[0] if params else None
            # Return active Pro subscription for households 1, 10, 20
            if hhid in [1, 10, 20]:
                return {"id": hhid, "is_premium": True, "subscription_status": "premium", "trial_ends_at": None}
            # Household 30 is free tier
            if hhid == 30:
                return {"id": 30, "is_premium": False, "subscription_status": "free", "trial_ends_at": None}
        return None

    # ─────────────────────────────────────────────────────────────
    # 1. Direct _resolve_still_good_hh Unit Tests (Falsiness Rule)
    # ─────────────────────────────────────────────────────────────

    def test_resolve_still_good_hh_valid_session(self):
        """When _hh() returns a valid positive ID, _resolve_still_good_hh returns it."""
        with patch("app._hh", return_value=42):
            hhid = _resolve_still_good_hh(self.mock_db)
            self.assertEqual(hhid, 42)

    def test_resolve_still_good_hh_fallback_to_user_table(self):
        """When _hh() is 0 or None, fallback to auth_users table and return positive household_id."""
        self.mock_db.users[100] = {"household_id": 55}
        with patch("app._hh", return_value=0), \
             patch("shared.auth.get_user_id", return_value=100):
            hhid = _resolve_still_good_hh(self.mock_db)
            self.assertEqual(hhid, 55)

    def test_resolve_still_good_hh_falsiness_rule_zero_in_user_table(self):
        """When user row has household_id=0, Falsiness Rule prevents using 0 and falls back to None (NEVER 1)."""
        self.mock_db.users[101] = {"household_id": 0}
        with patch("app._hh", return_value=0), \
             patch("shared.auth.get_user_id", return_value=101):
            hhid = _resolve_still_good_hh(self.mock_db)
            self.assertIsNone(hhid, "Should return None, never 1")

    def test_resolve_still_good_hh_no_user_found_returns_none(self):
        """When user is unassociated, _resolve_still_good_hh returns None (NEVER 1)."""
        with patch("app._hh", return_value=None), \
             patch("shared.auth.get_user_id", return_value=None):
            hhid = _resolve_still_good_hh(self.mock_db)
            self.assertIsNone(hhid, "Must return None instead of fallback 1")

    # ─────────────────────────────────────────────────────────────
    # 2. Unauthenticated / Missing Household Access (401 across endpoints)
    # ─────────────────────────────────────────────────────────────

    def test_unauthenticated_requests_return_401(self):
        """Completely unauthenticated requests must be rejected with 401 across all Still Good endpoints."""
        endpoints = [
            ("GET", "/api/still-good", None),
            ("POST", "/api/still-good", {"name": "Pad Thai"}),
            ("POST", "/api/still-good/1/action", {"action": "consume"}),
            ("POST", "/api/still-good/1/snooze", {"days": 2}),
            ("POST", "/api/still-good/snooze-all", {"days": 2}),
            ("POST", "/api/still-good/vacation-freeze", {}),
            ("PUT", "/api/still-good/1", {"name": "Renamed"}),
            ("DELETE", "/api/still-good/1", None),
        ]
        for method, url, data in endpoints:
            with self.subTest(method=method, url=url):
                if method == "GET":
                    res = self.client.get(url)
                elif method == "POST":
                    res = self.client.post(url, json=data or {})
                elif method == "PUT":
                    res = self.client.put(url, json=data or {})
                elif method == "DELETE":
                    res = self.client.delete(url)
                self.assertEqual(res.status_code, 401)

    def test_authenticated_user_without_household_returns_401_and_protects_hh1(self):
        """Logged-in user without a household association returns 401 and NEVER accesses or alters Household 1."""
        hh1_item_before = dict(self.mock_db.items[1])

        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 999, "household_id": 0, "email": "orphan@example.com"}

        endpoints = [
            ("GET", "/api/still-good", None),
            ("POST", "/api/still-good", {"name": "Hacker Leftover"}),
            ("POST", "/api/still-good/1/action", {"action": "consume"}),
            ("POST", "/api/still-good/1/snooze", {"days": 2}),
            ("POST", "/api/still-good/snooze-all", {"days": 2}),
            ("POST", "/api/still-good/vacation-freeze", {}),
            ("PUT", "/api/still-good/1", {"name": "Compromised Lasagna"}),
            ("DELETE", "/api/still-good/1", None),
        ]

        for method, url, data in endpoints:
            with self.subTest(method=method, url=url):
                if method == "GET":
                    res = self.client.get(url)
                elif method == "POST":
                    res = self.client.post(url, json=data or {})
                elif method == "PUT":
                    res = self.client.put(url, json=data or {})
                elif method == "DELETE":
                    res = self.client.delete(url)

                self.assertEqual(res.status_code, 401)
                body = res.get_json()
                self.assertFalse(body.get("ok"))
                self.assertIn("Authentication required: no household associated with user", body.get("error", ""))

        # Verify Household 1 item was untouched
        self.assertIn(1, self.mock_db.items)
        self.assertEqual(self.mock_db.items[1], hh1_item_before)

    # ─────────────────────────────────────────────────────────────
    # 3. Cross-Household Multi-Tenant Isolation (404 on target mismatch)
    # ─────────────────────────────────────────────────────────────

    def test_cross_household_isolation(self):
        """Household A cannot read, update, action, or delete Household B's items."""
        # Seed items for Household A (10) and Household B (20)
        self.mock_db.items[100] = {
            "id": 100,
            "household_id": 10,
            "name": "HH A Soup",
            "location": "fridge",
            "item_type": "home_cooked",
            "servings": 2,
            "date_added": "2026-10-10",
            "consume_by": "2026-10-13",
            "status": "active",
            "thawing": False,
            "notes": ""
        }
        self.mock_db.items[200] = {
            "id": 200,
            "household_id": 20,
            "name": "HH B Secret Biryani",
            "location": "fridge",
            "item_type": "restaurant",
            "servings": 3,
            "date_added": "2026-10-10",
            "consume_by": "2026-10-11",
            "status": "active",
            "thawing": False,
            "notes": "Do not leak"
        }
        hh_b_item_before = dict(self.mock_db.items[200])

        # Log in as Household A
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 10, "household_id": 10, "email": "a@example.com"}

        # 1. Household A listing items should NOT include Household B's item
        res = self.client.get("/api/still-good")
        self.assertEqual(res.status_code, 200)
        item_ids = [it["id"] for it in res.get_json()["items"]]
        self.assertIn(100, item_ids)
        self.assertNotIn(200, item_ids)

        # 2. Household A attempting to update Household B item returns 404
        res = self.client.put("/api/still-good/200", json={"name": "Attacked Biryani"})
        self.assertEqual(res.status_code, 404)
        self.assertFalse(res.get_json()["ok"])
        self.assertEqual(res.get_json()["error"], "Item not found")

        # 3. Household A attempting to action Household B item returns 404
        res = self.client.post("/api/still-good/200/action", json={"action": "consume"})
        self.assertEqual(res.status_code, 404)
        self.assertFalse(res.get_json()["ok"])
        self.assertEqual(res.get_json()["error"], "Item not found")

        # 4. Household A attempting to snooze Household B item returns 404
        res = self.client.post("/api/still-good/200/snooze", json={"days": 3})
        self.assertEqual(res.status_code, 404)
        self.assertFalse(res.get_json()["ok"])
        self.assertEqual(res.get_json()["error"], "Item not found")

        # 5. Household A attempting to delete Household B item returns 404
        res = self.client.delete("/api/still-good/200")
        self.assertEqual(res.status_code, 404)
        self.assertFalse(res.get_json()["ok"])
        self.assertEqual(res.get_json()["error"], "Item not found")

        # Ensure Household B item is completely untouched
        self.assertIn(200, self.mock_db.items)
        self.assertEqual(self.mock_db.items[200], hh_b_item_before)

    # ─────────────────────────────────────────────────────────────
    # 4. Batch Operations Strictly Scoped to Calling Household
    # ─────────────────────────────────────────────────────────────

    def test_snooze_all_strictly_scoped(self):
        """snooze-all applies ONLY to calling household active fridge items."""
        self.mock_db.items[10] = {"id": 10, "household_id": 10, "status": "active", "location": "fridge", "snooze_until": None}
        self.mock_db.items[11] = {"id": 11, "household_id": 10, "status": "active", "location": "freezer", "snooze_until": None}
        self.mock_db.items[20] = {"id": 20, "household_id": 20, "status": "active", "location": "fridge", "snooze_until": None}

        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 10, "household_id": 10, "email": "a@example.com"}

        res = self.client.post("/api/still-good/snooze-all", json={"days": 2})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])

        # Household A fridge item snoozed
        self.assertIsNotNone(self.mock_db.items[10]["snooze_until"])
        # Household A freezer item NOT snoozed (freezer excluded)
        self.assertIsNone(self.mock_db.items[11]["snooze_until"])
        # Household B fridge item NOT touched
        self.assertIsNone(self.mock_db.items[20]["snooze_until"])

    def test_vacation_freeze_strictly_scoped(self):
        """vacation-freeze moves ONLY calling household active fridge items to freezer."""
        self.mock_db.items[10] = {"id": 10, "household_id": 10, "status": "active", "location": "fridge", "item_type": "home_cooked"}
        self.mock_db.items[20] = {"id": 20, "household_id": 20, "status": "active", "location": "fridge", "item_type": "home_cooked"}

        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 10, "household_id": 10, "email": "a@example.com"}

        res = self.client.post("/api/still-good/vacation-freeze", json={})
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["moved_count"], 1)

        # Household A item moved to freezer
        self.assertEqual(self.mock_db.items[10]["location"], "freezer")
        # Household B item remains in fridge
        self.assertEqual(self.mock_db.items[20]["location"], "fridge")

    # ─────────────────────────────────────────────────────────────
    # 5. Legitimate Pro Household CRUD Flow
    # ─────────────────────────────────────────────────────────────

    def test_pro_household_crud_flow(self):
        """Full CRUD flow for an authorized Pro household."""
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 10, "household_id": 10, "email": "pro@example.com"}

        # 1. Create item
        res = self.client.post("/api/still-good", json={
            "name": "Sunday Pot Roast",
            "location": "fridge",
            "item_type": "home_cooked",
            "servings": 4
        })
        self.assertEqual(res.status_code, 200)
        create_data = res.get_json()
        self.assertTrue(create_data["ok"])
        item_id = create_data["item"]["id"]
        self.assertEqual(create_data["item"]["name"], "Sunday Pot Roast")
        self.assertEqual(self.mock_db.items[item_id]["household_id"], 10)

        # 2. List items
        res = self.client.get("/api/still-good")
        self.assertEqual(res.status_code, 200)
        list_data = res.get_json()
        self.assertTrue(list_data["ok"])
        found = [it for it in list_data["items"] if it["id"] == item_id]
        self.assertEqual(len(found), 1)

        # 3. Update item
        res = self.client.put(f"/api/still-good/{item_id}", json={
            "name": "Sunday Pot Roast (Deluxe)",
            "servings": 5
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])
        self.assertEqual(self.mock_db.items[item_id]["name"], "Sunday Pot Roast (Deluxe)")
        self.assertEqual(self.mock_db.items[item_id]["servings"], 5)

        # 4. Action item (thaw toggle or consume)
        res = self.client.post(f"/api/still-good/{item_id}/action", json={"action": "thaw"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(self.mock_db.items[item_id]["thawing"])

        # 5. Snooze item
        res = self.client.post(f"/api/still-good/{item_id}/snooze", json={"days": 2})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])
        self.assertIsNotNone(self.mock_db.items[item_id]["snooze_until"])

        # 6. Delete item
        res = self.client.delete(f"/api/still-good/{item_id}")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])
        self.assertNotIn(item_id, self.mock_db.items)

        # 7. Repeated delete on now-deleted item returns 404
        res = self.client.delete(f"/api/still-good/{item_id}")
        self.assertEqual(res.status_code, 404)
        self.assertFalse(res.get_json()["ok"])
        self.assertEqual(res.get_json()["error"], "Item not found")

    # ─────────────────────────────────────────────────────────────
    # 6. Paywall Access Check
    # ─────────────────────────────────────────────────────────────

    def test_free_tier_household_blocked_by_paywall(self):
        """Free or expired tier household is blocked with 403 paywall_required."""
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 30, "household_id": 30, "email": "free@example.com"}

        res = self.client.get("/api/still-good")
        self.assertEqual(res.status_code, 403)
        body = res.get_json()
        self.assertFalse(body["ok"])
        self.assertTrue(body["paywall_required"])


if __name__ == "__main__":
    unittest.main()
