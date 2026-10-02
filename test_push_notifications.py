import os
import unittest
from unittest.mock import patch, MagicMock

import shared.auth as authmod
import push_helper


class TestPushNotifications(unittest.TestCase):
    def setUp(self):
        self.mock_store = {}
        self.patcher_init = patch("shared.auth._init_schema", return_value=True)
        self.patcher_run = patch("shared.auth._run", side_effect=self._mock_run)
        self.patcher_one = patch("shared.auth._one", side_effect=self._mock_one)
        self.patcher_init.start()
        self.patcher_run.start()
        self.patcher_one.start()

    def tearDown(self):
        self.patcher_one.stop()
        self.patcher_run.stop()
        self.patcher_init.stop()

    def _mock_run(self, query, params=None):
        q = " ".join(query.strip().split())
        params = params or ()

        if "DELETE FROM push_subscriptions" in q:
            uid, platform = params[0], params[1]
            to_del = [tok for tok, row in self.mock_store.items()
                      if row.get("user_id") == uid and row.get("platform") == platform and (tok.startswith("status:") or tok.startswith("denied:"))]
            for tok in to_del:
                del self.mock_store[tok]
            return []

        if "INSERT INTO push_subscriptions" in q:
            uid, hhid, token, platform, model, version = params[:6]
            is_active = False if "FALSE" in q else True
            perm = params[6] if len(params) > 6 else ("granted" if is_active else "denied")

            self.mock_store[token] = {
                "id": len(self.mock_store) + 1,
                "user_id": uid,
                "household_id": hhid,
                "token": token,
                "platform": platform,
                "device_model": model,
                "app_version": version,
                "is_active": is_active,
                "permission_status": perm
            }
            return []

        if "UPDATE push_subscriptions SET is_active = FALSE, permission_status = 'denied'" in q:
            uid, platform = params[0], params[1]
            for row in self.mock_store.values():
                if row.get("user_id") == uid and row.get("platform") == platform and row.get("is_active"):
                    row["is_active"] = False
                    row["permission_status"] = "denied"
            return []

        if "UPDATE push_subscriptions SET is_active = FALSE, permission_status = 'revoked'" in q or "UPDATE push_subscriptions SET is_active = FALSE, updated_at = NOW() WHERE token = %s" in q:
            token = params[0]
            if token in self.mock_store:
                self.mock_store[token]["is_active"] = False
                self.mock_store[token]["permission_status"] = "revoked"
            return []

        if "WHERE token = ANY" in q:
            tokens = params[0] if isinstance(params[0], (list, tuple, set)) else [params[0]]
            for tok in tokens:
                if tok in self.mock_store:
                    self.mock_store[tok]["is_active"] = False
                    self.mock_store[tok]["permission_status"] = "revoked"
            return []

        if "SELECT token, platform, device_model, app_version FROM push_subscriptions WHERE user_id = %s AND is_active = TRUE" in q:
            uid = params[0]
            return [dict(row) for row in self.mock_store.values() if row.get("user_id") == uid and row.get("is_active")]

        if "WHERE household_id = %s AND user_id != %s AND is_active = TRUE" in q:
            hhid, uid = params[0], params[1]
            return [dict(row) for row in self.mock_store.values() if row.get("household_id") == hhid and row.get("user_id") != uid and row.get("is_active")]

        if "WHERE household_id = %s AND is_active = TRUE" in q:
            hhid = params[0]
            return [dict(row) for row in self.mock_store.values() if row.get("household_id") == hhid and row.get("is_active")]

        return []

    def _mock_one(self, query, params=None):
        q = " ".join(query.strip().split())
        params = params or ()

        if "WHERE user_id = %s AND platform = %s AND is_active = TRUE" in q:
            uid, platform = params[0], params[1]
            for row in self.mock_store.values():
                if row.get("user_id") == uid and row.get("platform") == platform and row.get("is_active"):
                    if "token NOT LIKE" in q and (row["token"].startswith("status:") or row["token"].startswith("denied:")):
                        continue
                    return dict(row)
            return None

        if "SELECT token, platform, is_active, permission_status, app_version FROM push_subscriptions" in q:
            uid, platform = params[0], params[1] if len(params) > 1 else (params[0], "ios")
            for row in self.mock_store.values():
                if row.get("user_id") == uid and row.get("platform") == platform:
                    return dict(row)
            return None

        if "token LIKE 'status:%'" in q:
            uid = params[0]
            for row in self.mock_store.values():
                if row.get("user_id") == uid and row["token"].startswith("status:"):
                    return dict(row)
            return None

        if "WHERE token = %s" in q:
            token = params[0]
            return dict(self.mock_store[token]) if token in self.mock_store else None

        return None

    def test_register_and_unregister_token(self):
        token = "test_device_token_abc_123"
        # Register token
        ok = authmod.register_push_token(
            user_id=1,
            household_id=1,
            token=token,
            platform="android",
            device_model="Pixel 8",
            app_version="1.0.1"
        )
        self.assertTrue(ok)

        # Verify active in user query
        tokens = authmod.get_active_tokens_for_user(1)
        token_strings = [t["token"] for t in tokens]
        self.assertIn(token, token_strings)

        # Verify active in household query
        hh_tokens = authmod.get_active_tokens_for_household(1)
        hh_token_strings = [t["token"] for t in hh_tokens]
        self.assertIn(token, hh_token_strings)

        # Verify exclusion works (e.g. sender exclusion)
        hh_tokens_ex = authmod.get_active_tokens_for_household(1, exclude_user_id=1)
        self.assertEqual(len(hh_tokens_ex), 0)

        # Unregister token
        un_ok = authmod.unregister_push_token(token)
        self.assertTrue(un_ok)

        # Verify no longer returned
        tokens_after = authmod.get_active_tokens_for_user(1)
        token_strings_after = [t["token"] for t in tokens_after]
        self.assertNotIn(token, token_strings_after)

    def test_zero_vs_none_defense(self):
        # 0 user_id or 0 household_id should be rejected safely
        self.assertFalse(authmod.register_push_token(user_id=0, household_id=1, token="tok_1"))
        self.assertFalse(authmod.register_push_token(user_id=1, household_id=0, token="tok_2"))
        self.assertEqual(authmod.get_active_tokens_for_user(0), [])
        self.assertEqual(authmod.get_active_tokens_for_household(0), [])

    def test_mock_push_dispatch(self):
        # Register a token first
        authmod.register_push_token(user_id=1, household_id=1, token="test_token_dispatch")
        res = push_helper.send_push_to_user(1, "Test Alert", "Partner checked off milk", {"url": "/settings"})
        self.assertIn("sent", res)
        self.assertEqual(res.get("failed"), 0)

    def test_mark_tokens_inactive(self):
        token1 = "test_dead_token_1"
        token2 = "test_dead_token_2"
        authmod.register_push_token(user_id=1, household_id=1, token=token1)
        authmod.register_push_token(user_id=1, household_id=1, token=token2)

        authmod.mark_tokens_inactive([token1, token2])
        tokens = authmod.get_active_tokens_for_user(1)
        token_strings = [t["token"] for t in tokens]
        self.assertNotIn(token1, token_strings)
        self.assertNotIn(token2, token_strings)

    def test_record_push_permission_status_lifecycle(self):
        # 1. User denies permission upon app upgrade to 1.0.1
        ok = authmod.record_push_permission_status(
            user_id=1,
            household_id=1,
            permission_status="denied",
            platform="ios",
            device_model="iPhone 15",
            app_version="1.0.1"
        )
        self.assertTrue(ok)

        # 2. Check push_subscriptions has the denied entry with is_active = FALSE
        row = authmod._one("SELECT token, platform, is_active, permission_status, app_version FROM push_subscriptions WHERE user_id = %s AND platform = %s", (1, "ios"))
        self.assertIsNotNone(row)
        self.assertFalse(row["is_active"])
        self.assertEqual(row["permission_status"], "denied")
        self.assertEqual(row["app_version"], "1.0.1")
        self.assertTrue(row["token"].startswith("status:1:ios"))

        # 3. get_active_tokens_for_user must NOT return the denied placeholder
        active_tokens = authmod.get_active_tokens_for_user(1)
        for t in active_tokens:
            self.assertFalse(t["token"].startswith("status:"))

        # 4. Later, user enables notifications in settings -> registers real token
        real_token = "live_fcm_or_apns_token_777"
        reg_ok = authmod.register_push_token(
            user_id=1,
            household_id=1,
            token=real_token,
            platform="ios",
            device_model="iPhone 15",
            app_version="1.0.1",
            permission_status="granted"
        )
        self.assertTrue(reg_ok)

        # 5. Placeholder must be replaced/cleaned up, real token active
        status_row = authmod._one("SELECT id FROM push_subscriptions WHERE user_id = %s AND token LIKE 'status:%'", (1,))
        self.assertIsNone(status_row)

        real_row = authmod._one("SELECT is_active, permission_status FROM push_subscriptions WHERE token = %s", (real_token,))
        self.assertIsNotNone(real_row)
        self.assertTrue(real_row["is_active"])
        self.assertEqual(real_row["permission_status"], "granted")


if __name__ == "__main__":
    unittest.main()
