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

if __name__ == '__main__':
    unittest.main()
