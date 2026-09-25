import unittest
from unittest.mock import patch, MagicMock
import datetime
import urllib.parse

# Mock psycopg2 before importing shared.auth and db_pg
import sys
mock_psycopg2 = MagicMock()
sys.modules['psycopg2'] = mock_psycopg2
sys.modules['psycopg2.extras'] = MagicMock()
sys.modules['psycopg2.pool'] = MagicMock()

from shared.auth import claim_trial_extension
from email_helper import send_subscription_notice, send_combined_notice, BASE_URL

class TestTrialExtensionsComprehensive(unittest.TestCase):
    @patch('shared.auth._one')
    @patch('shared.auth._run')
    def test_claim_trial_extension_15d(self, mock_run, mock_one):
        # Household has not claimed 15d yet
        mock_one.return_value = {
            'id': 101,
            'subscription_status': 'trial',
            'trial_ext_15d_claimed_at': None,
            'trial_ext_7d_claimed_at': None,
            'trial_extension_claimed_at': None
        }
        mock_run.return_value = 1
        
        ok, msg, days = claim_trial_extension(household_id=101, user_id=202, tier='15d')
        self.assertTrue(ok)
        self.assertEqual(days, 15)
        self.assertIn("15 extra days", msg)
        self.assertTrue(mock_run.called)

    @patch('shared.auth._one')
    @patch('shared.auth._run')
    def test_claim_trial_extension_7d_after_15d(self, mock_run, mock_one):
        # Household already claimed 15d, now claiming 7d
        mock_one.return_value = {
            'id': 101,
            'subscription_status': 'expired',
            'trial_ext_15d_claimed_at': datetime.datetime.now(datetime.timezone.utc),
            'trial_ext_7d_claimed_at': None,
            'trial_extension_claimed_at': datetime.datetime.now(datetime.timezone.utc)
        }
        mock_run.return_value = 1
        
        ok, msg, days = claim_trial_extension(household_id=101, user_id=202, tier='7d')
        self.assertTrue(ok)
        self.assertEqual(days, 7)
        self.assertIn("7 extra days", msg)

    @patch('shared.auth._one')
    @patch('shared.auth._run')
    def test_claim_trial_extension_legacy_30d_capped_to_7d(self, mock_run, mock_one):
        # Legacy household with 30-day trial span created in the past
        now = datetime.datetime.now(datetime.timezone.utc)
        mock_one.return_value = {
            'id': 105,
            'subscription_status': 'trial',
            'created_at': now - datetime.timedelta(days=30),
            'trial_ends_at': now,
            'trial_ext_15d_claimed_at': None,
            'trial_ext_7d_claimed_at': None,
            'trial_extension_claimed_at': None
        }
        mock_run.return_value = 1
        
        # Even if tier='15d' or not specified, legacy 30d users receive 7 days to cap at 37d total
        ok, msg, days = claim_trial_extension(household_id=105, user_id=202, tier='15d')
        self.assertTrue(ok)
        self.assertEqual(days, 7)
        self.assertIn("7 extra days", msg)
        self.assertTrue(mock_run.called)
        
        # Verify SQL update marks both 15d and 7d slots as satisfied
        update_sql = mock_run.call_args[0][0]
        self.assertIn("trial_ext_7d_claimed_at = NOW()", update_sql)
        self.assertIn("trial_ext_15d_claimed_at = COALESCE(trial_ext_15d_claimed_at, NOW())", update_sql)

    @patch('shared.auth._one')
    def test_claim_trial_extension_legacy_30d_already_claimed_7d(self, mock_one):
        now = datetime.datetime.now(datetime.timezone.utc)
        mock_one.return_value = {
            'id': 105,
            'subscription_status': 'expired',
            'created_at': now - datetime.timedelta(days=37),
            'trial_ends_at': now,
            'trial_ext_15d_claimed_at': now - datetime.timedelta(days=7),
            'trial_ext_7d_claimed_at': now - datetime.timedelta(days=7),
            'trial_extension_claimed_at': now - datetime.timedelta(days=7)
        }
        ok, msg, days = claim_trial_extension(household_id=105, user_id=202, tier='7d')
        self.assertFalse(ok)
        self.assertEqual(days, 0)
        self.assertIn("already claimed", msg)

    @patch('shared.auth._one')
    def test_claim_trial_extension_already_claimed(self, mock_one):
        # Household has already claimed both
        mock_one.return_value = {
            'id': 101,
            'subscription_status': 'expired',
            'trial_ext_15d_claimed_at': datetime.datetime.now(datetime.timezone.utc),
            'trial_ext_7d_claimed_at': datetime.datetime.now(datetime.timezone.utc),
            'trial_extension_claimed_at': datetime.datetime.now(datetime.timezone.utc)
        }
        
        ok, msg, days = claim_trial_extension(household_id=101, user_id=202, tier='15d')
        self.assertFalse(ok)
        self.assertEqual(days, 0)
        self.assertIn("already claimed", msg)

    def test_falsiness_rule_ids(self):
        # Passing 0 as user_id or household_id should be treated as None, not crash
        with patch('shared.auth._one') as mock_one:
            mock_one.return_value = None
            ok, msg, days = claim_trial_extension(household_id=0, user_id=0)
            self.assertFalse(ok)
            self.assertIn("No household found", msg)

    @patch('email_helper._send_via_api')
    def test_send_subscription_notice_extension_links(self, mock_send):
        mock_send.return_value = True
        with patch.dict('os.environ', {'SENDGRID_API_KEY': 'test_key'}):
            # 1. Day 0 trial with extension available
            ok = send_subscription_notice(
                to_email="test@example.com",
                user_name="Alex",
                is_trial=True,
                days_left=0,
                user_id=10,
                household_id=20,
                can_extend=True,
                extension_tier="15d"
            )
            self.assertTrue(ok)
            self.assertTrue(mock_send.called)
            
            payload = mock_send.call_args[0][1]
            content_html = payload['content'][1]['value']
            content_plain = payload['content'][0]['value']
            
            # Check deep links and parameters
            expected_ext_param = "action=claim-extension&tier=15d"
            self.assertIn(urllib.parse.quote(expected_ext_param), content_html)
            self.assertIn(urllib.parse.quote(expected_ext_param), content_plain)
            self.assertIn("Claim 15 Extra Days Free", content_html)
            self.assertIn("15-day free extension", content_plain.lower())

    @patch('email_helper._send_via_api')
    def test_send_combined_notice_consolidation(self, mock_send):
        mock_send.return_value = True
        with patch.dict('os.environ', {'SENDGRID_API_KEY': 'test_key'}):
            events = {
                'expiration': {
                    'is_trial': True,
                    'days_left': 0,
                    'can_extend': True,
                    'extension_tier': '15d'
                },
                'solo_nudge': True
            }
            ok = send_combined_notice(
                to_email="alex@example.com",
                user_name="Alex",
                events=events,
                user_id=10,
                household_id=20
            )
            self.assertTrue(ok)
            payload = mock_send.call_args[0][1]
            content_html = payload['content'][1]['value']
            
            # Verify single email contains both extension offer and household invite
            self.assertIn("Extend Free Trial for 15 Days", content_html)
            self.assertIn("Invite Your Household", content_html)

    @patch('shared.auth._one')
    @patch('shared.auth._run')
    def test_claim_trial_extension_honors_15d_when_promised_in_email(self, mock_run, mock_one):
        # Legacy 30d household that was promised 15d in a winback email dispatch
        now = datetime.datetime.now(datetime.timezone.utc)
        def side_effect_one(sql, params=None):
            if "FROM auth_households" in sql or "FROM {_HH}" in sql:
                return {
                    'id': 37,
                    'subscription_status': 'expired',
                    'created_at': now - datetime.timedelta(days=35),
                    'trial_ends_at': now - datetime.timedelta(days=5),
                    'trial_ext_15d_claimed_at': None,
                    'trial_ext_7d_claimed_at': None,
                    'trial_extension_claimed_at': None
                }
            elif "FROM email_events" in sql:
                return {'campaign': 'trial_winback_ext_15d'}
            return None

        mock_one.side_effect = side_effect_one
        mock_run.return_value = 1

        ok, msg, days = claim_trial_extension(household_id=37, user_id=1, tier='15d')
        self.assertTrue(ok)
        self.assertEqual(days, 15)
        self.assertIn("15 extra days", msg)
        self.assertTrue(mock_run.called)

        update_sql = mock_run.call_args[0][0]
        self.assertIn("trial_ext_15d_claimed_at = NOW()", update_sql)

    @patch('scripts.send_expired_trial_winback.send_winback_email')
    @patch('scripts.send_expired_trial_winback.db_pg.execute_query')
    def test_send_expired_trial_winback_legacy_30d_tier(self, mock_query, mock_send):
        from scripts.send_expired_trial_winback import run_winback
        now = datetime.datetime.now(datetime.timezone.utc)
        
        # Row 1: Legacy 30d trial user (30-day trial span in past) -> should get 7d
        # Row 2: Standard 15d trial user (15-day trial span in past) -> should get 15d
        mock_query.return_value = [
            {
                'household_id': 37,
                'household_name': 'Legacy Household',
                'user_id': 1,
                'email': 'legacy@example.com',
                'user_name': 'Legacy User',
                'subscription_status': 'expired',
                'created_at': now - datetime.timedelta(days=35),
                'trial_ends_at': now - datetime.timedelta(days=5),
                'trial_ext_15d_claimed_at': None,
                'trial_ext_7d_claimed_at': None,
                'trial_extension_claimed_at': None
            },
            {
                'household_id': 50,
                'household_name': 'Standard Household',
                'user_id': 2,
                'email': 'standard@example.com',
                'user_name': 'Standard User',
                'subscription_status': 'expired',
                'created_at': now - datetime.timedelta(days=16),
                'trial_ends_at': now - datetime.timedelta(days=1),
                'trial_ext_15d_claimed_at': None,
                'trial_ext_7d_claimed_at': None,
                'trial_extension_claimed_at': None
            }
        ]
        mock_send.return_value = True

        run_winback(dry_run=False)

        self.assertEqual(mock_send.call_count, 2)
        # Check call 1 (legacy 30d) -> 7d
        call1_kwargs = mock_send.call_args_list[0].kwargs
        self.assertEqual(call1_kwargs['household_id'], 37)
        self.assertEqual(call1_kwargs['extension_tier'], '7d')

        # Check call 2 (standard 15d) -> 15d
        call2_kwargs = mock_send.call_args_list[1].kwargs
        self.assertEqual(call2_kwargs['household_id'], 50)
        self.assertEqual(call2_kwargs['extension_tier'], '15d')

    @patch('scripts.send_expired_trial_winback.send_winback_email')
    @patch('scripts.send_expired_trial_winback.db_pg.execute_query')
    def test_send_expired_trial_winback_targeted_household_id(self, mock_query, mock_send):
        from scripts.send_expired_trial_winback import run_winback
        now = datetime.datetime.now(datetime.timezone.utc)

        mock_query.return_value = [
            {
                'household_id': 37,
                'household_name': 'Legacy Household',
                'user_id': 1,
                'email': 'legacy@example.com',
                'user_name': 'Legacy User',
                'subscription_status': 'expired',
                'created_at': now - datetime.timedelta(days=35),
                'trial_ends_at': now - datetime.timedelta(days=5),
                'trial_ext_15d_claimed_at': None,
                'trial_ext_7d_claimed_at': None,
                'trial_extension_claimed_at': None
            }
        ]
        mock_send.return_value = True

        run_winback(dry_run=False, household_id=37)

        self.assertEqual(mock_query.call_count, 1)
        query_sql, query_params = mock_query.call_args[0]
        self.assertIn("AND h.id = %s", query_sql)
        self.assertEqual(query_params, [37])
        # Verify query SQL does not have literal % characters that would break psycopg2 execution with params
        import re
        cleaned_sql = query_sql.replace('%%', '')
        all_placeholders = re.findall(r'%s', cleaned_sql)
        invalid_percents = re.findall(r'%[^s]', cleaned_sql)
        self.assertEqual(len(all_placeholders), len(query_params))
        self.assertEqual(len(invalid_percents), 0, f"Found raw unescaped % that breaks psycopg2: {invalid_percents}")
        self.assertEqual(mock_send.call_count, 1)
        self.assertEqual(mock_send.call_args.kwargs['household_id'], 37)
        self.assertEqual(mock_send.call_args.kwargs['extension_tier'], '7d')

if __name__ == '__main__':
    unittest.main()
