import unittest
from unittest.mock import patch, MagicMock
import datetime

# Mock psycopg2 before importing shared.auth
import sys
mock_psycopg2 = MagicMock()
sys.modules['psycopg2'] = mock_psycopg2
sys.modules['psycopg2.extras'] = MagicMock()
sys.modules['psycopg2.pool'] = MagicMock()

import shared.auth as authmod

class TestTrialExtensions(unittest.TestCase):
    def test_calc_days_left(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        future_5 = now + datetime.timedelta(days=5)
        past_2 = now - datetime.timedelta(days=2)
        
        # Test helper directly inside claim_trial_extension logic
        self.assertGreaterEqual(max(0, (future_5 - now).days), 4)
        self.assertEqual(max(0, (past_2 - now).days), 0)

    @patch('shared.auth._one')
    @patch('shared.auth._run')
    def test_claim_15d_first_time(self, mock_run, mock_one):
        mock_one.side_effect = [
            # First call: fetch household
            {
                'id': 101,
                'name': 'Test House',
                'is_premium': False,
                'subscription_status': 'trial',
                'trial_ends_at': '2026-09-24 12:00:00',
                'trial_extension_claimed_at': None,
                'trial_ext_15d_claimed_at': None,
                'trial_ext_7d_claimed_at': None,
            },
            # Second call: fetch user email
            {'email': 'test@example.com'}
        ]
        
        ok, msg, days = authmod.claim_trial_extension(101, 1, tier='15d')
        self.assertTrue(ok)
        self.assertEqual(days, 15)
        self.assertIn('15 extra days', msg)
        self.assertTrue(mock_run.called)

    @patch('shared.auth._one')
    @patch('shared.auth._run')
    def test_claim_7d_after_15d(self, mock_run, mock_one):
        mock_one.side_effect = [
            {
                'id': 102,
                'name': 'Test House 2',
                'is_premium': False,
                'subscription_status': 'trial',
                'trial_ends_at': '2026-09-24 12:00:00',
                'trial_extension_claimed_at': '2026-09-10 12:00:00',
                'trial_ext_15d_claimed_at': '2026-09-10 12:00:00',
                'trial_ext_7d_claimed_at': None,
            },
            {'email': 'test2@example.com'}
        ]
        
        ok, msg, days = authmod.claim_trial_extension(102, 2, tier='7d')
        self.assertTrue(ok)
        self.assertEqual(days, 7)
        self.assertIn('7 extra days', msg)

    @patch('shared.auth._one')
    @patch('shared.auth._run')
    def test_claim_after_all_used(self, mock_run, mock_one):
        mock_one.return_value = {
            'id': 103,
            'name': 'Test House 3',
            'is_premium': False,
            'subscription_status': 'trial',
            'trial_ends_at': '2026-09-24 12:00:00',
            'trial_extension_claimed_at': '2026-09-10 12:00:00',
            'trial_ext_15d_claimed_at': '2026-09-10 12:00:00',
            'trial_ext_7d_claimed_at': '2026-09-24 12:00:00',
        }
        
        ok, msg, days = authmod.claim_trial_extension(103, 3, tier='15d')
        self.assertFalse(ok)
        self.assertIn('already claimed all complimentary trial extensions', msg)

if __name__ == '__main__':
    unittest.main()
