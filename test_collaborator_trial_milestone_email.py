#!/usr/bin/env python3
"""
test_collaborator_trial_milestone_email.py

Unit tests for scripts/send_collaborator_trial_milestone_email.py.
Verifies content generation, HTML structure, branding colors, milestone metrics,
and test-email dispatch routing.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Add repository root to path
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.send_collaborator_trial_milestone_email import (
    generate_email_content,
    send_email,
    CAMPAIGN_NAME,
    TARGET_EMAIL,
    TARGET_USER_NAME,
    TARGET_HOUSEHOLD_NAME,
)


class TestCollaboratorTrialMilestoneEmail(unittest.TestCase):
    def test_generate_email_content_structure(self):
        """Verify subject, plain text, and HTML body contain required milestone data and branding."""
        subject, plain_text, html_body = generate_email_content()

        # Subject verification
        self.assertIn("Your month with ListMate", subject)

        # Plain text milestone verifications
        self.assertIn("Balasubramaniam", plain_text)
        self.assertIn("lakshmi's List", plain_text)
        self.assertIn("September 22, 2026", plain_text)
        self.assertIn("16 items planned and organized", plain_text)
        self.assertIn("1 store trip completed", plain_text)
        self.assertIn("Still Good", plain_text)
        self.assertIn("Nourish", plain_text)
        self.assertIn("$9.99/year", plain_text)
        self.assertIn("%3Fmodal%3Dupgrade", plain_text)

        # HTML body styling and content verification
        self.assertIn("<!DOCTYPE html>", html_body)
        self.assertIn("background:linear-gradient(135deg, #047857 0%, #10b981 100%)", html_body)
        self.assertIn("1-MONTH MILESTONE • PRO TRIAL UPDATE", html_body)
        self.assertIn("Member Since September 22, 2026", html_body)
        self.assertIn("16 Items Planned &amp; Organized", html_body)
        self.assertIn("1 Shopping Trip Completed", html_body)
        self.assertIn("Still Good", html_body)
        self.assertIn("Nourish", html_body)
        self.assertIn("Keep Household Pro Active", html_body)
        self.assertIn("Unsubscribe", html_body)

    @patch("scripts.send_collaborator_trial_milestone_email._send_via_api")
    def test_send_email_test_mode(self, mock_send):
        """Verify test email sends with [TEST] prefix and does not touch production email_events."""
        mock_send.return_value = True

        success = send_email(
            api_key="SG.fake_test_key",
            dry_run=False,
            force=False,
            test_email="venragh@gmail.com",
        )
        self.assertTrue(success)
        self.assertTrue(mock_send.called)

        call_args = mock_send.call_args[0]
        api_key_arg = call_args[0]
        payload_arg = call_args[1]

        self.assertEqual(api_key_arg, "SG.fake_test_key")
        self.assertEqual(payload_arg["personalizations"][0]["to"][0]["email"], "venragh@gmail.com")
        self.assertTrue(payload_arg["subject"].startswith("[TEST] "))
        self.assertEqual(payload_arg["personalizations"][0]["custom_args"]["is_test"], "True")


if __name__ == "__main__":
    unittest.main()
