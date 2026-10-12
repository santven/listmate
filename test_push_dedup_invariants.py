#!/usr/bin/env python3
"""
Test suite for Push Notification Deduplication and Entity-Level Invariants (Issue #645).
Verifies:
1. Dual-layer deduplication in push_helper.py (push_notifications_log + list_items.stash_notified_at).
2. Candidate queries exclude items where stash_notified_at IS NOT NULL.
3. Items are stamped with stash_notified_at upon notification dispatch.
4. Unchecking list items resets stash_notified_at to NULL.
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

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

import push_helper
from app import app


class TestPushDedupInvariants(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.client = app.test_client()

    @patch("push_helper._init_schema")
    @patch("push_helper._run")
    @patch("push_helper.send_push_to_user")
    def test_smart_stash_stamps_entity_stash_notified_at(self, mock_send_push, mock_run, mock_init_schema):
        """Verify that dispatching a smart stash push stamps candidate items with stash_notified_at."""
        mock_send_push.return_value = {"sent": 1, "failed": 0, "mock": False}

        # Mock candidate user
        mock_run.side_effect = [
            # 1. candidate query returns 1 user
            [{"user_id": 79, "household_id": 58, "user_email": "tim@example.com", "user_timezone": "America/Denver"}],
            # 2. unstashed_items query returns 2 produce items
            [
                {"id": 101, "name": "Tomatoes", "category": "Produce", "purchased_at": "2026-10-11 18:00:00"},
                {"id": 102, "name": "Cilantro", "category": "Produce", "purchased_at": "2026-10-11 18:00:00"}
            ],
            # 3. UPDATE list_items SET stash_notified_at = NOW() ...
            None
        ]

        res = push_helper.check_post_shopping_smart_stash_pushes(dry_run=False, force_send=True)

        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("dispatched"), 1)
        mock_send_push.assert_called_once()

        # Verify UPDATE was called to stamp items
        update_calls = [c for c in mock_run.call_args_list if "UPDATE list_items SET stash_notified_at = NOW()" in str(c)]
        self.assertEqual(len(update_calls), 1)
        sql, params = update_calls[0][0]
        self.assertIn("stash_notified_at = NOW()", sql)
        self.assertEqual(params, (58, [101, 102]))

    def test_candidate_query_filters_stash_notified_at(self):
        """Verify that candidate SQL query filters out items that already have stash_notified_at set."""
        import inspect
        src = inspect.getsource(push_helper.check_post_shopping_smart_stash_pushes)
        self.assertIn("AND li.stash_notified_at IS NULL", src)
        self.assertIn("AND stash_notified_at IS NULL", src)

    def test_timezone_utc_casting_and_20h_guard(self):
        """Verify that all push reminder queries use (created_at AT TIME ZONE 'UTC') and the 20h guard."""
        import inspect
        for fn in [
            push_helper.check_post_shopping_smart_stash_pushes,
            push_helper.check_still_good_fridge_lunch_pushes,
            push_helper.check_still_good_produce_expiry_pushes,
            push_helper.check_still_good_freezer_expiry_pushes
        ]:
            src = inspect.getsource(fn)
            self.assertIn("INTERVAL '20 hours'", src, f"{fn.__name__} missing 20-hour sliding window guard")
            self.assertIn("pnl.created_at AT TIME ZONE 'UTC'", src, f"{fn.__name__} missing UTC source cast")

    def test_uncheck_resets_stash_notified_at(self):
        """Verify that unchecking a list item resets stash_notified_at to NULL."""
        import inspect
        from app import toggle_list_item, sync_offline_actions
        toggle_src = inspect.getsource(toggle_list_item)
        self.assertIn("stash_notified_at=NULL", toggle_src)
        sync_src = inspect.getsource(sync_offline_actions)
        self.assertIn("stash_notified_at=NULL", sync_src)


if __name__ == "__main__":
    unittest.main()
