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

from app import app, _resolve_still_good_hh, _can_household_access_still_good
import shared.auth as authmod
import datetime
import push_helper


class InMemoryStillGoodDb:
    """In-memory mock database tracking still_good_items table."""
    def __init__(self):
        self.items = {}  # id -> dict
        self.users = {}  # user_id -> dict
        self.list_items = {}  # id -> dict
        self.stores = {}  # id -> dict
        self.now = datetime.datetime(2026, 10, 11, 14, 0, 0)
        self.next_id = 1
        self.next_list_id = 1000
        self._cur_result = None
        self._last_rowcount = 0
        self.executed_queries = []

    def execute(self, sql, params=None):
        params = params or ()
        sql_clean = " ".join(sql.strip().split())
        self.executed_queries.append((sql_clean, params))
        self._cur_result = None
        self._last_rowcount = 0

        if sql_clean.startswith("ALTER TABLE") or sql_clean.startswith("CREATE INDEX"):
            return self

        # Stash candidates query
        if "FROM list_items" in sql_clean and "still_good_stashed_at IS NULL" in sql_clean and "SELECT id, name, category, quantity, store_id, purchased_at" in sql_clean:
            hhid = params[0]
            three_hours_ago = self.now - datetime.timedelta(hours=3)
            forty_eight_hours_ago = self.now - datetime.timedelta(hours=48)
            matched = []
            for item in self.list_items.values():
                if item.get("household_id") != hhid:
                    continue
                if not item.get("purchased"):
                    continue
                if item.get("still_good_stashed_at") is not None:
                    continue
                p_at = item.get("purchased_at")
                t_at = item.get("trip_notified_at")
                quarantine_ok = (t_at is not None and t_at <= three_hours_ago) or (p_at is not None and p_at <= three_hours_ago)
                window_ok = (p_at is not None and p_at >= forty_eight_hours_ago)
                if quarantine_ok and window_ok:
                    matched.append(dict(item))
            matched.sort(key=lambda x: x.get("purchased_at") or self.now, reverse=True)
            self._cur_result = matched
            self._last_rowcount = len(matched)
            return self

        # Stash atomic UPDATE query
        if sql_clean.startswith("UPDATE list_items SET still_good_stashed_at = NOW()"):
            hhid = params[-1]
            target_ids = set(params[:-1])
            claimed = []
            for item_id, item in self.list_items.items():
                if item_id in target_ids and item.get("household_id") == hhid:
                    if item.get("purchased") and item.get("still_good_stashed_at") is None:
                        item["still_good_stashed_at"] = self.now
                        claimed.append({
                            "id": item["id"],
                            "name": item["name"],
                            "category": item.get("category", ""),
                            "purchased_at": item.get("purchased_at"),
                            "store_id": item.get("store_id")
                        })
            self._cur_result = claimed
            self._last_rowcount = len(claimed)
            return self

        # Dismiss sentinel UPDATE query
        if sql_clean.startswith("UPDATE list_items SET still_good_stashed_at = '1970-01-01 00:00:00'"):
            hhid = params[-1]
            target_ids = set(params[:-1])
            dismissed_count = 0
            for item_id, item in self.list_items.items():
                if item_id in target_ids and item.get("household_id") == hhid:
                    if item.get("purchased") and item.get("still_good_stashed_at") is None:
                        item["still_good_stashed_at"] = "1970-01-01 00:00:00"
                        dismissed_count += 1
            self._cur_result = []
            self._last_rowcount = dismissed_count
            return self

        # Delete on uncheck
        if sql_clean.startswith("DELETE FROM still_good_items WHERE list_item_id = ? AND household_id = ? AND status = 'active'"):
            li_id, hhid = params
            deleted = [sg_id for sg_id, sg in list(self.items.items()) if sg.get("list_item_id") == li_id and sg.get("household_id") == hhid and sg.get("status") == "active"]
            for d in deleted:
                del self.items[d]
            self._last_rowcount = len(deleted)
            return self

        # Toggle list item lookups & updates
        if "SELECT * FROM list_items WHERE id = ? AND household_id = ?" in sql_clean:
            item_id, hhid = params
            item = self.list_items.get(item_id)
            if item and item.get("household_id") == hhid:
                self._cur_result = [dict(item)]
            else:
                self._cur_result = []
            return self

        if "UPDATE list_items SET purchased=FALSE" in sql_clean:
            item_id = params[0]
            if item_id in self.list_items:
                self.list_items[item_id]["purchased"] = False
                self.list_items[item_id]["purchased_at"] = None
                self.list_items[item_id]["trip_notified_at"] = None
                self.list_items[item_id]["still_good_stashed_at"] = None
                self._last_rowcount = 1
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

        # Store lookups
        if "SELECT id, name FROM stores WHERE id = ? AND household_id = ?" in sql_clean:
            sid, hhid = params
            store = self.stores.get(sid)
            if store and store.get("household_id") == hhid:
                self._cur_result = [{"id": store["id"], "name": store["name"]}]
            else:
                self._cur_result = []
            return self

        if "SELECT id, name FROM stores WHERE household_id = ? AND name = 'General List' LIMIT 1" in sql_clean:
            hhid = params[0]
            matched = [s for s in self.stores.values() if s.get("household_id") == hhid and s.get("name") == "General List"]
            self._cur_result = matched[:1]
            return self

        if "SELECT id, name FROM stores WHERE household_id = ? ORDER BY id ASC LIMIT 1" in sql_clean:
            hhid = params[0]
            matched = sorted([s for s in self.stores.values() if s.get("household_id") == hhid], key=lambda x: x["id"])
            self._cur_result = matched[:1]
            return self

        if sql_clean.startswith("INSERT INTO stores"):
            hhid = params[-1]
            sid = max(self.stores.keys(), default=0) + 1
            self.stores[sid] = {"id": sid, "name": "General List", "household_id": hhid}
            self._cur_result = [{"id": sid, "name": "General List"}]
            self._last_rowcount = 1
            return self

        # List items deduplication check
        if "FROM list_items" in sql_clean and "purchased = FALSE" in sql_clean and "LOWER(TRIM(name)) = LOWER(TRIM(?))" in sql_clean:
            sid, hhid, name = params
            matched = []
            for li in self.list_items.values():
                if li.get("household_id") == hhid and li.get("store_id") == sid and not li.get("purchased"):
                    if (li.get("name") or "").strip().lower() == (name or "").strip().lower():
                        matched.append({"id": li["id"]})
            self._cur_result = matched
            return self

        # List items category lookup
        if "SELECT category FROM list_items WHERE id = ? AND household_id = ?" in sql_clean:
            li_id, hhid = params
            li = self.list_items.get(li_id)
            if li and li.get("household_id") == hhid:
                self._cur_result = [{"category": li.get("category", "")}]
            else:
                self._cur_result = []
            return self

        # Insert list item
        if sql_clean.startswith("INSERT INTO list_items"):
            hhid, sid, name, cat, added_by, added_by_uid = params
            new_id = getattr(self, "next_list_id", 1000)
            self.next_list_id = new_id + 1
            self.list_items[new_id] = {
                "id": new_id,
                "household_id": hhid,
                "store_id": sid,
                "name": name,
                "category": cat,
                "quantity": "1",
                "added_by": added_by,
                "added_by_user_id": added_by_uid,
                "purchased": False,
                "purchased_at": None,
                "trip_notified_at": None,
                "still_good_stashed_at": None
            }
            self._cur_result = [{"id": new_id}]
            self._last_rowcount = 1
            return self

        # List items query
        if ("SELECT id, household_id, name, location" in sql_clean or "SELECT sgi.id, sgi.household_id, sgi.name, sgi.location" in sql_clean) and "FROM still_good_items" in sql_clean:
            hhid = params[0]
            matched = []
            for v in self.items.values():
                if v.get("household_id") != hhid:
                    continue
                row = dict(v)
                sid = row.get("store_id")
                if sid and sid in self.stores:
                    row["store_name"] = self.stores[sid].get("name", "")
                elif "store_name" not in row:
                    row["store_name"] = ""
                matched.append(row)
            if "AND status = ?" in sql_clean or "AND sgi.status = ?" in sql_clean:
                st = params[1]
                matched = [m for m in matched if m.get("status") == st]
            if "AND location = ?" in sql_clean or "AND sgi.location = ?" in sql_clean:
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
            if "list_item_id" in sql_clean:
                if len(params) == 7:
                    hhid, store_id, name, date_added, consume_by, list_item_id, shelf_life_days = params
                else:
                    hhid, name, date_added, consume_by, list_item_id = params
                    store_id = None
                    shelf_life_days = 5
                item_id = self.next_id
                self.next_id += 1
                item = {
                    "id": item_id,
                    "household_id": hhid,
                    "store_id": store_id,
                    "name": name,
                    "location": "fridge",
                    "item_type": "produce",
                    "servings": 1,
                    "date_added": str(date_added)[:10],
                    "consume_by": str(consume_by)[:10],
                    "snooze_until": None,
                    "remind_cadence": "daily",
                    "status": "active",
                    "consumed_at": None,
                    "discarded_at": None,
                    "thawing": False,
                    "notes": "",
                    "ai_estimated": False,
                    "ai_estimated_at": None,
                    "shelf_life_days": shelf_life_days,
                    "ai_tip": "",
                    "list_item_id": list_item_id,
                    "created_at": "2026-10-10 12:00:00",
                    "updated_at": "2026-10-10 12:00:00"
                }
                self.items[item_id] = item
                self._cur_result = [{"id": item_id}]
                self._last_rowcount = 1
                return self

            if len(params) == 11:
                hhid, name, loc, itype, servings, consume_by, snooze_until, remind_cadence, notes, ai_estimated, ai_tip = params
            else:
                hhid, name, loc, itype, servings, consume_by, snooze_until, remind_cadence, notes = params
                ai_estimated = False
                ai_tip = ""
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
                "ai_estimated": ai_estimated,
                "ai_estimated_at": None,
                "shelf_life_days": 3,
                "ai_tip": ai_tip,
                "created_at": "2026-10-10 12:00:00",
                "updated_at": "2026-10-10 12:00:00"
            }
            self.items[item_id] = item
            self._cur_result = [{
                "id": item_id,
                "date_added": "2026-10-10",
                "consume_by": consume_by,
                "snooze_until": snooze_until,
                "remind_cadence": remind_cadence,
                "ai_estimated": ai_estimated,
                "ai_tip": ai_tip
            }]
            self._last_rowcount = 1
            return self

        # Single item lookups scoped by household_id
        if "SELECT id, location, item_type, thawing, status FROM still_good_items WHERE id = ? AND household_id = ?" in sql_clean or \
           "SELECT id, location, consume_by, status FROM still_good_items WHERE id = ? AND household_id = ?" in sql_clean or \
           "SELECT name, location, item_type, servings, notes, consume_by, ai_estimated FROM still_good_items WHERE id = ? AND household_id = ?" in sql_clean or \
           "SELECT id FROM still_good_items WHERE id = ? AND household_id = ?" in sql_clean or \
           "SELECT id, name, category, store_id, list_item_id FROM still_good_items WHERE id = ? AND household_id = ?" in sql_clean:
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

        # AI estimation query (still_good_ai.py)
        if "FROM still_good_items WHERE status = 'active' AND ai_estimated = FALSE" in sql_clean:
            limit = params[0] if params else 50
            matched = [
                dict(v) for v in sorted(self.items.values(), key=lambda x: x["id"])
                if v.get("status") == "active" and not v.get("ai_estimated")
            ][:limit]
            self._cur_result = matched
            self._last_rowcount = len(matched)
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
                    if "ai_estimated = TRUE" in sql_clean:
                        item["ai_estimated"] = True
                    elif "ai_estimated = FALSE" in sql_clean:
                        item["ai_estimated"] = False
                    if "ai_tip = ''" in sql_clean:
                        item["ai_tip"] = ""
                    if "shelf_life_days = NULL" in sql_clean:
                        item["shelf_life_days"] = None
                    if "ai_estimated_at = NULL" in sql_clean:
                        item["ai_estimated_at"] = None
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
            elif "WHERE id = ?" in sql_clean and "ai_estimated = TRUE" in sql_clean:
                new_cb, safe_days, tip, i_id = params
                if i_id in self.items:
                    self.items[i_id]["consume_by"] = new_cb
                    self.items[i_id]["shelf_life_days"] = safe_days
                    self.items[i_id]["ai_tip"] = tip
                    self.items[i_id]["ai_estimated"] = True
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
            # Household 40 is lifetime VIP grant (status free, is_premium True)
            if hhid == 40:
                return {"id": 40, "is_premium": True, "subscription_status": "free", "trial_ends_at": None}
            # Household 41 is lifetime subscription
            if hhid == 41:
                return {"id": 41, "is_premium": True, "subscription_status": "lifetime", "trial_ends_at": None}
            # Household 42 is canceled
            if hhid == 42:
                return {"id": 42, "is_premium": False, "subscription_status": "canceled", "trial_ends_at": None}
            # Household 43 is expired
            if hhid == 43:
                return {"id": 43, "is_premium": False, "subscription_status": "expired", "trial_ends_at": None}
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
            ("GET", "/api/still-good/stash-candidates", None),
            ("POST", "/api/still-good/stash", {"item_ids": [1]}),
            ("POST", "/api/still-good/1/add-to-list", None),
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
            ("GET", "/api/still-good/stash-candidates", None),
            ("POST", "/api/still-good/stash", {"item_ids": [1]}),
            ("POST", "/api/still-good/1/add-to-list", None),
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

        # 6. Household A attempting to add Household B item to list returns 404
        res = self.client.post("/api/still-good/200/add-to-list")
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

        res_add = self.client.post("/api/still-good/1/add-to-list")
        self.assertEqual(res_add.status_code, 403)
        body_add = res_add.get_json()
        self.assertFalse(body_add["ok"])
        self.assertTrue(body_add["paywall_required"])

    def test_can_household_access_still_good_subscription_status_matrix(self):
        """
        Verify _can_household_access_still_good access rules (Issue #662):
        - Returns True for subscription_status='premium', is_premium=True
        - Returns True for subscription_status='free', is_premium=True (lifetime VIP grant)
        - Returns True for subscription_status='lifetime', is_premium=True
        - Returns False for subscription_status='expired', is_premium=False
        - Returns False for subscription_status='canceled', is_premium=False
        - Returns False for subscription_status='free', is_premium=False
        - Preserves trial validation (active=True, expired=False)
        """
        # Stop default mock to test custom auth returns per case
        self.patcher_auth_one.stop()
        try:
            test_cases = [
                ("premium", True, True, "premium subscription"),
                ("free", True, True, "lifetime VIP grant (status=free, is_premium=True)"),
                ("lifetime", True, True, "lifetime subscription"),
                ("expired", False, False, "expired subscription"),
                ("canceled", False, False, "canceled subscription"),
                ("free", False, False, "free tier without premium"),
            ]

            for status, is_prem, expected, label in test_cases:
                with self.subTest(status=status, is_premium=is_prem, label=label):
                    mock_record = {
                        "id": 999,
                        "is_premium": is_prem,
                        "subscription_status": status,
                        "trial_ends_at": None,
                    }
                    with patch("shared.auth._one", return_value=mock_record):
                        result = _can_household_access_still_good(self.mock_db, 999)
                        self.assertEqual(
                            result,
                            expected,
                            f"Expected {expected} for status='{status}', is_premium={is_prem} ({label}), got {result}"
                        )

            # Trial validation checks
            now = datetime.datetime.now(datetime.timezone.utc)
            # Active trial in the future
            future_trial = (now + datetime.timedelta(days=7)).isoformat()
            with patch("shared.auth._one", return_value={"id": 999, "is_premium": False, "subscription_status": "trial", "trial_ends_at": future_trial}):
                self.assertTrue(_can_household_access_still_good(self.mock_db, 999))

            # Expired trial in the past
            past_trial = (now - datetime.timedelta(days=1)).isoformat()
            with patch("shared.auth._one", return_value={"id": 999, "is_premium": False, "subscription_status": "trial", "trial_ends_at": past_trial}):
                self.assertFalse(_can_household_access_still_good(self.mock_db, 999))

            # Invalid household IDs
            self.assertFalse(_can_household_access_still_good(self.mock_db, 0))
            self.assertFalse(_can_household_access_still_good(self.mock_db, None))
            self.assertFalse(_can_household_access_still_good(self.mock_db, -5))
        finally:
            self.patcher_auth_one.start()

    def test_lifetime_and_vip_tier_households_allowed_through_paywall(self):
        """Households with lifetime or free-VIP status pass the paywall endpoint check."""
        # Household 40 (status='free', is_premium=True)
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 40, "household_id": 40, "email": "vip@example.com"}

        res = self.client.get("/api/still-good")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])

        # Household 41 (status='lifetime', is_premium=True)
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 41, "household_id": 41, "email": "lifetime@example.com"}

        res = self.client.get("/api/still-good")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])

        # Household 42 (status='canceled', is_premium=False)
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 42, "household_id": 42, "email": "canceled@example.com"}

        res = self.client.get("/api/still-good")
        self.assertEqual(res.status_code, 403)
        self.assertTrue(res.get_json()["paywall_required"])

        # Household 43 (status='expired', is_premium=False)
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 43, "household_id": 43, "email": "expired@example.com"}

        res = self.client.get("/api/still-good")
        self.assertEqual(res.status_code, 403)
        self.assertTrue(res.get_json()["paywall_required"])

    # ─────────────────────────────────────────────────────────────
    # 7. Smart Stash Crisper Drawer Tests (Issue #632)
    # ─────────────────────────────────────────────────────────────

    def test_stash_candidates_quarantine_window_and_perishable_filter(self):
        """
        Verify:
        - Items purchased < 3 hours ago: EXCLUDED.
        - Items purchased 3h to 48h ago: INCLUDED.
        - Items purchased > 48h ago: EXCLUDED.
        - Already stashed items: EXCLUDED.
        - Non-perishable items: EXCLUDED.
        - Unchecked (purchased=False) items: EXCLUDED.
        - Suggested consume_by dates calculated properly.
        """
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 101, "household_id": 10, "email": "user101@example.com"}

        ref_now = self.mock_db.now

        # 1. < 3h ago: excluded
        self.mock_db.list_items[101] = {
            "id": 101, "store_id": 1, "name": "Fresh Spinach", "category": "Produce",
            "quantity": "1 bag", "household_id": 10, "purchased": True,
            "purchased_at": ref_now - datetime.timedelta(hours=1),
            "trip_notified_at": ref_now - datetime.timedelta(hours=1),
            "still_good_stashed_at": None
        }

        # 2. 5h ago, Dairy: INCLUDED
        self.mock_db.list_items[102] = {
            "id": 102, "store_id": 1, "name": "Organic Milk", "category": "Dairy",
            "quantity": "1 gal", "household_id": 10, "purchased": True,
            "purchased_at": ref_now - datetime.timedelta(hours=5),
            "trip_notified_at": ref_now - datetime.timedelta(hours=5),
            "still_good_stashed_at": None
        }

        # 3. 10h ago, Meat & Seafood: INCLUDED
        self.mock_db.list_items[103] = {
            "id": 103, "store_id": 1, "name": "Wild Salmon", "category": "Meat & Seafood",
            "quantity": "2 fillets", "household_id": 10, "purchased": True,
            "purchased_at": ref_now - datetime.timedelta(hours=10),
            "trip_notified_at": ref_now - datetime.timedelta(hours=10),
            "still_good_stashed_at": None
        }

        # 4. 20h ago, Bakery: INCLUDED
        self.mock_db.list_items[104] = {
            "id": 104, "store_id": 1, "name": "Sourdough Bread", "category": "Bakery",
            "quantity": "1 loaf", "household_id": 10, "purchased": True,
            "purchased_at": ref_now - datetime.timedelta(hours=20),
            "trip_notified_at": None,
            "still_good_stashed_at": None
        }

        # 5. 5h ago, Pantry (non-perishable): EXCLUDED
        self.mock_db.list_items[105] = {
            "id": 105, "store_id": 1, "name": "Canned Crushed Tomatoes", "category": "Pantry",
            "quantity": "2 cans", "household_id": 10, "purchased": True,
            "purchased_at": ref_now - datetime.timedelta(hours=5),
            "trip_notified_at": ref_now - datetime.timedelta(hours=5),
            "still_good_stashed_at": None
        }

        # 6. 5h ago, Household (non-perishable): EXCLUDED
        self.mock_db.list_items[106] = {
            "id": 106, "store_id": 1, "name": "Paper Towels", "category": "Household",
            "quantity": "1 pack", "household_id": 10, "purchased": True,
            "purchased_at": ref_now - datetime.timedelta(hours=5),
            "trip_notified_at": ref_now - datetime.timedelta(hours=5),
            "still_good_stashed_at": None
        }

        # 7. > 48h ago (55h ago): EXCLUDED
        self.mock_db.list_items[107] = {
            "id": 107, "store_id": 1, "name": "Old Blueberries", "category": "Produce",
            "quantity": "1 pint", "household_id": 10, "purchased": True,
            "purchased_at": ref_now - datetime.timedelta(hours=55),
            "trip_notified_at": ref_now - datetime.timedelta(hours=55),
            "still_good_stashed_at": None
        }

        # 8. 6h ago, but already stashed: EXCLUDED
        self.mock_db.list_items[108] = {
            "id": 108, "store_id": 1, "name": "Fuji Apples", "category": "Produce",
            "quantity": "3 lbs", "household_id": 10, "purchased": True,
            "purchased_at": ref_now - datetime.timedelta(hours=6),
            "trip_notified_at": ref_now - datetime.timedelta(hours=6),
            "still_good_stashed_at": ref_now - datetime.timedelta(hours=2)
        }

        # 9. 4h ago, Empty category item: EXCLUDED
        self.mock_db.list_items[109] = {
            "id": 109, "store_id": 1, "name": "Haldiram Nutcracker Snack", "category": "",
            "quantity": "2", "household_id": 10, "purchased": True,
            "purchased_at": ref_now - datetime.timedelta(hours=4),
            "trip_notified_at": ref_now - datetime.timedelta(hours=4),
            "still_good_stashed_at": None
        }

        # 10. Not purchased: EXCLUDED
        self.mock_db.list_items[110] = {
            "id": 110, "store_id": 1, "name": "Romaine Lettuce", "category": "Produce",
            "quantity": "3 heads", "household_id": 10, "purchased": False,
            "purchased_at": None,
            "trip_notified_at": None,
            "still_good_stashed_at": None
        }

        res = self.client.get("/api/still-good/stash-candidates")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        candidates = data.get("candidates", [])

        candidate_ids = [c["id"] for c in candidates]
        self.assertIn(102, candidate_ids, "Organic Milk (Dairy, 5h ago) must be included")
        self.assertIn(103, candidate_ids, "Wild Salmon (Meat & Seafood, 10h ago) must be included")
        self.assertIn(104, candidate_ids, "Sourdough Bread (Bakery, 20h ago) must be included")

        self.assertNotIn(101, candidate_ids, "1h old item must be excluded by 3h quarantine")
        self.assertNotIn(105, candidate_ids, "Pantry item must be excluded")
        self.assertNotIn(106, candidate_ids, "Household item must be excluded")
        self.assertNotIn(107, candidate_ids, "Item > 48h old must be excluded")
        self.assertNotIn(108, candidate_ids, "Already stashed item must be excluded")
        self.assertNotIn(109, candidate_ids, "Empty category item must be excluded")
        self.assertNotIn(110, candidate_ids, "Unpurchased item must be excluded")

        # Verify suggested consume_by dates
        item_102 = next(c for c in candidates if c["id"] == 102)
        p102_date = (ref_now - datetime.timedelta(hours=5)).date()
        exp102_date = (p102_date + datetime.timedelta(days=5)).isoformat()
        self.assertEqual(item_102["suggested_consume_by"], exp102_date)

    def test_atomic_batch_stash_anchored_dates_and_idempotency(self):
        """
        Verify:
        - Stashing list items atomically marks list_items.still_good_stashed_at = NOW().
        - Creates corresponding still_good_items records anchored to purchased_at::date.
        - Repeated calls are idempotent (stashed_count=0, no duplicate Still Good records).
        """
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 101, "household_id": 10, "email": "user101@example.com"}

        ref_now = self.mock_db.now
        p_time = ref_now - datetime.timedelta(hours=6)
        self.mock_db.list_items[201] = {
            "id": 201, "store_id": 1, "name": "Organic Strawberries", "category": "Produce",
            "quantity": "2 boxes", "household_id": 10, "purchased": True,
            "purchased_at": p_time, "trip_notified_at": p_time, "still_good_stashed_at": None
        }
        self.mock_db.list_items[202] = {
            "id": 202, "store_id": 1, "name": "Greek Yogurt", "category": "Dairy",
            "quantity": "32 oz", "household_id": 10, "purchased": True,
            "purchased_at": p_time, "trip_notified_at": p_time, "still_good_stashed_at": None
        }

        # First stash call
        res = self.client.post("/api/still-good/stash", json={"item_ids": [201, 202]})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("stashed_count"), 2)
        self.assertEqual(len(data.get("items")), 2)

        # Verify list_items updated
        self.assertIsNotNone(self.mock_db.list_items[201]["still_good_stashed_at"])
        self.assertIsNotNone(self.mock_db.list_items[202]["still_good_stashed_at"])

        # Verify still_good_items created
        sg_records = [r for r in self.mock_db.items.values() if r.get("list_item_id") in [201, 202]]
        self.assertEqual(len(sg_records), 2)

        sg_strawberries = next(r for r in sg_records if r["list_item_id"] == 201)
        self.assertEqual(sg_strawberries["household_id"], 10)
        self.assertEqual(sg_strawberries["name"], "Organic Strawberries")
        self.assertEqual(sg_strawberries["location"], "fridge")
        self.assertEqual(sg_strawberries["item_type"], "produce")
        self.assertEqual(sg_strawberries["status"], "active")
        self.assertEqual(sg_strawberries["shelf_life_days"], 5)
        # Date anchoring: date_added = purchased_at::date, consume_by = date_added + 5 days
        expected_added = p_time.date().isoformat()
        expected_consume = (p_time.date() + datetime.timedelta(days=5)).isoformat()
        self.assertEqual(sg_strawberries["date_added"], expected_added)
        self.assertEqual(sg_strawberries["consume_by"], expected_consume)

        # Second stash call (Idempotency test): should claim 0 items without duplicating
        res_repeat = self.client.post("/api/still-good/stash", json={"item_ids": [201, 202]})
        self.assertEqual(res_repeat.status_code, 200)
        data_repeat = res_repeat.get_json()
        self.assertTrue(data_repeat.get("ok"))
        self.assertEqual(data_repeat.get("stashed_count"), 0)
        self.assertEqual(data_repeat.get("items"), [])

        # Total still_good_items for these list items must remain 2
        sg_records_after = [r for r in self.mock_db.items.values() if r.get("list_item_id") in [201, 202]]
        self.assertEqual(len(sg_records_after), 2)

    def test_smart_stash_destructive_edge_cases(self):
        """
        Destructive Edge-Case Testing (QA Gate):
        - Null, empty, and malformed payloads
        - Non-list and missing item_ids keys
        - Coercion of string IDs ('250') and filtering of invalid values (0, negative, non-numeric)
        - Empty list_items table returns empty candidates cleanly
        - Candidate items with NULL or whitespace category correctly treated as uncategorized perishable
        """
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 101, "household_id": 10, "email": "user101@example.com"}

        # 1. Missing body / empty JSON
        res_empty = self.client.post("/api/still-good/stash", json={})
        self.assertEqual(res_empty.status_code, 400)
        self.assertFalse(res_empty.get_json()["ok"])

        # 2. item_ids is None / null
        res_null = self.client.post("/api/still-good/stash", json={"item_ids": None})
        self.assertEqual(res_null.status_code, 400)
        self.assertFalse(res_null.get_json()["ok"])

        # 3. item_ids is a string instead of a list
        res_str = self.client.post("/api/still-good/stash", json={"item_ids": "201"})
        self.assertEqual(res_str.status_code, 400)
        self.assertFalse(res_str.get_json()["ok"])

        # 4. item_ids is empty list
        res_emptylist = self.client.post("/api/still-good/stash", json={"item_ids": []})
        self.assertEqual(res_emptylist.status_code, 200)
        self.assertEqual(res_emptylist.get_json()["stashed_count"], 0)
        self.assertEqual(res_emptylist.get_json()["items"], [])

        # 5. item_ids contains invalid values (0, negative, non-numeric)
        res_invalid = self.client.post("/api/still-good/stash", json={"item_ids": [0, -10, "invalid_string", None]})
        self.assertEqual(res_invalid.status_code, 200)
        self.assertEqual(res_invalid.get_json()["stashed_count"], 0)
        self.assertEqual(res_invalid.get_json()["items"], [])

        # 6. item_ids contains valid string-coercible ID
        ref_now = self.mock_db.now
        p_time = ref_now - datetime.timedelta(hours=4)
        self.mock_db.list_items[250] = {
            "id": 250, "store_id": 1, "name": "Coerced Blueberries", "category": "Produce",
            "quantity": "1 pint", "household_id": 10, "purchased": True,
            "purchased_at": p_time, "trip_notified_at": p_time, "still_good_stashed_at": None
        }
        res_coerce = self.client.post("/api/still-good/stash", json={"item_ids": ["250"]})
        self.assertEqual(res_coerce.status_code, 200)
        self.assertEqual(res_coerce.get_json()["stashed_count"], 1)
        self.assertIsNotNone(self.mock_db.list_items[250]["still_good_stashed_at"])

        # 7. Candidate item with NULL category & whitespace category are excluded (CEO directive: disregard empty category)
        self.mock_db.list_items[251] = {
            "id": 251, "store_id": 1, "name": "Mystery Item", "category": None,
            "quantity": "1 bunch", "household_id": 10, "purchased": True,
            "purchased_at": p_time, "trip_notified_at": p_time, "still_good_stashed_at": None
        }
        self.mock_db.list_items[252] = {
            "id": 252, "store_id": 1, "name": "Haldiram Nutcracker Snack", "category": "   ",
            "quantity": "1 container", "household_id": 10, "purchased": True,
            "purchased_at": p_time, "trip_notified_at": p_time, "still_good_stashed_at": None
        }
        res_cand = self.client.get("/api/still-good/stash-candidates")
        self.assertEqual(res_cand.status_code, 200)
        cand_ids = [c["id"] for c in res_cand.get_json().get("candidates", [])]
        self.assertNotIn(251, cand_ids)
        self.assertNotIn(252, cand_ids)


    def test_uncheck_rollback_cascade_active_vs_consumed_discarded(self):
        """
        Verify:
        - When an item is unchecked (toggled to purchased=FALSE):
          * If Still Good item is 'active', it is DELETED.
          * If Still Good item is 'consumed' or 'discarded', it is NOT deleted.
          * list_items.still_good_stashed_at is reset to NULL.
        """
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 101, "household_id": 10, "email": "user101@example.com"}

        ref_now = self.mock_db.now
        p_time = ref_now - datetime.timedelta(hours=4)

        # Item 301: active Still Good item
        self.mock_db.list_items[301] = {
            "id": 301, "store_id": 1, "name": "Fresh Broccoli", "category": "Produce",
            "quantity": "2 heads", "household_id": 10, "purchased": True,
            "purchased_at": p_time, "trip_notified_at": p_time, "still_good_stashed_at": ref_now
        }
        self.mock_db.items[401] = {
            "id": 401, "household_id": 10, "name": "Fresh Broccoli", "location": "fridge",
            "item_type": "produce", "status": "active", "list_item_id": 301
        }

        # Item 302: consumed Still Good item
        self.mock_db.list_items[302] = {
            "id": 302, "store_id": 1, "name": "Organic Eggs", "category": "Dairy",
            "quantity": "1 dozen", "household_id": 10, "purchased": True,
            "purchased_at": p_time, "trip_notified_at": p_time, "still_good_stashed_at": ref_now
        }
        self.mock_db.items[402] = {
            "id": 402, "household_id": 10, "name": "Organic Eggs", "location": "fridge",
            "item_type": "produce", "status": "consumed", "list_item_id": 302
        }

        # Item 303: discarded Still Good item
        self.mock_db.list_items[303] = {
            "id": 303, "store_id": 1, "name": "Fresh Cilantro", "category": "Produce",
            "quantity": "1 bunch", "household_id": 10, "purchased": True,
            "purchased_at": p_time, "trip_notified_at": p_time, "still_good_stashed_at": ref_now
        }
        self.mock_db.items[403] = {
            "id": 403, "household_id": 10, "name": "Fresh Cilantro", "location": "fridge",
            "item_type": "produce", "status": "discarded", "list_item_id": 303
        }

        # 1. Uncheck Item 301 (Active) -> Still Good item 401 MUST be deleted
        res301 = self.client.post("/api/list/301/toggle")
        self.assertEqual(res301.status_code, 200)
        self.assertFalse(self.mock_db.list_items[301]["purchased"])
        self.assertIsNone(self.mock_db.list_items[301]["still_good_stashed_at"])
        self.assertNotIn(401, self.mock_db.items, "Active Still Good item 401 must be deleted on uncheck")

        # 2. Uncheck Item 302 (Consumed) -> Still Good item 402 must NOT be deleted
        res302 = self.client.post("/api/list/302/toggle")
        self.assertEqual(res302.status_code, 200)
        self.assertFalse(self.mock_db.list_items[302]["purchased"])
        self.assertIsNone(self.mock_db.list_items[302]["still_good_stashed_at"])
        self.assertIn(402, self.mock_db.items, "Consumed Still Good item 402 must NOT be deleted")
        self.assertEqual(self.mock_db.items[402]["status"], "consumed")

        # 3. Uncheck Item 303 (Discarded) -> Still Good item 403 must NOT be deleted
        res303 = self.client.post("/api/list/303/toggle")
        self.assertEqual(res303.status_code, 200)
        self.assertFalse(self.mock_db.list_items[303]["purchased"])
        self.assertIsNone(self.mock_db.list_items[303]["still_good_stashed_at"])
        self.assertIn(403, self.mock_db.items, "Discarded Still Good item 403 must NOT be deleted")
        self.assertEqual(self.mock_db.items[403]["status"], "discarded")

    def test_multi_tenant_isolation_stash_and_candidates(self):
        """
        Verify:
        - Household A cannot see Household B's stash candidates.
        - Household A cannot stash Household B's list items.
        - Household B's items remain untouched when Household A attempts cross-household mutation.
        """
        ref_now = self.mock_db.now
        p_time = ref_now - datetime.timedelta(hours=5)

        # Household B item (household_id=20)
        self.mock_db.list_items[501] = {
            "id": 501, "store_id": 1, "name": "Household B Avocados", "category": "Produce",
            "quantity": "4", "household_id": 20, "purchased": True,
            "purchased_at": p_time, "trip_notified_at": p_time, "still_good_stashed_at": None
        }

        # Log in as Household A (household_id=10)
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 101, "household_id": 10, "email": "user101@example.com"}

        # 1. Candidate lookup: Household A must not see Item 501
        res_cand = self.client.get("/api/still-good/stash-candidates")
        self.assertEqual(res_cand.status_code, 200)
        data_cand = res_cand.get_json()
        cand_ids = [c["id"] for c in data_cand.get("candidates", [])]
        self.assertNotIn(501, cand_ids, "Household A must not see Household B candidates")

        # 2. Cross-household stash attempt: Household A attempts to stash Item 501
        res_stash = self.client.post("/api/still-good/stash", json={"item_ids": [501]})
        self.assertEqual(res_stash.status_code, 200)
        data_stash = res_stash.get_json()
        self.assertEqual(data_stash.get("stashed_count"), 0)
        self.assertEqual(data_stash.get("items"), [])

        # Item 501 must remain unstashed
        self.assertIsNone(self.mock_db.list_items[501]["still_good_stashed_at"])
        self.assertNotIn(501, [r.get("list_item_id") for r in self.mock_db.items.values()])

    @patch("push_helper._init_schema")
    @patch("push_helper._run")
    @patch("push_helper.send_push_to_user")
    def test_check_post_shopping_smart_stash_pushes_dispatch(self, mock_send_push, mock_run, mock_init_schema):
        """Verify post-shopping smart stash push reminder evaluates unstashed items and dispatches."""
        mock_run.side_effect = [
            # 1. Candidate query returns user 101 in household 10
            [
                {
                    "user_id": 101,
                    "household_id": 10,
                    "user_name": "Alice",
                    "user_email": "alice@example.com",
                    "user_timezone": "America/New_York"
                }
            ],
            # 2. Unstashed items query for household 10
            [
                {"id": 20, "name": "Fresh Spinach", "category": "Produce", "purchased_at": "2026-10-11 10:00:00"},
                {"id": 21, "name": "Strawberries", "category": "Produce", "purchased_at": "2026-10-11 10:00:00"}
            ]
        ]
        mock_send_push.return_value = {"sent": 1, "failed": 0, "mock": False}

        res = push_helper.check_post_shopping_smart_stash_pushes(dry_run=False, force_send=True)
        self.assertTrue(res["ok"])
        self.assertEqual(res["candidates"], 1)
        self.assertEqual(res["dispatched"], 1)

        mock_send_push.assert_called_once()
        call_kwargs = mock_send_push.call_args[1]
        self.assertEqual(call_kwargs["user_id"], 101)
        self.assertIn("Stash your fresh groceries", call_kwargs["title"])
        self.assertIn("Fresh Spinach", call_kwargs["body"])
        self.assertEqual(call_kwargs["data"]["campaign"], "still_good_smart_stash_3h")
        self.assertEqual(call_kwargs["data"]["source"], "push_smart_stash_3h")

    @patch("push_helper._init_schema")
    @patch("push_helper._run")
    def test_check_post_shopping_smart_stash_pushes_dry_run(self, mock_run, mock_init_schema):
        """Verify dry-run mode returns candidate copy without dispatching."""
        mock_run.side_effect = [
            [
                {
                    "user_id": 102,
                    "household_id": 10,
                    "user_name": "Bob",
                    "user_email": "bob@example.com",
                    "user_timezone": "America/Chicago"
                }
            ],
            [
                {"id": 25, "name": "Organic Milk", "category": "Dairy", "purchased_at": "2026-10-11 10:00:00"}
            ]
        ]

        res = push_helper.check_post_shopping_smart_stash_pushes(dry_run=True, force_send=True)
        self.assertTrue(res["ok"])
        self.assertEqual(res["candidates"], 1)
        self.assertEqual(res["dispatched"], 0)
        self.assertEqual(len(res["results"]), 1)
        self.assertEqual(res["results"][0]["status"], "dry_run")
        self.assertIn("Organic Milk", res["results"][0]["body"])

    # ─────────────────────────────────────────────────────────────
    # 8. Add to List from Crisper Drawer (Iteration 2)
    # ─────────────────────────────────────────────────────────────

    def test_add_to_list_success_with_store(self):
        """Item with store_id adds to that store list with category, returning 200 and added=True."""
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 101, "household_id": 10, "email": "user101@example.com"}

        self.mock_db.stores[2] = {"id": 2, "name": "Trader Joe's", "household_id": 10}
        self.mock_db.items[701] = {
            "id": 701, "household_id": 10, "store_id": 2, "name": "Organic Honeycrisp Apples",
            "category": "Produce", "location": "fridge", "item_type": "produce", "status": "active"
        }

        res = self.client.post("/api/still-good/701/add-to-list")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("added"))
        self.assertFalse(data.get("already_on_list"))
        self.assertEqual(data.get("store_id"), 2)
        self.assertEqual(data.get("store_name"), "Trader Joe's")
        new_li_id = data.get("list_item_id")
        self.assertIsNotNone(new_li_id)

        # Verify list item exists in mock db
        li = self.mock_db.list_items[new_li_id]
        self.assertEqual(li["name"], "Organic Honeycrisp Apples")
        self.assertEqual(li["store_id"], 2)
        self.assertEqual(li["household_id"], 10)
        self.assertEqual(li["category"], "Produce")
        self.assertFalse(li["purchased"])

    def test_add_to_list_deduplication(self):
        """If item is already on active unpurchased list for target store, return already_on_list=True and do not duplicate."""
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 101, "household_id": 10, "email": "user101@example.com"}

        self.mock_db.stores[2] = {"id": 2, "name": "Trader Joe's", "household_id": 10}
        self.mock_db.items[702] = {
            "id": 702, "household_id": 10, "store_id": 2, "name": "Baby Spinach",
            "category": "Produce", "location": "fridge", "item_type": "produce", "status": "active"
        }
        # Prepopulate active list item in store 2
        self.mock_db.list_items[801] = {
            "id": 801, "household_id": 10, "store_id": 2, "name": "Baby Spinach",
            "category": "Produce", "purchased": False
        }

        res = self.client.post("/api/still-good/702/add-to-list")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertFalse(data.get("added"))
        self.assertTrue(data.get("already_on_list"))
        self.assertEqual(data.get("list_item_id"), 801)
        self.assertEqual(data.get("store_id"), 2)
        self.assertEqual(data.get("store_name"), "Trader Joe's")
        self.assertIn("already on your Trader Joe's list", data.get("message", ""))

    def test_add_to_list_fallback_to_general_list_and_category_inference(self):
        """If item has no store_id, resolve to household General List and infer category."""
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 101, "household_id": 10, "email": "user101@example.com"}

        self.mock_db.stores[1] = {"id": 1, "name": "General List", "household_id": 10}
        # Item with no store_id and no category
        self.mock_db.items[703] = {
            "id": 703, "household_id": 10, "store_id": None, "name": "Bananas",
            "category": "", "location": "fridge", "item_type": "produce", "status": "active"
        }

        res = self.client.post("/api/still-good/703/add-to-list")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("added"))
        self.assertEqual(data.get("store_id"), 1)
        self.assertEqual(data.get("store_name"), "General List")

        new_li = self.mock_db.list_items[data.get("list_item_id")]
        self.assertEqual(new_li["store_id"], 1)
        self.assertEqual(new_li["name"], "Bananas")
        self.assertTrue(len(new_li["category"]) > 0)

    # ─────────────────────────────────────────────────────────────
    # 9. Manual Consume-By Date & AI Estimation Lock (Issue #669)
    # ─────────────────────────────────────────────────────────────

    def test_post_still_good_with_custom_consume_by_locks_ai_and_clears_tip(self):
        """POST /api/still-good with valid custom consume_by sets consume_by, ai_estimated=True, ai_tip=''."""
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 10, "household_id": 10, "email": "pro@example.com"}

        res = self.client.post("/api/still-good", json={
            "name": "Homemade Chicken Curry",
            "location": "fridge",
            "item_type": "home_cooked",
            "servings": 3,
            "consume_by": "2026-10-25"
        })
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertTrue(body["ok"])
        item = body["item"]
        self.assertEqual(item["consume_by"], "2026-10-25")
        self.assertTrue(item["ai_estimated"])
        self.assertEqual(item["ai_tip"], "")

        db_item = self.mock_db.items[item["id"]]
        self.assertEqual(db_item["consume_by"], "2026-10-25")
        self.assertTrue(db_item["ai_estimated"])
        self.assertEqual(db_item["ai_tip"], "")

    def test_post_still_good_without_consume_by_uses_default_and_leaves_ai_unestimated(self):
        """POST /api/still-good with empty or omitted consume_by computes default consume_by and sets ai_estimated=False."""
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 10, "household_id": 10, "email": "pro@example.com"}

        for payload_cb in [None, "", "   "]:
            with self.subTest(consume_by=payload_cb):
                payload = {
                    "name": "Leftover Pizza",
                    "location": "fridge",
                    "item_type": "restaurant",
                    "servings": 2
                }
                if payload_cb is not None:
                    payload["consume_by"] = payload_cb

                res = self.client.post("/api/still-good", json=payload)
                self.assertEqual(res.status_code, 200)
                body = res.get_json()
                self.assertTrue(body["ok"])
                item = body["item"]
                expected_cb = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
                self.assertEqual(item["consume_by"], expected_cb)
                self.assertFalse(item["ai_estimated"])
                self.assertEqual(item["ai_tip"], "")

                db_item = self.mock_db.items[item["id"]]
                self.assertFalse(db_item["ai_estimated"])
                self.assertEqual(db_item["ai_tip"], "")

    def test_post_still_good_malformed_consume_by_returns_400(self):
        """POST /api/still-good with malformed consume_by returns HTTP 400 (never 500)."""
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 10, "household_id": 10, "email": "pro@example.com"}

        bad_inputs = ["not-a-date", "2026-02-30", "2026-13-01", "2026-1-1", 12345, ["2026-10-20"], {"date": "2026-10-20"}]
        for bad_cb in bad_inputs:
            with self.subTest(bad_cb=bad_cb):
                res = self.client.post("/api/still-good", json={
                    "name": "Test Item",
                    "consume_by": bad_cb
                })
                self.assertEqual(res.status_code, 400)
                body = res.get_json()
                self.assertFalse(body["ok"])
                self.assertIn("Invalid consume_by date format", body["error"])

    def test_put_still_good_setting_custom_consume_by_locks_ai_and_clears_tip(self):
        """PUT /api/still-good/<id> setting custom consume_by sets consume_by, ai_estimated=True, ai_tip='' even when other fields change."""
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 10, "household_id": 10, "email": "pro@example.com"}

        self.mock_db.items[850] = {
            "id": 850,
            "household_id": 10,
            "name": "Veggie Soup",
            "location": "fridge",
            "item_type": "home_cooked",
            "servings": 2,
            "date_added": "2026-10-15",
            "consume_by": "2026-10-18",
            "status": "active",
            "ai_estimated": True,
            "ai_tip": "Reheat until steaming hot",
            "shelf_life_days": 3,
            "notes": ""
        }

        res = self.client.put("/api/still-good/850", json={
            "name": "Veggie Soup",
            "location": "freezer",
            "servings": 4,
            "consume_by": "2026-11-30"
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])

        updated = self.mock_db.items[850]
        self.assertEqual(updated["consume_by"], "2026-11-30")
        self.assertEqual(updated["location"], "freezer")
        self.assertEqual(updated["servings"], 4)
        self.assertTrue(updated["ai_estimated"])
        self.assertEqual(updated["ai_tip"], "")
        self.assertIsNone(updated["shelf_life_days"])

    def test_put_still_good_clearing_consume_by_resets_default_and_reenables_ai(self):
        """PUT /api/still-good/<id> clearing consume_by ('') recalculates fallback consume_by and sets ai_estimated=False, ai_tip=''."""
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 10, "household_id": 10, "email": "pro@example.com"}

        self.mock_db.items[851] = {
            "id": 851,
            "household_id": 10,
            "name": "Batch Chili",
            "location": "fridge",
            "item_type": "batch_cook",
            "servings": 6,
            "date_added": "2026-10-15",
            "consume_by": "2026-10-28",
            "status": "active",
            "ai_estimated": True,
            "ai_tip": "Custom tip",
            "shelf_life_days": 10,
            "notes": ""
        }

        res = self.client.put("/api/still-good/851", json={
            "consume_by": ""
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])

        updated = self.mock_db.items[851]
        expected_fallback = (datetime.date.today() + datetime.timedelta(days=5)).strftime("%Y-%m-%d")
        self.assertEqual(updated["consume_by"], expected_fallback)
        self.assertFalse(updated["ai_estimated"])
        self.assertEqual(updated["ai_tip"], "")
        self.assertIsNone(updated["shelf_life_days"])

    def test_put_still_good_malformed_consume_by_returns_400(self):
        """PUT /api/still-good/<id> with malformed consume_by returns HTTP 400."""
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 10, "household_id": 10, "email": "pro@example.com"}

        self.mock_db.items[852] = {
            "id": 852,
            "household_id": 10,
            "name": "Pasta Salad",
            "location": "fridge",
            "item_type": "home_cooked",
            "servings": 2,
            "date_added": "2026-10-15",
            "consume_by": "2026-10-18",
            "status": "active",
            "ai_estimated": False,
            "ai_tip": "",
            "notes": ""
        }

        for bad_cb in ["invalid-date", "2026-02-30", 99999, ["2026-10-20"]]:
            with self.subTest(bad_cb=bad_cb):
                res = self.client.put("/api/still-good/852", json={"consume_by": bad_cb})
                self.assertEqual(res.status_code, 400)
                self.assertFalse(res.get_json()["ok"])
                self.assertEqual(self.mock_db.items[852]["consume_by"], "2026-10-18")

    def test_still_good_ai_skips_household_consume_by_items(self):
        """Verify still_good_ai.enhance_still_good_shelf_life_batch skips items where household provided consume_by (ai_estimated=True)."""
        import still_good_ai
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {"user_id": 10, "household_id": 10, "email": "pro@example.com"}

        # Clear pre-seeded items
        self.mock_db.items.clear()

        # 1. Create item with household custom consume_by -> ai_estimated=True
        res_custom = self.client.post("/api/still-good", json={
            "name": "Household Custom Date Stew",
            "location": "fridge",
            "item_type": "home_cooked",
            "consume_by": "2026-10-29"
        })
        custom_id = res_custom.get_json()["item"]["id"]

        # 2. Create item without custom consume_by -> ai_estimated=False
        res_auto = self.client.post("/api/still-good", json={
            "name": "Auto Date Stir Fry",
            "location": "fridge",
            "item_type": "restaurant"
        })
        auto_id = res_auto.get_json()["item"]["id"]

        with patch("still_good_ai.get_db", return_value=self.mock_db), \
             patch("still_good_ai.close_db"), \
             patch("still_good_ai._discover_gemini_key", return_value=""):
            ai_res = still_good_ai.enhance_still_good_shelf_life_batch()
            self.assertTrue(ai_res["ok"])
            self.assertEqual(ai_res["processed"], 1)
            self.assertEqual(ai_res["enhanced"], 1)

        # Custom item was skipped: consume_by remains 2026-10-29 and ai_tip remains empty
        self.assertEqual(self.mock_db.items[custom_id]["consume_by"], "2026-10-29")
        self.assertEqual(self.mock_db.items[custom_id]["ai_tip"], "")
        self.assertTrue(self.mock_db.items[custom_id]["ai_estimated"])

        # Auto item was processed by AI fallback and got a tip
        self.assertTrue(self.mock_db.items[auto_id]["ai_estimated"])
        self.assertNotEqual(self.mock_db.items[auto_id]["ai_tip"], "")


if __name__ == "__main__":
    unittest.main()
