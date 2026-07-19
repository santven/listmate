#!/usr/bin/env python3
"""SendGrid email helper — shared by grocery and Listmate apps."""
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

FROM_EMAIL = os.environ.get("SENDGRID_FROM", "hello@grocerlist.app")
FROM_NAME = os.environ.get("SENDGRID_FROM_NAME", "Listmate")


def send_invite(to_email: str, invite_link: str, household_name: str, inviter_name: str = "someone") -> bool:
    """Send a household invite email. Returns True on success."""
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        print("WARNING: SENDGRID_API_KEY not set — skipping email")
        return False

    message = Mail(
        from_email=(FROM_EMAIL, FROM_NAME),
        to_emails=to_email,
        subject=f"{inviter_name} invited you to join {household_name} on Listmate",
        plain_text_content=f"""Hi!

{inviter_name} invited you to join "{household_name}" on Listmate — a shared grocery list app for your household.

To accept this invitation, click the link below and sign in with your Google account:

{invite_link}

This link expires in 7 days.

— The Listmate Team""",
        html_content=f"""
<div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:20px">
  <h2 style="color:#2c5a2c">🛒 You're invited!</h2>
  <p style="font-size:16px">{inviter_name} invited you to join <strong>{household_name}</strong> on Listmate.</p>
  <p>Listmate helps your household keep shared grocery lists, organized by store.</p>
  <p style="margin:24px 0">
    <a href="{invite_link}" style="background:#5ebe7e;color:#fff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:bold">
      Accept Invitation
    </a>
  </p>
  <p style="font-size:12px;color:#888">This link expires in 7 days.</p>
</div>""",
    )

    try:
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        return 200 <= response.status_code < 300
    except Exception as e:
        print(f"SendGrid error: {e}")
        return False
