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

def send_subscription_notice(to_email: str, user_name: str, is_trial: bool, days_left: int) -> bool:
    """Send subscription ending notice. Returns True on success."""
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        print("WARNING: SENDGRID_API_KEY not set — skipping email")
        return False
        
    term = "trial" if is_trial else "subscription"
    
    if days_left == 0:
        subject = f"Your ListMate {term} ends today"
        urgency_text = "expires today"
    else:
        subject = f"Your ListMate {term} ends in {days_left} days"
        urgency_text = f"expires in {days_left} days"
        
    upgrade_link = "https://listmate.app/upgrade?source=email_reminder"
    
    payload = {
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "personalizations": [{"to": [{"email": to_email}]}],
        "subject": subject,
        "content": [
            {
                "type": "text/plain",
                "value": f"Hi {user_name},\n\nYour ListMate {term} {urgency_text}.\n\nDon't lose access to your shared grocery lists! Tap the link below to upgrade your household and keep everything syncing seamlessly.\n\n{upgrade_link}\n\n— The Listmate Team",
            },
            {
                "type": "text/html",
                "value": f'<div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:20px"><h2 style="color:#2c5a2c">⏳ Action Required</h2><p style="font-size:16px">Hi {user_name},</p><p>Your ListMate <strong>{term}</strong> {urgency_text}.</p><p>Don\'t lose access to your shared grocery lists! Tap the button below to upgrade your household and keep everything syncing seamlessly.</p><p style="margin:24px 0"><a href="{upgrade_link}" style="background:#5ebe7e;color:#fff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:bold">Upgrade Now</a></p></div>',
            },
        ],
        "tracking_settings": {
            "click_tracking": {"enable": False},
            "open_tracking": {"enable": False},
        },
    }
    return _send_via_api(api_key, payload)

def send_activation_notice(to_email: str, user_name: str) -> bool:
    """Send Day 3 onboarding/activation notice to inactive users."""
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        print("WARNING: SENDGRID_API_KEY not set — skipping email")
        return False
        
    app_link = "https://listmate.app/?source=email_activation"
    
    payload = {
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "personalizations": [{"to": [{"email": to_email}]}],
        "subject": "Getting started with ListMate",
        "content": [
            {
                "type": "text/plain",
                "value": f"Hi {user_name},\n\nWe noticed you haven't added any items to ListMate yet!\n\nDid you know you can share your grocery list with your partner or roommates? It syncs instantly so whoever goes to the store always has the latest updates.\n\nTap the link below to add your first items and invite your household:\n\n{app_link}\n\n— The Listmate Team",
            },
            {
                "type": "text/html",
                "value": f'<div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:20px"><h2 style="color:#2c5a2c">👋 Getting started with ListMate</h2><p style="font-size:16px">Hi {user_name},</p><p>We noticed you haven\'t added any items to ListMate yet!</p><p>Did you know you can share your grocery list with your partner or roommates? It syncs instantly so whoever goes to the store always has the latest updates.</p><p style="margin:24px 0"><a href="{app_link}" style="background:#5ebe7e;color:#fff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:bold">Open ListMate</a></p></div>',
            },
        ],
        "tracking_settings": {
            "click_tracking": {"enable": False},
            "open_tracking": {"enable": False},
        },
    }
    return _send_via_api(api_key, payload)

