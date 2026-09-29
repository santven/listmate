import os
import unittest
from unittest.mock import patch, MagicMock

import shared.auth as authmod
import push_helper


class TestPushNotifications(unittest.TestCase):
    def setUp(self):
        authmod._init_schema()

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
        # Test mock dispatch when no firebase credentials are set
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


if __name__ == "__main__":
    unittest.main()
