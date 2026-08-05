#!/usr/bin/env python3
"""SendGrid email helper — shared by grocery and ListMate apps."""
import os

FROM_EMAIL = os.environ.get("SENDGRID_FROM", "hello@grocerlist.app")
FROM_NAME = os.environ.get("SENDGRID_FROM_NAME", "ListMate")


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
        "subject": f"{inviter_name} invited you to join {household_name} on ListMate",
        "content": [
            {
                "type": "text/plain",
                "value": f"Hi!\n\n{inviter_name} invited you to join \"{household_name}\" on ListMate — a shared grocery list app for your household.\n\nTo accept this invitation, click the link below and sign in with your Google account:\n\n{invite_link}\n\nThis link expires in 7 days.\n\n— The ListMate Team",
            },
            {
                "type": "text/html",
                "value": f'<div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:20px"><h2 style="color:#2c5a2c">🛒 You\'re invited!</h2><p style="font-size:16px">{inviter_name} invited you to join <strong>{household_name}</strong> on ListMate.</p><p>ListMate helps your household keep shared grocery lists, organized by store.</p><p style="margin:24px 0"><a href="{invite_link}" style="background:#5ebe7e;color:#fff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:bold">Accept Invitation</a></p><p style="font-size:12px;color:#888">This link expires in 7 days.</p></div>',
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
                "value": f"Hi {user_name},\n\nYour ListMate {term} {urgency_text}.\n\nDon't lose access to your shared grocery lists! Tap the link below to upgrade your household and keep everything syncing seamlessly.\n\n{upgrade_link}\n\n— The ListMate Team",
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
        "subject": "Simplify your grocery runs with ListMate",
        "content": [
            {
                "type": "text/plain",
                "value": (
                    f"Hi {user_name},\n\n"
                    f"We noticed you haven't added any items to ListMate yet!\n\n"
                    f"Did you know that sharing a real-time grocery list with your partner or housemates makes shopping effortless and can save your household hundreds of dollars a year in forgotten items, duplicate purchases, and impulse buys?\n\n"
                    f"When everyone adds items as they run out, whoever visits the store always has the exact, up-to-date list in their pocket.\n\n"
                    f"Tap the link below to add your first items and invite your household:\n\n"
                    f"{app_link}\n\n"
                    f"— The ListMate Team"
                ),
            },
            {
                "type": "text/html",
                "value": (
                    f'<div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:20px">'
                    f'<h2 style="color:#2c5a2c">👋 Getting started with ListMate</h2>'
                    f'<p style="font-size:16px">Hi {user_name},</p>'
                    f'<p>We noticed you haven\'t added any items to ListMate yet!</p>'
                    f'<p>Did you know that sharing a real-time grocery list with your partner or housemates makes shopping effortless and can <strong>save your household hundreds of dollars a year</strong> in forgotten items, duplicate purchases, and impulse buys?</p>'
                    f'<p>When everyone adds items as they run out, whoever visits the store always has the exact, up-to-date list in their pocket.</p>'
                    f'<p style="margin:24px 0"><a href="{app_link}" style="background:#5ebe7e;color:#fff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:bold">Open ListMate & Add First Item</a></p>'
                    f'</div>'
                ),
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
        "subject": "It's been a while! Streamline your next grocery trip",
        "content": [
            {
                "type": "text/plain",
                "value": (
                    f"Hi {user_name},\n\n"
                    f"It's been a couple of weeks since your last update on ListMate. We wanted to remind you that your shared grocery lists are waiting for you!\n\n"
                    f"Sharing a live, store-organized grocery list with your household is one of the easiest ways to smooth out shopping trips and cut down on impulse buys—saving you both time and money.\n\n"
                    f"Check out our latest features, including instant store-based aisle organization, to make your next trip seamless.\n\n"
                    f"Tap the link below to plan your next grocery trip:\n\n"
                    f"{app_link}\n\n"
                    f"— The ListMate Team"
                ),
            },
            {
                "type": "text/html",
                "value": (
                    f'<div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:20px">'
                    f'<h2 style="color:#2c5a2c">🛒 It\'s been a while!</h2>'
                    f'<p style="font-size:16px">Hi {user_name},</p>'
                    f'<p>It\'s been a couple of weeks since your last update on ListMate. We wanted to remind you that your shared grocery lists are waiting for you!</p>'
                    f'<p>Sharing a live, store-organized grocery list with your household is one of the easiest ways to smooth out shopping trips and cut down on impulse buys—<strong>saving you both time and money</strong>.</p>'
                    f'<p>Check out our latest features, including instant store-based aisle organization, to make your next trip seamless.</p>'
                    f'<p style="margin:24px 0"><a href="{app_link}" style="background:#5ebe7e;color:#fff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:bold">Plan Your Next Trip</a></p>'
                    f'</div>'
                ),
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
        text_sections.append(
            f"You haven't added any items to ListMate yet!\n"
            f"Did you know sharing a real-time grocery list with your household can save hundreds of dollars each year in impulse and duplicate purchases? Tap here to get started:\n{app_link}"
        )
        html_sections.append(
            f'<h3 style="color:#2c5a2c">👋 Getting Started</h3>'
            f'<p>We noticed you haven\'t added any items yet. Sharing a live list with your partner or housemates makes store trips smoother and prevents impulse buys, saving your household both time and money.</p>'
        )

    if 'reengagement' in events:
        text_sections.append(
            f"It's been a while! We wanted to remind you that your shared lists are waiting for you.\n"
            f"Keep your household synced and cut down on extra store runs and duplicate buys:\n{app_link}"
        )
        html_sections.append(
            f'<h3 style="color:#2c5a2c">🛒 It\'s been a while!</h3>'
            f'<p>We wanted to remind you that your shared lists are waiting for you. Stay synced with your household to avoid duplicate buys and make every grocery run effortless.</p>'
        )

    if not ('expiration' in events):
        html_sections.append(f'<p style="margin:24px 0"><a href="{app_link}" style="background:#5ebe7e;color:#fff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:bold">Open ListMate</a></p>')

    text_body = f"Hi {user_name},\n\n" + "\n\n---\n\n".join(text_sections) + "\n\n— The ListMate Team"
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