def send_reengagement_notice(to_email: str, user_name: str) -> bool:
    """Send Day 14 re-engagement notice to dormant users."""
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        print("WARNING: SENDGRID_API_KEY not set — skipping email")
        return False
        
    app_link = "https://listmate.app/?source=email_reengagement"
    
    payload = {
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "personalizations": [{"to": [{"email": to_email}]}],
        "subject": "It's been a while! What's new in ListMate",
        "content": [
            {
                "type": "text/plain",
                "value": f"Hi {user_name},\n\nIt's been a couple weeks since you last used ListMate. We wanted to remind you that your shared lists are waiting for you!\n\nCheck out the latest features, including fast store-based category organization, which makes your grocery trips much smoother.\n\nTap the link below to plan your next grocery trip:\n\n{app_link}\n\n— The Listmate Team",
            },
            {
                "type": "text/html",
                "value": f'<div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:20px"><h2 style="color:#2c5a2c">🛒 It\'s been a while!</h2><p style="font-size:16px">Hi {user_name},</p><p>It\'s been a couple weeks since you last used ListMate. We wanted to remind you that your shared lists are waiting for you!</p><p>Check out the latest features, including fast store-based category organization, which makes your grocery trips much smoother.</p><p style="margin:24px 0"><a href="{app_link}" style="background:#5ebe7e;color:#fff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:bold">Plan Your Next Trip</a></p></div>',
            },
        ],
        "tracking_settings": {
            "click_tracking": {"enable": False},
            "open_tracking": {"enable": False},
        },
    }
    return _send_via_api(api_key, payload)

def send_combined_notice(to_email: str, user_name: str, events: dict) -> bool:
    """Send a combined notice when multiple daily events occur for the same user."""
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        print("WARNING: SENDGRID_API_KEY not set — skipping email")
        return False
        
    app_link = "https://listmate.app/?source=email_combined"
    upgrade_link = "https://listmate.app/upgrade?source=email_reminder"
    
    # Build dynamic subject and content based on events
    html_sections = []
    text_sections = []
    
    # Expiration is highest priority
    if 'expiration' in events:
        days = events['expiration']['days_left']
        is_trial = events['expiration']['is_trial']
        term = "trial" if is_trial else "subscription"
        subject = f"Action Required: Your ListMate {term} ends in {days} days" if days > 0 else f"Action Required: Your ListMate {term} ends today"
        urgency = "expires today" if days == 0 else f"expires in {days} days"
        
        text_sections.append(f"Your ListMate {term} {urgency}. Upgrade to keep syncing your shared grocery lists:\n{upgrade_link}")
        html_sections.append(f'<h3 style="color:#d32f2f">⏳ {term.capitalize()} {urgency}</h3><p>Upgrade to keep syncing your shared grocery lists seamlessly.</p><p><a href="{upgrade_link}" style="background:#5ebe7e;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;font-weight:bold">Upgrade Now</a></p>')
    else:
        subject = "Updates from ListMate"

    if 'activation' in events:
        text_sections.append(f"You haven't added any items to ListMate yet! Tap here to get started:\n{app_link}")
        html_sections.append(f'<h3 style="color:#2c5a2c">👋 Getting Started</h3><p>We noticed you haven\'t added any items yet. Share your grocery list with your household so whoever goes to the store has the latest updates.</p>')
        
    if 'reengagement' in events:
        text_sections.append(f"It's been a while! We wanted to remind you that your shared lists are waiting for you.\n{app_link}")
        html_sections.append(f'<h3 style="color:#2c5a2c">🛒 It\'s been a while!</h3><p>We wanted to remind you that your shared lists are waiting for you. Check out the latest features like fast store-based category organization.</p>')

    if not ('expiration' in events):
        html_sections.append(f'<p style="margin:24px 0"><a href="{app_link}" style="background:#5ebe7e;color:#fff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:bold">Open ListMate</a></p>')

    text_body = f"Hi {user_name},\n\n" + "\n\n---\n\n".join(text_sections) + "\n\n— The Listmate Team"
    html_body = f'<div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:20px"><p style="font-size:16px">Hi {user_name},</p>' + "".join(html_sections) + "</div>"
    
    payload = {
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "personalizations": [{"to": [{"email": to_email}]}],
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": text_body},
            {"type": "text/html", "value": html_body},
        ],
        "tracking_settings": {
            "click_tracking": {"enable": False},
            "open_tracking": {"enable": False},
        },
    }
    return _send_via_api(api_key, payload)
