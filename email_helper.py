#!/usr/bin/env python3
"""SendGrid email helper — shared by grocery and Listmate apps."""
import os

FROM_EMAIL = os.environ.get("SENDGRID_FROM", "hello@grocerlist.app")
FROM_NAME = os.environ.get("SENDGRID_FROM_NAME", "Listmate")


def _send_via_api(api_key: str, payload: dict) -> bool:
    """Send via SendGrid REST API directly — avoids helper class quirks."""
    import json
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError

    req = Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(req) as resp:
            return 200 <= resp.status < 300
    except HTTPError as e:
        print(f"SendGrid error: {e.code} {e.read().decode()[:200]}")
        return False


def send_invite(to_email: str, invite_link: str, household_name: str, inviter_name: str = "someone") -> bool:
    """Send a household invite email. Returns True on success."""
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        print("WARNING: SENDGRID_API_KEY not set — skipping email")
        return False

    payload = {
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "personalizations": [{
            "to": [{"email": to_email}],
        }],
        "subject": f"{inviter_name} invited you to join {household_name} on Listmate",
        "content": [
            {
                "type": "text/plain",
                "value": f"Hi!\n\n{inviter_name} invited you to join \"{household_name}\" on Listmate — a shared grocery list app for your household.\n\nTo accept this invitation, click the link below and sign in with your Google account:\n\n{invite_link}\n\nThis link expires in 7 days.\n\n— The Listmate Team",
            },
            {
                "type": "text/html",
                "value": f'<div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:20px"><h2 style="color:#2c5a2c">🛒 You\'re invited!</h2><p style="font-size:16px">{inviter_name} invited you to join <strong>{household_name}</strong> on Listmate.</p><p>Listmate helps your household keep shared grocery lists, organized by store.</p><p style="margin:24px 0"><a href="{invite_link}" style="background:#5ebe7e;color:#fff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:bold">Accept Invitation</a></p><p style="font-size:12px;color:#888">This link expires in 7 days.</p></div>',
            },
        ],
        "tracking_settings": {
            "click_tracking": {"enable": False},
            "open_tracking": {"enable": False},
        },
    }

    return _send_via_api(api_key, payload)
