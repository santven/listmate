#!/usr/bin/env python3
"""
Unit tests for GET /api/nourish/user/nourish-enabled enhancements:
- Returns `has_logged_meals` (bool) and `total_logs` (int)
- Scoped to user_id
- Safe error handling (falls back to has_logged_meals=False, total_logs=0)
"""

import contextlib
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY", "test-secret-key-unit-tests")
os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL", "postgresql://dummy:5432/test")

for mod in [
    "google", "google.oauth2", "google.auth", "google.auth.transport",
    "google.auth.exceptions", "psycopg2", "psycopg2.extras", "psycopg2.pool", "requests"
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

if "flask_limiter" not in sys.modules:
    mock_limiter = MagicMock()
    mock_limiter.Limiter.return_value.limit.return_value = lambda f: f
    sys.modules["flask_limiter"] = mock_limiter
    sys.modules["flask_limiter.util"] = MagicMock()

from app import app


class MockDB:
    def __init__(self, users=None, logs_count_by_user=None, raise_on_count=False):
        self.users = users or {}
        self.logs_count_by_user = logs_count_by_user or {}
        self.raise_on_count = raise_on_count
        self.committed = False
        self.rolled_back = False

    def execute(self, sql, params=None):
        params = tuple(params or ())
        if "FROM auth_users WHERE id = ?" in sql:
            uid = int(params[0])
            enabled = self.users.get(uid, False)
            return MockCursor([{"nourish_enabled": enabled}])
        if "UPDATE auth_users SET nourish_enabled = ? WHERE id = ?" in sql:
            enabled = bool(params[0])
            uid = int(params[1])
            self.users[uid] = enabled
            return MockCursor([])
        if "COUNT(*)" in sql and "nourish_food_logs" in sql:
            if self.raise_on_count:
                raise Exception("Relation 'nourish_food_logs' does not exist")
            uid = int(params[0])
            count = self.logs_count_by_user.get(uid, 0)
            return MockCursor([{"total": count, "count": count}])
        return MockCursor([])

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


class MockCursor:
    def __init__(self, rows):
        self._rows = rows
        self._idx = 0

    def fetchone(self):
        if self._idx < len(self._rows):
            r = self._rows[self._idx]
            self._idx += 1
            return r
        return None

    def fetchall(self):
        return self._rows


class TestNourishUserEnabledLogs(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.app_ctx = app.app_context()
        self.app_ctx.push()

    def tearDown(self):
        self.app_ctx.pop()

    @contextlib.contextmanager
    def _user_context(self, user_id=42, household_id=1, db_instance=None):
        with self.client.session_transaction() as sess:
            sess["listmate_session"] = {
                "user_id": user_id,
                "household_id": household_id,
                "email": f"user{user_id}@example.com",
            }
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch("shared.auth._reconcile_session", side_effect=lambda s: s))
            stack.enter_context(patch("app._ensure_schema"))
            stack.enter_context(patch("shared.auth.get_user_id", return_value=user_id))
            stack.enter_context(patch("shared.auth.get_household_id", return_value=household_id))
            stack.enter_context(patch("app.get_household_id", return_value=household_id))
            stack.enter_context(patch("shared.auth.get_household_status", return_value={"is_read_only": False}))
            if db_instance:
                stack.enter_context(patch("app.get_db", return_value=db_instance))
            yield

    def test_user_with_no_logged_meals(self):
        """User with 0 logs returns has_logged_meals=False, total_logs=0."""
        mock_db = MockDB(users={42: True}, logs_count_by_user={42: 0})
        with self._user_context(user_id=42, db_instance=mock_db):
            resp = self.client.get("/api/nourish/user/nourish-enabled")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data["ok"])
            self.assertTrue(data["enabled"])
            self.assertFalse(data["has_logged_meals"])
            self.assertEqual(data["total_logs"], 0)

    def test_user_with_logged_meals(self):
        """User with 5 logs returns has_logged_meals=True, total_logs=5."""
        mock_db = MockDB(users={42: True}, logs_count_by_user={42: 5})
        with self._user_context(user_id=42, db_instance=mock_db):
            for path in ["/api/nourish/user/nourish-enabled", "/api/user/nourish-enabled"]:
                resp = self.client.get(path)
                self.assertEqual(resp.status_code, 200)
                data = resp.get_json()
                self.assertTrue(data["ok"])
                self.assertTrue(data["enabled"])
                self.assertTrue(data["has_logged_meals"])
                self.assertEqual(data["total_logs"], 5)

    def test_user_isolation(self):
        """User 101 has 0 logs even if other user 202 has 10 logs."""
        mock_db = MockDB(users={101: False, 202: True}, logs_count_by_user={101: 0, 202: 10})
        with self._user_context(user_id=101, db_instance=mock_db):
            resp = self.client.get("/api/nourish/user/nourish-enabled")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data["ok"])
            self.assertFalse(data["enabled"])
            self.assertFalse(data["has_logged_meals"])
            self.assertEqual(data["total_logs"], 0)

    def test_safe_error_handling_when_table_missing(self):
        """If COUNT(*) query fails, endpoint gracefully returns has_logged_meals=False, total_logs=0."""
        mock_db = MockDB(users={42: True}, raise_on_count=True)
        with self._user_context(user_id=42, db_instance=mock_db):
            resp = self.client.get("/api/nourish/user/nourish-enabled")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data["ok"])
            self.assertTrue(data["enabled"])
            self.assertFalse(data["has_logged_meals"])
            self.assertEqual(data["total_logs"], 0)
            self.assertTrue(mock_db.rolled_back)


if __name__ == "__main__":
    unittest.main()
