#!/usr/bin/env python3
"""SendGrid email helper — shared by grocery and ListMate apps."""
import os
from urllib.parse import quote

FROM_EMAIL = os.environ.get("SENDGRID_FROM", "hello@grocerlist.app")
FROM_NAME = os.environ.get("SENDGRID_FROM_NAME", "ListMate")
BASE_URL = os.environ.get("APP_URL", "https://grocerlist.app").rstrip("/")


def _send_via_api(api_key: str, payload: dict) -> bool:
    """Send via SendGrid REST API directly — avoids helper class quirks."""
    import json
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError

    # Ensure sender identity and reply_to are always configured
    if "from" not in payload:
        payload["from"] = {"email": FROM_EMAIL, "name": FROM_NAME}
    if "reply_to" not in payload:
        payload["reply_to"] = {"email": FROM_EMAIL, "name": FROM_NAME}

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


def send_invite(to_email: str, invite_link: str, household_name: str, inviter_name: str = "someone", invite_code: str = "", marketing_opt_in: bool = False, user_id: int = 0, household_id: int = 0) -> bool:
    """Send a household invite email with 8-character invite code, reliable mobile badges, and anti-spam deliverability."""
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        print("WARNING: SENDGRID_API_KEY not set — skipping email")
        return False

    display_code = (invite_code or "").strip()
    if not display_code and "token=" in invite_link:
        import urllib.parse
        parsed = urllib.parse.urlparse(invite_link)
        qs = urllib.parse.parse_qs(parsed.query)
        if "token" in qs and qs["token"]:
            display_code = qs["token"][0]

    campaign = "invite"
    marketing_txt = '\n\nThe household owner has opted in to marketing emails. You will default to the same setting for this household, but you can change it in your settings.' if marketing_opt_in else ''
    marketing_html = '<p style="font-size: 11px; color: #888; margin-top: 20px; text-align: center;">The household owner has opted in to marketing emails. You will default to the same setting for this household, but you can change it in your settings.</p>' if marketing_opt_in else ''

    # Reliable global CDN URLs for store badges
    app_store_img = "https://cdn.jsdelivr.net/gh/santven/listmate@main/static/app_store_badge.png"
    google_play_img = "https://cdn.jsdelivr.net/gh/santven/listmate@main/static/google_play_badge.png"
    ios_link = "https://apps.apple.com/us/app/grocerlistmate/id6795402710"
    android_link = "https://play.google.com/store/apps/details?id=com.pvkslabs.listmate&pcampaignid=web_share"

    clean_inviter = (inviter_name or "").strip()
    has_inviter = clean_inviter and clean_inviter.lower() not in ("someone", "unknown", "a user", "none", "")

    if has_inviter:
        subject = f"{clean_inviter} invited you to join {household_name} on ListMate"
        intro_text = f"{clean_inviter} invited you to join \"{household_name}\" on ListMate — a shared grocery list app for your household."
        intro_html = f"{clean_inviter} invited you to join <strong>{household_name}</strong> on ListMate."
    else:
        subject = f"You were invited to join {household_name} on ListMate"
        intro_text = f"You have been invited to join \"{household_name}\" on ListMate — a shared grocery list app for your household."
        intro_html = f"You have been invited to join <strong>{household_name}</strong> on ListMate."

    if display_code:
        code_section_html = f'''
      <div style="background-color:#f0fdf4;border:2px dashed #86efac;border-radius:10px;padding:16px;text-align:center;margin:20px 0;">
        <div style="font-size:12px;font-weight:700;color:#166534;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;">Your Household Invite Code</div>
        <div style="font-family:Consolas,Monaco,Courier,monospace;font-size:28px;font-weight:800;letter-spacing:4px;color:#15803d;">{display_code}</div>
      </div>
      <div style="font-size:14px;color:#374151;line-height:1.6;margin-bottom:20px;">
        <strong>How to join on mobile:</strong><br>
        1. Download <strong>ListMate</strong> for your device:<br>
        <div style="margin:10px 0 14px 0;">
          <a href="{ios_link}" target="_blank" rel="noopener noreferrer" style="display:inline-block;text-decoration:none;margin-right:8px;vertical-align:middle;">
            <img src="{app_store_img}" alt="Download on the App Store" width="135" height="40" border="0" style="display:inline-block;height:40px;width:auto;border:0;outline:none;vertical-align:middle;border-radius:6px;">
          </a>
          <a href="{android_link}" target="_blank" rel="noopener noreferrer" style="display:inline-block;text-decoration:none;vertical-align:middle;">
            <img src="{google_play_img}" alt="Get it on Google Play" width="135" height="40" border="0" style="display:inline-block;height:40px;width:auto;border:0;outline:none;vertical-align:middle;border-radius:6px;">
          </a>
        </div>
        2. Sign in with your Google or Apple account.<br>
        3. Enter your invite code <span style="font-family:Consolas,Monaco,Courier,monospace;font-weight:700;background-color:#f1f5f9;padding:2px 6px;border-radius:4px;">{display_code}</span> when prompted.
      </div>
      <div style="text-align:center;margin:24px 0;">
        <a href="{invite_link}" target="_blank" rel="noopener noreferrer" style="background-color:#10b981;color:#ffffff;padding:12px 24px;border-radius:8px;text-decoration:none;font-size:15px;font-weight:700;display:inline-block;">Accept in Browser</a>
      </div>
        '''
        plain_text = (
            f"Hi!\n\n"
            f"{intro_text}\n\n"
            f"Your Household Invite Code:\n{display_code}\n\n"
            f"How to join:\n"
            f"1. Download ListMate on your mobile device:\n"
            f"   • iPhone: {ios_link}\n"
            f"   • Android: {android_link}\n"
            f"2. Sign in with your Google or Apple account\n"
            f"3. Under 'Have a Household Invite code?', enter: {display_code}\n\n"
            f"Or accept directly in your browser:\n"
            f"{invite_link}\n\n"
            f"This single-use invite code expires in 7 days.\n\n"
            f"— The ListMate Team\n\n"
            f"--\n"
            f"ListMate • Powered by PVKS Labs\n"
            f"You received this invitation because a ListMate member invited you to their household.\n"
            f"Need help? Contact hello@grocerlist.app" + marketing_txt
        )
    else:
        code_section_html = f'''
      <div style="font-size:14px;color:#374151;line-height:1.6;margin-bottom:20px;">
        <strong>Download ListMate:</strong><br>
        <div style="margin:10px 0 14px 0;">
          <a href="{ios_link}" target="_blank" rel="noopener noreferrer" style="display:inline-block;text-decoration:none;margin-right:8px;vertical-align:middle;">
            <img src="{app_store_img}" alt="Download on the App Store" width="135" height="40" border="0" style="display:inline-block;height:40px;width:auto;border:0;outline:none;vertical-align:middle;border-radius:6px;">
          </a>
          <a href="{android_link}" target="_blank" rel="noopener noreferrer" style="display:inline-block;text-decoration:none;vertical-align:middle;">
            <img src="{google_play_img}" alt="Get it on Google Play" width="135" height="40" border="0" style="display:inline-block;height:40px;width:auto;border:0;outline:none;vertical-align:middle;border-radius:6px;">
          </a>
        </div>
      </div>
      <div style="margin:24px 0;text-align:center;">
        <a href="{invite_link}" target="_blank" rel="noopener noreferrer" style="background-color:#10b981;color:#ffffff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:bold;display:inline-block;">Accept Invitation</a>
      </div>
        '''
        plain_text = (
            f"Hi!\n\n"
            f"{intro_text}\n\n"
            f"Download ListMate:\n"
            f"• iPhone: {ios_link}\n"
            f"• Android: {android_link}\n\n"
            f"To accept this invitation, click the link below and sign in with your Google or Apple account:\n\n"
            f"{invite_link}\n\n"
            f"This single-use invitation link expires in 7 days.\n\n"
            f"— The ListMate Team\n\n"
            f"--\n"
            f"ListMate • Powered by PVKS Labs\n"
            f"You received this invitation because a ListMate member invited you to their household.\n"
            f"Need help? Contact hello@grocerlist.app" + marketing_txt
        )

    html_body = (
        f'<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,Helvetica,Arial,sans-serif;max-width:500px;margin:0 auto;padding:24px;border:1px solid #e2e8f0;border-radius:12px;background-color:#ffffff;color:#334155;">'
        f'<h2 style="font-size:20px;font-weight:700;color:#0f172a;margin-top:0;margin-bottom:12px;line-height:1.3;">You\'re invited to join {household_name}</h2>'
        f'<p style="font-size:15px;color:#334155;line-height:1.5;margin-top:0;margin-bottom:12px;">{intro_html}</p>'
        f'<p style="font-size:14px;color:#64748b;line-height:1.5;margin-top:0;margin-bottom:20px;">ListMate helps your household keep shared grocery lists organized by store, syncing in real time across all members.</p>'
        f'{code_section_html}'
        f'<p style="font-size:12px;color:#94a3b8;line-height:1.5;margin-top:20px;margin-bottom:0;text-align:center;">Sign in with your Google or Apple account to join. This invite code expires in 7 days.</p>'
        f'<div style="font-size:11px;color:#888888;margin-top:24px;padding-top:16px;border-top:1px solid #e2e8f0;text-align:center;line-height:1.6;">'
        f'<p style="margin:3px 0;font-weight:600;color:#64748b;">ListMate • Powered by PVKS Labs</p>'
        f'<p style="margin:3px 0;color:#94a3b8;">You received this invitation because a ListMate member invited you to their household.</p>'
        f'<p style="margin:3px 0;color:#94a3b8;">Need help? Contact <a href="mailto:hello@grocerlist.app" style="color:#64748b;text-decoration:underline;">hello@grocerlist.app</a></p>'
        f'{marketing_html}'
        f'</div>'
        f'</div>'
    )

    payload = {
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "reply_to": {"email": FROM_EMAIL, "name": FROM_NAME},
        "personalizations": [{
            "to": [{"email": to_email}],
            "custom_args": {
                "user_id": str(user_id) if user_id else "",
                "household_id": str(household_id) if household_id else "",
                "campaign": campaign,
            },
        }],
        "categories": [campaign],
        "custom_args": {
            "user_id": str(user_id) if user_id else "",
            "household_id": str(household_id) if household_id else "",
            "campaign": campaign,
        },
        "subject": subject,
        "content": [
            {
                "type": "text/plain",
                "value": plain_text,
            },
            {
                "type": "text/html",
                "value": html_body,
            },
        ],
        "tracking_settings": {
            "click_tracking": {"enable": True, "enable_text": False},
            "open_tracking": {"enable": True},
        },
    }
    return _send_via_api(api_key, payload)


def send_invite_reminder(
    to_email: str,
    invite_link: str,
    household_name: str,
    inviter_name: str = "someone",
    invite_code: str = "",
    days_remaining: int = 5,
    user_id: int = 0,
    household_id: int = 0
) -> bool:
    """Send an automated pending invite reminder (Day 2 gentle nudge or Day 5 final urgency)."""
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        print("WARNING: SENDGRID_API_KEY not set — skipping email")
        return False

    display_code = (invite_code or "").strip()
    if not display_code and "token=" in invite_link:
        import urllib.parse
        parsed = urllib.parse.urlparse(invite_link)
        qs = urllib.parse.parse_qs(parsed.query)
        if "token" in qs and qs["token"]:
            display_code = qs["token"][0]

    is_urgent = (days_remaining <= 2)
    campaign = "invite_reminder_day5" if is_urgent else "invite_reminder_day2"

    app_store_img = "https://cdn.jsdelivr.net/gh/santven/listmate@main/static/app_store_badge.png"
    google_play_img = "https://cdn.jsdelivr.net/gh/santven/listmate@main/static/google_play_badge.png"
    ios_link = "https://apps.apple.com/us/app/grocerlistmate/id6795402710"
    android_link = "https://play.google.com/store/apps/details?id=com.pvkslabs.listmate&pcampaignid=web_share"

    clean_inviter = (inviter_name or "").strip()
    has_inviter = clean_inviter and clean_inviter.lower() not in ("someone", "unknown", "a user", "none", "")

    if is_urgent:
        subject = f"Your invite to join {household_name} on ListMate expires in 48 hours"
        headline = "⏳ Invitation Expiring in 48 Hours"
        intro_p = f"This is a quick reminder that your invitation to join <strong>{household_name}</strong> on ListMate will expire in <strong>2 days</strong>."
        plain_intro = f"This is a quick reminder that your invitation to join \"{household_name}\" on ListMate expires in 2 days."
    else:
        if has_inviter:
            subject = f"Reminder: {clean_inviter} invited you to join {household_name} on ListMate"
            headline = f"🛒 {clean_inviter} is Waiting for You"
            intro_p = f"<strong>{clean_inviter}</strong> invited you to join <strong>{household_name}</strong> on ListMate to share and organize grocery lists together."
            plain_intro = f"{clean_inviter} invited you to join \"{household_name}\" on ListMate to share and organize grocery lists together."
        else:
            subject = f"Reminder: You're invited to join {household_name} on ListMate"
            headline = "🛒 Your Household Invite is Waiting"
            intro_p = f"You're invited to join <strong>{household_name}</strong> on ListMate to share and organize grocery lists together."
            plain_intro = f"You're invited to join \"{household_name}\" on ListMate to share and organize grocery lists together."

    if display_code:
        code_section_html = f'''
      <div style="background-color:#f0fdf4;border:2px dashed #86efac;border-radius:10px;padding:16px;text-align:center;margin:20px 0;">
        <div style="font-size:12px;font-weight:700;color:#166534;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;">Your Household Invite Code</div>
        <div style="font-family:Consolas,Monaco,Courier,monospace;font-size:28px;font-weight:800;letter-spacing:4px;color:#15803d;">{display_code}</div>
      </div>
      <div style="font-size:14px;color:#374151;line-height:1.6;margin-bottom:20px;">
        <strong>How to join on mobile:</strong><br>
        1. Download <strong>ListMate</strong> for your device:<br>
        <div style="margin:10px 0 14px 0;">
          <a href="{ios_link}" target="_blank" rel="noopener noreferrer" style="display:inline-block;text-decoration:none;margin-right:8px;vertical-align:middle;">
            <img src="{app_store_img}" alt="Download on the App Store" width="135" height="40" border="0" style="display:inline-block;height:40px;width:auto;border:0;outline:none;vertical-align:middle;border-radius:6px;">
          </a>
          <a href="{android_link}" target="_blank" rel="noopener noreferrer" style="display:inline-block;text-decoration:none;vertical-align:middle;">
            <img src="{google_play_img}" alt="Get it on Google Play" width="135" height="40" border="0" style="display:inline-block;height:40px;width:auto;border:0;outline:none;vertical-align:middle;border-radius:6px;">
          </a>
        </div>
        2. Sign in with your Google or Apple account.<br>
        3. Enter your invite code <span style="font-family:Consolas,Monaco,Courier,monospace;font-weight:700;background-color:#f1f5f9;padding:2px 6px;border-radius:4px;">{display_code}</span> when prompted.
      </div>
      <div style="text-align:center;margin:24px 0;">
        <a href="{invite_link}" target="_blank" rel="noopener noreferrer" style="background-color:#10b981;color:#ffffff;padding:12px 24px;border-radius:8px;text-decoration:none;font-size:15px;font-weight:700;display:inline-block;">Accept in Browser</a>
      </div>
        '''
        plain_text = (
            f"Hi!\n\n"
            f"{plain_intro}\n\n"
            f"Your Household Invite Code:\n{display_code}\n\n"
            f"How to join:\n"
            f"1. Download ListMate on your mobile device:\n"
            f"   • iPhone: {ios_link}\n"
            f"   • Android: {android_link}\n"
            f"2. Sign in with your Google or Apple account\n"
            f"3. Under 'Have a Household Invite code?', enter: {display_code}\n\n"
            f"Or accept directly in your browser:\n"
            f"{invite_link}\n\n"
            f"This single-use invite code expires in {days_remaining} days.\n\n"
            f"— The ListMate Team\n\n"
            f"--\n"
            f"ListMate • Powered by PVKS Labs\n"
            f"You received this reminder because a ListMate member invited you to their household.\n"
            f"Need help? Contact hello@grocerlist.app"
        )
    else:
        code_section_html = f'''
      <div style="font-size:14px;color:#374151;line-height:1.6;margin-bottom:20px;">
        <strong>Download ListMate:</strong><br>
        <div style="margin:10px 0 14px 0;">
          <a href="{ios_link}" target="_blank" rel="noopener noreferrer" style="display:inline-block;text-decoration:none;margin-right:8px;vertical-align:middle;">
            <img src="{app_store_img}" alt="Download on the App Store" width="135" height="40" border="0" style="display:inline-block;height:40px;width:auto;border:0;outline:none;vertical-align:middle;border-radius:6px;">
          </a>
          <a href="{android_link}" target="_blank" rel="noopener noreferrer" style="display:inline-block;text-decoration:none;vertical-align:middle;">
            <img src="{google_play_img}" alt="Get it on Google Play" width="135" height="40" border="0" style="display:inline-block;height:40px;width:auto;border:0;outline:none;vertical-align:middle;border-radius:6px;">
          </a>
        </div>
      </div>
      <div style="margin:24px 0;text-align:center;">
        <a href="{invite_link}" target="_blank" rel="noopener noreferrer" style="background-color:#10b981;color:#ffffff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:bold;display:inline-block;">Accept Invitation</a>
      </div>
        '''
        plain_text = (
            f"Hi!\n\n"
            f"{plain_intro}\n\n"
            f"Download ListMate:\n"
            f"• iPhone: {ios_link}\n"
            f"• Android: {android_link}\n\n"
            f"To accept this invitation, click the link below and sign in with your Google or Apple account:\n\n"
            f"{invite_link}\n\n"
            f"This single-use invitation link expires in {days_remaining} days.\n\n"
            f"— The ListMate Team\n\n"
            f"--\n"
            f"ListMate • Powered by PVKS Labs\n"
            f"You received this reminder because a ListMate member invited you to their household.\n"
            f"Need help? Contact hello@grocerlist.app"
        )

    html_body = (
        f'<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,Helvetica,Arial,sans-serif;max-width:500px;margin:0 auto;padding:24px;border:1px solid #e2e8f0;border-radius:12px;background-color:#ffffff;color:#334155;">'
        f'<h2 style="font-size:20px;font-weight:700;color:#0f172a;margin-top:0;margin-bottom:12px;line-height:1.3;">{headline}</h2>'
        f'<p style="font-size:15px;color:#334155;line-height:1.5;margin-top:0;margin-bottom:12px;">{intro_p}</p>'
        f'<p style="font-size:14px;color:#64748b;line-height:1.5;margin-top:0;margin-bottom:20px;">With ListMate, your household can organize grocery items by store, sync live in the aisles, and eliminate duplicate shopping trips.</p>'
        f'{code_section_html}'
        f'<p style="font-size:12px;color:#94a3b8;line-height:1.5;margin-top:20px;margin-bottom:0;text-align:center;">Sign in with your Google or Apple account to join. This invite code expires in {days_remaining} days.</p>'
        f'<div style="font-size:11px;color:#888888;margin-top:24px;padding-top:16px;border-top:1px solid #e2e8f0;text-align:center;line-height:1.6;">'
        f'<p style="margin:3px 0;font-weight:600;color:#64748b;">ListMate • Powered by PVKS Labs</p>'
        f'<p style="margin:3px 0;color:#94a3b8;">You received this reminder because a ListMate member invited you to their household.</p>'
        f'<p style="margin:3px 0;color:#94a3b8;">Need help? Contact <a href="mailto:hello@grocerlist.app" style="color:#64748b;text-decoration:underline;">hello@grocerlist.app</a></p>'
        f'</div>'
        f'</div>'
    )

    payload = {
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "reply_to": {"email": FROM_EMAIL, "name": FROM_NAME},
        "personalizations": [{
            "to": [{"email": to_email}],
            "custom_args": {
                "user_id": str(user_id) if user_id else "",
                "household_id": str(household_id) if household_id else "",
                "campaign": campaign,
            },
        }],
        "categories": [campaign],
        "custom_args": {
            "user_id": str(user_id) if user_id else "",
            "household_id": str(household_id) if household_id else "",
            "campaign": campaign,
        },
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": plain_text},
            {"type": "text/html", "value": html_body},
        ],
        "tracking_settings": {
            "click_tracking": {"enable": True, "enable_text": False},
            "open_tracking": {"enable": True},
        },
    }
    return _send_via_api(api_key, payload)


def send_invite_expired_notice(
    to_email: str,
    inviter_name: str,
    invitee_email: str,
    household_name: str,
    user_id: int = 0,
    household_id: int = 0
) -> bool:
    """Send notice to household inviter/owner that an invitation has expired after 7 days."""
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        print("WARNING: SENDGRID_API_KEY not set — skipping email")
        return False

    campaign = "invite_expired_inviter"
    name_str = (inviter_name or "there").split(" ")[0].capitalize()
    subject = f"Household invite to {invitee_email} has expired"

    settings_link = f"{BASE_URL}/open?url={quote('/settings?action=add-member&source=email_invite_expired')}"
    unsub_txt, unsub_html = _get_unsub_blocks(user_id, "household notices", f"You received this notice because you manage the {household_name} household on ListMate.")

    plain_text = (
        f"Hi {name_str},\n\n"
        f"The 7-day household invitation code sent to {invitee_email} for \"{household_name}\" has expired without being used.\n\n"
        f"If they still want to join, you can generate and send a fresh invite code anytime from your Household Settings:\n"
        f"{settings_link}\n\n"
        f"— The ListMate Team" + unsub_txt
    )

    html_body = (
        f'<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,Helvetica,Arial,sans-serif;max-width:500px;margin:0 auto;padding:24px;border:1px solid #e2e8f0;border-radius:12px;background-color:#ffffff;color:#334155;">'
        f'<div style="text-align:center;margin-bottom:16px;">'
        f'<span style="display:inline-block;background:#fef3c7;color:#92400e;font-size:12px;font-weight:700;padding:4px 12px;border-radius:20px;text-transform:uppercase;letter-spacing:0.5px;">⏳ Invitation Expired</span>'
        f'<h2 style="font-size:20px;font-weight:700;color:#0f172a;margin:12px 0 6px 0;">Household Invite Expired</h2>'
        f'</div>'
        f'<p style="font-size:15px;color:#334155;line-height:1.5;">Hi {name_str},</p>'
        f'<p style="font-size:15px;color:#334155;line-height:1.5;">The 7-day invite code sent to <strong>{invitee_email}</strong> to join <strong>{household_name}</strong> has expired without being accepted.</p>'
        f'<p style="font-size:14px;color:#64748b;line-height:1.5;">You can easily generate and resend a new single-use invite code directly from your Household Settings whenever you\'re ready.</p>'
        f'<div style="text-align:center;margin:24px 0 16px 0;">'
        f'<a href="{settings_link}" style="background-color:#10b981;color:#ffffff;padding:12px 24px;border-radius:8px;text-decoration:none;font-size:15px;font-weight:700;display:inline-block;">Open Household Settings →</a>'
        f'</div>'
        f'</div>' + unsub_html
    )

    payload = {
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "reply_to": {"email": FROM_EMAIL, "name": FROM_NAME},
        "personalizations": [{
            "to": [{"email": to_email}],
            "custom_args": {
                "user_id": str(user_id) if user_id else "",
                "household_id": str(household_id) if household_id else "",
                "campaign": campaign,
            },
        }],
        "categories": [campaign],
        "custom_args": {
            "user_id": str(user_id) if user_id else "",
            "household_id": str(household_id) if household_id else "",
            "campaign": campaign,
        },
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": plain_text},
            {"type": "text/html", "value": html_body},
        ],
        "tracking_settings": {
            "click_tracking": {"enable": True, "enable_text": False},
            "open_tracking": {"enable": True},
        },
    }
    return _send_via_api(api_key, payload)


def _get_unsub_link(user_id: int) -> str:
    if not user_id: return ""
    import base64, json
    data = {"uid": user_id}
    token = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    return f"{BASE_URL}/api/unsubscribe?token={token}"

def _get_footer_blocks(user_id: int = 0, purpose: str = "marketing emails", context_reason: str = "You received this email because you are a registered user of ListMate.") -> tuple:
    """Returns (footer_txt, footer_html) with sender branding, context reason, support contact, and unsubscribe footer."""
    unsub_link = _get_unsub_link(user_id) if user_id else ""
    
    txt_lines = [
        "\n\n--",
        "ListMate • Powered by PVKS Labs",
    ]
    if context_reason:
        txt_lines.append(context_reason)
    txt_lines.append(f"Need help or have feedback? Contact hello@grocerlist.app or visit {BASE_URL}/requests")
    if unsub_link:
        txt_lines.append(f"To unsubscribe from {purpose}, visit: {unsub_link}")
    
    footer_txt = "\n".join(txt_lines)

    html_parts = [
        '<div style="font-size: 11px; color: #888888; margin-top: 28px; padding-top: 16px; border-top: 1px solid #e2e8f0; text-align: center; line-height: 1.6;">',
        '<p style="margin: 3px 0; font-weight: 600; color: #64748b;">ListMate • Powered by PVKS Labs</p>',
    ]
    if context_reason:
        html_parts.append(f'<p style="margin: 3px 0; color: #94a3b8;">{context_reason}</p>')
    html_parts.append(f'<p style="margin: 3px 0; color: #94a3b8;">Need help or have feedback? Contact <a href="mailto:hello@grocerlist.app" style="color: #64748b; text-decoration: underline;">hello@grocerlist.app</a> or visit <a href="{BASE_URL}/requests" style="color: #64748b; text-decoration: underline;">Support & Roadmap</a>.</p>')
    if unsub_link:
        html_parts.append(f'<p style="margin: 6px 0 0 0;"><a href="{unsub_link}" style="color: #94a3b8; text-decoration: underline;">Unsubscribe</a> from {purpose}.</p>')
    html_parts.append('</div>')
    
    footer_html = "\n".join(html_parts)
    return footer_txt, footer_html

def _get_unsub_blocks(user_id: int, purpose: str = "marketing emails", context_reason: str = "You received this email because you are a registered user of ListMate.") -> tuple:
    """Returns (footer_txt, footer_html) for backwards compatibility."""
    return _get_footer_blocks(user_id=user_id, purpose=purpose, context_reason=context_reason)

def send_subscription_notice(to_email: str, user_name: str, is_trial: bool, days_left: int, user_id: int = 0, household_id: int = 0) -> bool:
    """Send subscription ending notice. Returns True on success."""
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        print("WARNING: SENDGRID_API_KEY not set — skipping email")
        return False

    term = "trial" if is_trial else "subscription"
    campaign = f"{'trial' if is_trial else 'sub'}_exp_{'today' if days_left == 0 else '3days'}"
    if days_left == 0:
        subject = f"Your ListMate {term} ends today"
        urgency_text = "expires today"
    else:
        subject = f"Your ListMate {term} ends in {days_left} days"
        urgency_text = f"expires in {days_left} days"

    upgrade_link = f"{BASE_URL}/open?url={quote('/settings?action=upgrade&source=email_reminder')}"
    add_member_link = f"{BASE_URL}/open?url={quote('/settings?action=add-member&source=email_reminder')}"

    unsub_txt, unsub_html = _get_unsub_blocks(user_id, "subscription and billing reminders", "You received this email because you created a ListMate household or manage a household subscription.")
    payload = {
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "reply_to": {"email": FROM_EMAIL, "name": FROM_NAME},
        "personalizations": [{
            "to": [{"email": to_email}],
            "custom_args": {
                "user_id": str(user_id) if user_id else "",
                "household_id": str(household_id) if household_id else "",
                "campaign": campaign,
            },
        }],
        "categories": [campaign],
        "custom_args": {
            "user_id": str(user_id) if user_id else "",
            "household_id": str(household_id) if household_id else "",
            "campaign": campaign,
        },
        "subject": subject,
        "content": [
            {
                "type": "text/plain",
                "value": (
                    f"Hi {user_name},\n\n"
                    f"Your ListMate {term} {urgency_text}.\n\n"
                    f"Don't lose access to your shared grocery lists! Upgrade your household today to keep everything syncing seamlessly across all your household members.\n\n"
                    f"Upgrade Household: {upgrade_link}\n"
                    f"Add Household Members: {add_member_link}\n\n"
                    f"— The ListMate Team" + unsub_txt
                ),
            },
            {
                "type": "text/html",
                "value": (
                    f'<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;max-width:520px;margin:0 auto;padding:24px 20px;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;">'
                    f'<h2 style="color:#2c5a2c;margin-top:0;">⏳ Action Required</h2>'
                    f'<p style="font-size:16px;color:#333;">Hi {user_name},</p>'
                    f'<p style="font-size:15px;color:#333;line-height:1.5;">Your ListMate <strong>{term}</strong> {urgency_text}.</p>'
                    f'<p style="font-size:15px;color:#333;line-height:1.5;">Don\'t lose access to your shared grocery lists! Upgrade your household to keep real-time sync active across all members.</p>'
                    f'<div style="margin:24px 0 16px;">'
                    f'<a href="{upgrade_link}" style="display:inline-block;background:#5ebe7e;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-size:15px;font-weight:bold;margin-right:10px;margin-bottom:8px;">Upgrade Household Now</a>'
                    f'<a href="{add_member_link}" style="display:inline-block;background:#f0fdf4;color:#166534;border:1px solid #bbf7d0;padding:12px 20px;border-radius:8px;text-decoration:none;font-size:14px;font-weight:600;margin-bottom:8px;">Add Members</a>'
                    f'</div>'
                    f'<p style="font-size:13px;color:#666;line-height:1.4;">Remember: Only one subscription is needed per household ($1.99/mo or $9.99/yr). All invited members join and sync free!</p>'
                    f'</div>' + unsub_html
                ),
            },
        ],
        "tracking_settings": {
            "click_tracking": {"enable": True, "enable_text": False},
            "open_tracking": {"enable": True},
        },
    }
    return _send_via_api(api_key, payload)


def send_solo_nudge_notice(to_email: str, user_name: str, user_id: int = 0, household_id: int = 0) -> bool:
    """Send Day 3 nudge to solo household owners to invite their family/roommates."""
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        print("WARNING: SENDGRID_API_KEY not set — skipping email")
        return False

    campaign = "solo_nudge"
    add_member_link = f"{BASE_URL}/open?url={quote('/settings?action=add-member&source=email_solo_nudge')}"
    upgrade_link = f"{BASE_URL}/open?url={quote('/settings?action=upgrade&source=email_solo_nudge')}"

    unsub_txt, unsub_html = _get_unsub_blocks(user_id, "marketing emails", "You received this email because you created a household on ListMate.")

    payload = {
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "reply_to": {"email": FROM_EMAIL, "name": FROM_NAME},
        "personalizations": [{
            "to": [{"email": to_email}],
            "custom_args": {
                "user_id": str(user_id) if user_id else "",
                "household_id": str(household_id) if household_id else "",
                "campaign": campaign,
            },
        }],
        "categories": [campaign],
        "custom_args": {
            "user_id": str(user_id) if user_id else "",
            "household_id": str(household_id) if household_id else "",
            "campaign": campaign,
        },
        "subject": "Get the most out of ListMate: Invite your household 🛒",
        "content": [
            {
                "type": "text/plain",
                "value": (
                    f"Hi {user_name},\n\n"
                    f"We noticed you're the only member in your ListMate household so far.\n\n"
                    f"Did you know ListMate works best when shared? When your partner, spouse, or roommates join your household:\n"
                    f"• Everyone adds items in real time as they run out.\n"
                    f"• Checked items cross off instantly so you never buy duplicates.\n"
                    f"• No more texting back and forth while standing in the grocery store aisle!\n\n"
                    f"💡 Good to know: Only the household pays for a subscription ($1.99/mo or $9.99/yr). Individual members NEVER pay to join and sync.\n\n"
                    f"Invite Household Members:\n{add_member_link}\n\n"
                    f"View Subscription Plans:\n{upgrade_link}\n\n"
                    f"— The ListMate Team" + unsub_txt
                ),
            },
            {
                "type": "text/html",
                "value": (
                    f'<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;max-width:520px;margin:0 auto;padding:24px 20px;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;">'
                    f'<h2 style="color:#2c5a2c;margin-top:0;">👥 Share the List, Cut the Chaos</h2>'
                    f'<p style="font-size:16px;color:#333;">Hi {user_name},</p>'
                    f'<p style="font-size:15px;color:#333;line-height:1.5;">We noticed you\'re currently the only member in your ListMate household.</p>'
                    f'<p style="font-size:15px;color:#333;line-height:1.5;">ListMate is built for real-time collaboration. When your partner, family members, or roommates join:</p>'
                    f'<ul style="font-size:14px;color:#444;line-height:1.6;padding-left:20px;">'
                    f'<li><strong>Live household sync:</strong> Everyone adds items as they run out.</li>'
                    f'<li><strong>Zero duplicate buys:</strong> Items cross off in real time on all devices.</li>'
                    f'<li><strong>End messy chat threads:</strong> No more scrolling through WhatsApp or Keep notes in the aisle.</li>'
                    f'</ul>'
                    f'<div style="background:#f0fdf4;border-left:4px solid #5ebe7e;padding:12px 16px;margin:18px 0;border-radius:4px;">'
                    f'<strong style="color:#166534;display:block;margin-bottom:4px;">💡 Important to know:</strong>'
                    f'<span style="color:#274c36;font-size:13px;line-height:1.4;">Only the household pays for a Pro subscription ($1.99/mo or $9.99/yr). Invited household members join, edit, and sync completely free of charge!</span>'
                    f'</div>'
                    f'<div style="margin:24px 0 16px;">'
                    f'<a href="{add_member_link}" style="display:inline-block;background:#5ebe7e;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-size:15px;font-weight:bold;margin-right:10px;margin-bottom:8px;">👥 Invite Household Members</a>'
                    f'<a href="{upgrade_link}" style="display:inline-block;background:#f8fafc;color:#334155;border:1px solid #cbd5e1;padding:12px 20px;border-radius:8px;text-decoration:none;font-size:14px;font-weight:600;margin-bottom:8px;">⭐ View Pro Plans</a>'
                    f'</div>'
                    f'</div>' + unsub_html
                ),
            },
        ],
        "tracking_settings": {
            "click_tracking": {"enable": True, "enable_text": False},
            "open_tracking": {"enable": True},
        },
    }
    return _send_via_api(api_key, payload)


def send_store_nudge_notice(to_email: str, user_name: str, user_id: int = 0, household_id: int = 0) -> bool:
    """Send Day 3 nudge to households that only have General List and no custom stores."""
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        print("WARNING: SENDGRID_API_KEY not set — skipping email")
        return False

    campaign = "store_nudge"
    add_store_link = f"{BASE_URL}/open?url={quote('/?action=add_store&source=email_store_nudge')}"
    unsub_txt, unsub_html = _get_unsub_blocks(user_id, "marketing emails", "You received this email because you are using ListMate to organize your grocery lists.")

    payload = {
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "reply_to": {"email": FROM_EMAIL, "name": FROM_NAME},
        "personalizations": [{
            "to": [{"email": to_email}],
            "custom_args": {
                "user_id": str(user_id) if user_id else "",
                "household_id": str(household_id) if household_id else "",
                "campaign": campaign,
            },
        }],
        "categories": [campaign],
        "custom_args": {
            "user_id": str(user_id) if user_id else "",
            "household_id": str(household_id) if household_id else "",
            "campaign": campaign,
        },
        "subject": "Streamline your grocery runs with store-specific lists 🏪",
        "content": [
            {
                "type": "text/plain",
                "value": (
                    f"Hi {user_name},\n\n"
                    f"We noticed you've been building your grocery list in the General List on ListMate.\n\n"
                    f"Did you know you can add the specific stores where your household shops (like Trader Joe's, Costco, Safeway, or Target)?\n\n"
                    f"Here's how store lists make shopping easier:\n"
                    f"• Organize by aisle: Items group automatically under each store so you can navigate aisles smoothly.\n"
                    f"• Master Store Catalogs: Easily re-add frequently bought essentials in one tap.\n"
                    f"• Smart item routing: ListMate remembers where you buy each item and routes it automatically!\n\n"
                    f"Add your favorite stores to ListMate:\n"
                    f"{add_store_link}\n\n"
                    f"— The ListMate Team" + unsub_txt
                ),
            },
            {
                "type": "text/html",
                "value": (
                    f'<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;max-width:520px;margin:0 auto;padding:24px 20px;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;">'
                    f'<h2 style="color:#2c5a2c;margin-top:0;">🏪 Organize by Store, Shop Faster</h2>'
                    f'<p style="font-size:16px;color:#333;">Hi {user_name},</p>'
                    f'<p style="font-size:15px;color:#333;line-height:1.5;">We noticed you\'ve been adding items to your <strong>General List</strong> in ListMate.</p>'
                    f'<p style="font-size:15px;color:#333;line-height:1.5;">Did you know you can add the dedicated stores your household shops at (like Trader Joe\'s, Costco, Safeway, or Target)?</p>'
                    f'<ul style="font-size:14px;color:#444;line-height:1.6;padding-left:20px;">'
                    f'<li><strong>Aisle & store grouping:</strong> Keep your shopping trips organized and focused by store.</li>'
                    f'<li><strong>Master catalogs:</strong> Pull frequently purchased essentials into your active trip in one tap.</li>'
                    f'<li><strong>Smart routing:</strong> ListMate remembers where items belong and suggests the right store automatically.</li>'
                    f'</ul>'
                    f'<div style="margin:24px 0 16px;">'
                    f'<a href="{add_store_link}" style="display:inline-block;background:#5ebe7e;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-size:15px;font-weight:bold;margin-right:10px;margin-bottom:8px;">➕ Add a Store to ListMate</a>'
                    f'</div>'
                    f'</div>' + unsub_html
                ),
            },
        ],
        "tracking_settings": {
            "click_tracking": {"enable": True, "enable_text": False},
            "open_tracking": {"enable": True},
        },
    }
    return _send_via_api(api_key, payload)


def send_trial_week1_checkin(to_email: str, user_name: str, user_id: int = 0, household_id: int = 0) -> bool:
    """Send Day 7 (Week 1) check-in email asking for feedback and highlighting discovery tips & upgrade options."""
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        print("WARNING: SENDGRID_API_KEY not set — skipping email")
        return False

    campaign = "trial_week1"
    upgrade_link = f"{BASE_URL}/open?url={quote('/settings?action=upgrade&source=email_trial_week1')}"
    add_member_link = f"{BASE_URL}/open?url={quote('/settings?action=add-member&source=email_trial_week1')}"
    app_link = f"{BASE_URL}/open?url={quote('/?source=email_trial_week1')}"

    unsub_txt, unsub_html = _get_unsub_blocks(user_id, "marketing emails", "You received this email because your household is currently enjoying its ListMate 30-day Pro trial.")

    payload = {
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "reply_to": {"email": FROM_EMAIL, "name": FROM_NAME},
        "personalizations": [{
            "to": [{"email": to_email}],
            "custom_args": {
                "user_id": str(user_id) if user_id else "",
                "household_id": str(household_id) if household_id else "",
                "campaign": campaign,
            },
        }],
        "categories": [campaign],
        "custom_args": {
            "user_id": str(user_id) if user_id else "",
            "household_id": str(household_id) if household_id else "",
            "campaign": campaign,
        },
        "subject": "How's your first week with ListMate? 🛒",
        "content": [
            {
                "type": "text/plain",
                "value": (
                    f"Hi {user_name},\n\n"
                    f"How is your first week with ListMate going? We hope your grocery runs have been faster and more organized!\n\n"
                    f"You are currently enjoying your 30-day free Pro trial with unlimited stores and real-time syncing.\n\n"
                    f"💡 Upgrade Early & Keep Your Full Trial:\n"
                    f"You can choose a monthly ($1.99/mo) or annual ($9.99/yr) plan anytime. When you upgrade early, you will STILL receive your full 30-day trial period before your paid subscription begins!\n\n"
                    f"💡 Feature Discovery Tips:\n"
                    f"Be sure to check out the \"Feature Discovery Tips\" in the app menu to learn about aisle auto-sorting, store filters (Costco, Patel Brothers, Trader Joe's, etc.), and multi-store planning.\n\n"
                    f"Upgrade Household: {upgrade_link}\n"
                    f"Add Household Members: {add_member_link}\n"
                    f"Open ListMate: {app_link}\n\n"
                    f"— The ListMate Team" + unsub_txt
                ),
            },
            {
                "type": "text/html",
                "value": (
                    f'<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;max-width:520px;margin:0 auto;padding:24px 20px;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;">'
                    f'<h2 style="color:#2c5a2c;margin-top:0;">🌟 1 Week Down with ListMate</h2>'
                    f'<p style="font-size:16px;color:#333;">Hi {user_name},</p>'
                    f'<p style="font-size:15px;color:#333;line-height:1.5;">How has your first week of grocery shopping with ListMate been? We hope it’s making trips smoother for your household!</p>'
                    f'<p style="font-size:15px;color:#333;line-height:1.5;">You are currently enjoying your <strong>30-day Pro trial</strong> with live sync and store-by-store categorization.</p>'
                    f'<div style="background:#f8fafc;border:1px solid #e2e8f0;padding:14px 16px;margin:16px 0;border-radius:8px;">'
                    f'<strong style="color:#1e293b;display:block;margin-bottom:6px;font-size:14px;">💡 Lock in your plan early without losing trial days:</strong>'
                    f'<span style="color:#475569;font-size:13px;line-height:1.5;display:block;">You can select a monthly ($1.99/mo) or annual ($9.99/yr) plan today. Your paid billing will only start <em>after</em> your 30-day trial concludes.</span>'
                    f'</div>'
                    f'<div style="background:#ecfdf5;border:1px solid #a7f3d0;padding:14px 16px;margin:16px 0;border-radius:8px;">'
                    f'<strong style="color:#065f46;display:block;margin-bottom:6px;font-size:14px;">✨ Explore Feature Discovery Tips:</strong>'
                    f'<span style="color:#047857;font-size:13px;line-height:1.5;display:block;">Open the top menu in the app and tap <strong>Feature Discovery Tips</strong> to master aisle auto-sorting, store filtering (Patel Brothers, Costco, Trader Joe\'s), and real-time checkoffs!</span>'
                    f'</div>'
                    f'<div style="margin:24px 0 16px;">'
                    f'<a href="{upgrade_link}" style="display:inline-block;background:#5ebe7e;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-size:15px;font-weight:bold;margin-right:10px;margin-bottom:8px;">⭐ Upgrade Subscription</a>'
                    f'<a href="{add_member_link}" style="display:inline-block;background:#f0fdf4;color:#166534;border:1px solid #bbf7d0;padding:12px 20px;border-radius:8px;text-decoration:none;font-size:14px;font-weight:600;margin-bottom:8px;">👥 Add Members</a>'
                    f'</div>'
                    f'<p style="font-size:12px;color:#888;line-height:1.4;margin-top:20px;">Have questions or feedback? Reply directly to this email—we read every message!</p>'
                    f'</div>' + unsub_html
                ),
            },
        ],
        "tracking_settings": {
            "click_tracking": {"enable": True, "enable_text": False},
            "open_tracking": {"enable": True},
        },
    }
    return _send_via_api(api_key, payload)


def send_trial_week3_checkin(to_email: str, user_name: str, user_id: int = 0, household_id: int = 0) -> bool:
    """Send Day 21 (Week 3) check-in email with ~9 days left of trial."""
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        print("WARNING: SENDGRID_API_KEY not set — skipping email")
        return False

    campaign = "trial_week3"
    upgrade_link = f"{BASE_URL}/open?url={quote('/settings?action=upgrade&source=email_trial_week3')}"
    add_member_link = f"{BASE_URL}/open?url={quote('/settings?action=add-member&source=email_trial_week3')}"
    app_link = f"{BASE_URL}/open?url={quote('/?source=email_trial_week3')}"

    unsub_txt, unsub_html = _get_unsub_blocks(user_id, "marketing emails", "You received this email because your household is currently enjoying its ListMate 30-day Pro trial.")

    payload = {
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "reply_to": {"email": FROM_EMAIL, "name": FROM_NAME},
        "personalizations": [{
            "to": [{"email": to_email}],
            "custom_args": {
                "user_id": str(user_id) if user_id else "",
                "household_id": str(household_id) if household_id else "",
                "campaign": campaign,
            },
        }],
        "categories": [campaign],
        "custom_args": {
            "user_id": str(user_id) if user_id else "",
            "household_id": str(household_id) if household_id else "",
            "campaign": campaign,
        },
        "subject": "3 weeks with ListMate — how is grocery shopping going? 🛒",
        "content": [
            {
                "type": "text/plain",
                "value": (
                    f"Hi {user_name},\n\n"
                    f"You're 3 weeks into your ListMate Pro trial (~9 days remaining)!\n\n"
                    f"We hope ListMate has saved your household time, cut down on duplicate purchases, and made grocery trips stress-free.\n\n"
                    f"💡 Lock in your Pro Plan anytime:\n"
                    f"Upgrade to a monthly ($1.99/mo) or annual ($9.99/yr) subscription to ensure your household continues syncing without interruption. Upgrading now still gives you the full remaining days of your free trial!\n\n"
                    f"Remember: One subscription covers your whole household.\n\n"
                    f"Upgrade Household: {upgrade_link}\n"
                    f"Add Household Members: {add_member_link}\n"
                    f"Open ListMate: {app_link}\n\n"
                    f"— The ListMate Team" + unsub_txt
                ),
            },
            {
                "type": "text/html",
                "value": (
                    f'<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;max-width:520px;margin:0 auto;padding:24px 20px;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;">'
                    f'<h2 style="color:#2c5a2c;margin-top:0;">🛒 3 Weeks with ListMate</h2>'
                    f'<p style="font-size:16px;color:#333;">Hi {user_name},</p>'
                    f'<p style="font-size:15px;color:#333;line-height:1.5;">You\'re three weeks into your 30-day ListMate Pro trial, with about 9 days left!</p>'
                    f'<p style="font-size:15px;color:#333;line-height:1.5;">We hope ListMate has helped streamline your grocery runs and eliminated the chaos of duplicate buying and forgotten items.</p>'
                    f'<div style="background:#f8fafc;border:1px solid #e2e8f0;padding:14px 16px;margin:16px 0;border-radius:8px;">'
                    f'<strong style="color:#1e293b;display:block;margin-bottom:6px;font-size:14px;">💡 Keep your household in sync:</strong>'
                    f'<span style="color:#475569;font-size:13px;line-height:1.5;display:block;">Upgrade for just <strong>$1.99/mo</strong> or <strong>$9.99/yr</strong>. Locking in your subscription now preserves your remaining free trial days, so you won\'t be charged until the 30-day period ends.</span>'
                    f'</div>'
                    f'<div style="margin:24px 0 16px;">'
                    f'<a href="{upgrade_link}" style="display:inline-block;background:#5ebe7e;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-size:15px;font-weight:bold;margin-right:10px;margin-bottom:8px;">⭐ Upgrade Subscription</a>'
                    f'<a href="{add_member_link}" style="display:inline-block;background:#f0fdf4;color:#166534;border:1px solid #bbf7d0;padding:12px 20px;border-radius:8px;text-decoration:none;font-size:14px;font-weight:600;margin-bottom:8px;">👥 Add Members</a>'
                    f'</div>'
                    f'<p style="font-size:13px;color:#666;line-height:1.4;">Only one subscription is needed per household—all family members and roommates sync free!</p>'
                    f'</div>' + unsub_html
                ),
            },
        ],
        "tracking_settings": {
            "click_tracking": {"enable": True, "enable_text": False},
            "open_tracking": {"enable": True},
        },
    }
    return _send_via_api(api_key, payload)


def send_activation_notice(to_email: str, user_name: str, user_id: int = 0, household_id: int = 0) -> bool:
    """Send Day 3 onboarding/activation notice to inactive users."""
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        print("WARNING: SENDGRID_API_KEY not set — skipping email")
        return False

    campaign = "activation"
    app_link = f"{BASE_URL}/open?url={quote('/?source=email_activation')}"
    add_member_link = f"{BASE_URL}/open?url={quote('/settings?action=add-member&source=email_activation')}"

    unsub_txt, unsub_html = _get_unsub_blocks(user_id, "marketing emails", "You received this email because you recently signed up for ListMate.")
    payload = {
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "reply_to": {"email": FROM_EMAIL, "name": FROM_NAME},
        "personalizations": [{
            "to": [{"email": to_email}],
            "custom_args": {
                "user_id": str(user_id) if user_id else "",
                "household_id": str(household_id) if household_id else "",
                "campaign": campaign,
            },
        }],
        "categories": [campaign],
        "custom_args": {
            "user_id": str(user_id) if user_id else "",
            "household_id": str(household_id) if household_id else "",
            "campaign": campaign,
        },
        "subject": "Simplify your grocery runs with ListMate 🛒",
        "content": [
            {
                "type": "text/plain",
                "value": (
                    f"Hi {user_name},\n\n"
                    f"We noticed you haven't added any items to ListMate yet!\n\n"
                    f"Did you know that sharing a real-time grocery list with your partner or housemates makes shopping effortless and can save your household hundreds of dollars a year in forgotten items, duplicate purchases, and impulse buys?\n\n"
                    f"When everyone adds items as they run out, whoever visits the store always has the exact, up-to-date list in their pocket.\n\n"
                    f"Add your first items: {app_link}\n"
                    f"Invite your household: {add_member_link}\n\n"
                    f"— The ListMate Team" + unsub_txt
                ),
            },
            {
                "type": "text/html",
                "value": (
                    f'<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;max-width:520px;margin:0 auto;padding:24px 20px;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;">'
                    f'<h2 style="color:#2c5a2c;margin-top:0;">👋 Getting started with ListMate</h2>'
                    f'<p style="font-size:16px;color:#333;">Hi {user_name},</p>'
                    f'<p style="font-size:15px;color:#333;line-height:1.5;">We noticed you haven\'t added any items to ListMate yet!</p>'
                    f'<p style="font-size:15px;color:#333;line-height:1.5;">Did you know that sharing a real-time grocery list with your partner or housemates makes shopping effortless and can <strong>save your household hundreds of dollars a year</strong> in forgotten items, duplicate purchases, and impulse buys?</p>'
                    f'<p style="font-size:15px;color:#333;line-height:1.5;">When everyone adds items as they run out, whoever visits the store always has the exact, up-to-date list in their pocket.</p>'
                    f'<div style="margin:24px 0 16px;">'
                    f'<a href="{app_link}" style="display:inline-block;background:#5ebe7e;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-size:15px;font-weight:bold;margin-right:10px;margin-bottom:8px;">Add First Item</a>'
                    f'<a href="{add_member_link}" style="display:inline-block;background:#f0fdf4;color:#166534;border:1px solid #bbf7d0;padding:12px 20px;border-radius:8px;text-decoration:none;font-size:14px;font-weight:600;margin-bottom:8px;">👥 Invite Members</a>'
                    f'</div>'
                    f'</div>' + unsub_html
                ),
            },
        ],
        "tracking_settings": {
            "click_tracking": {"enable": True, "enable_text": False},
            "open_tracking": {"enable": True},
        },
    }
    return _send_via_api(api_key, payload)


def send_reengagement_notice(to_email: str, user_name: str, user_id: int = 0, household_id: int = 0) -> bool:
    """Send Day 14 re-engagement notice to dormant users."""
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        print("WARNING: SENDGRID_API_KEY not set — skipping email")
        return False

    campaign = "reengagement"
    app_link = f"{BASE_URL}/open?url={quote('/?source=email_reengagement')}"
    add_member_link = f"{BASE_URL}/open?url={quote('/settings?action=add-member&source=email_reengagement')}"

    unsub_txt, unsub_html = _get_unsub_blocks(user_id, "marketing emails", "You received this email because you are a registered user of ListMate.")
    payload = {
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "reply_to": {"email": FROM_EMAIL, "name": FROM_NAME},
        "personalizations": [{
            "to": [{"email": to_email}],
            "custom_args": {
                "user_id": str(user_id) if user_id else "",
                "household_id": str(household_id) if household_id else "",
                "campaign": campaign,
            },
        }],
        "categories": [campaign],
        "custom_args": {
            "user_id": str(user_id) if user_id else "",
            "household_id": str(household_id) if household_id else "",
            "campaign": campaign,
        },
        "subject": "It's been a while! Streamline your next grocery trip 🛒",
        "content": [
            {
                "type": "text/plain",
                "value": (
                    f"Hi {user_name},\n\n"
                    f"It's been a couple of weeks since your last update on ListMate. We wanted to remind you that your shared grocery lists are waiting for you!\n\n"
                    f"Sharing a live, store-organized grocery list with your household is one of the easiest ways to smooth out shopping trips and cut down on impulse buys—saving you both time and money.\n\n"
                    f"Check out our latest features, including instant store-based aisle organization, to make your next trip seamless.\n\n"
                    f"Plan your next trip: {app_link}\n"
                    f"Invite household members: {add_member_link}\n\n"
                    f"— The ListMate Team" + unsub_txt
                ),
            },
            {
                "type": "text/html",
                "value": (
                    f'<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;max-width:520px;margin:0 auto;padding:24px 20px;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;">'
                    f'<h2 style="color:#2c5a2c;margin-top:0;">🛒 It\'s been a while!</h2>'
                    f'<p style="font-size:16px;color:#333;">Hi {user_name},</p>'
                    f'<p style="font-size:15px;color:#333;line-height:1.5;">It\'s been a couple of weeks since your last update on ListMate. We wanted to remind you that your shared grocery lists are waiting for you!</p>'
                    f'<p style="font-size:15px;color:#333;line-height:1.5;">Sharing a live, store-organized grocery list with your household is one of the easiest ways to smooth out shopping trips and cut down on impulse buys—<strong>saving you both time and money</strong>.</p>'
                    f'<div style="margin:24px 0 16px;">'
                    f'<a href="{app_link}" style="display:inline-block;background:#5ebe7e;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-size:15px;font-weight:bold;margin-right:10px;margin-bottom:8px;">Plan Your Next Trip</a>'
                    f'<a href="{add_member_link}" style="display:inline-block;background:#f0fdf4;color:#166534;border:1px solid #bbf7d0;padding:12px 20px;border-radius:8px;text-decoration:none;font-size:14px;font-weight:600;margin-bottom:8px;">👥 Invite Members</a>'
                    f'</div>'
                    f'</div>' + unsub_html
                ),
            },
        ],
        "tracking_settings": {
            "click_tracking": {"enable": True, "enable_text": False},
            "open_tracking": {"enable": True},
        },
    }
    return _send_via_api(api_key, payload)


def send_combined_notice(to_email: str, user_name: str, events: dict, user_id: int = 0, household_id: int = 0) -> bool:
    """Send a combined notice when multiple daily events occur for the same user."""
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        print("WARNING: SENDGRID_API_KEY not set — skipping email")
        return False

    campaign = "combined"
    app_link = f"{BASE_URL}/open?url={quote('/?source=email_combined')}"
    upgrade_link = f"{BASE_URL}/open?url={quote('/settings?action=upgrade&source=email_combined')}"
    add_member_link = f"{BASE_URL}/open?url={quote('/settings?action=add-member&source=email_combined')}"
    add_store_link = f"{BASE_URL}/open?url={quote('/?action=add_store&source=email_combined')}"

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
        html_sections.append(f'<h3 style="color:#d32f2f;margin-top:0;">⏳ {term.capitalize()} {urgency}</h3><p style="font-size:15px;color:#333;line-height:1.5;">Upgrade your household to keep real-time sync active across all your household members without interruption.</p>')
    elif 'trial_week1' in events:
        subject = "How's your first week with ListMate? 🛒"
    elif 'trial_week3' in events:
        subject = "3 weeks with ListMate — how is grocery shopping going? 🛒"
    elif 'store_nudge' in events:
        subject = "Streamline your grocery runs with store-specific lists 🏪"
    elif 'solo_nudge' in events:
        subject = "Get the most out of ListMate: Invite your household 🛒"
    else:
        subject = "Updates from ListMate 🛒"

    if 'store_nudge' in events:
        text_sections.append(
            f"Organize by Store, Shop Faster:\n"
            f"Did you know you can add the dedicated stores where your household shops (like Trader Joe's, Costco, Safeway, or Target)?\n"
            f"Items automatically organize by store and aisle so your grocery runs are faster and more organized.\n"
            f"Add a Store: {add_store_link}"
        )
        html_sections.append(
            f'<div style="background:#f0fdf4;border-left:4px solid #5ebe7e;padding:12px 16px;margin:14px 0;border-radius:4px;">'
            f'<strong style="color:#166534;display:block;margin-bottom:4px;">🏪 Organize by Store:</strong>'
            f'<span style="color:#274c36;font-size:14px;line-height:1.5;">Did you know you can add the specific stores your household shops at? Organizing by store and aisle makes shopping faster and stress-free.</span>'
            f'<div style="margin-top:8px;"><a href="{add_store_link}" style="color:#166534;font-weight:bold;font-size:13px;text-decoration:underline;">➕ Add a Store &rarr;</a></div>'
            f'</div>'
        )

    if 'solo_nudge' in events:
        text_sections.append(
            f"Share the List, Cut the Chaos:\n"
            f"ListMate works best when shared with your partner, family, or roommates. Everyone adds items as they run out, and items cross off in real time so nobody buys duplicates.\n"
            f"Remember: Only one subscription is needed per household ($1.99/mo or $9.99/yr)—all invited members join and sync free!"
        )
        html_sections.append(
            f'<div style="background:#f0fdf4;border-left:4px solid #5ebe7e;padding:12px 16px;margin:14px 0;border-radius:4px;">'
            f'<strong style="color:#166534;display:block;margin-bottom:4px;">👥 Invite Your Household:</strong>'
            f'<span style="color:#274c36;font-size:14px;line-height:1.5;">ListMate works best when shared with your partner, family, or roommates. Only the household pays for a Pro plan ($1.99/mo or $9.99/yr)—all invited members sync 100% free!</span>'
            f'</div>'
        )

    if 'trial_week1' in events:
        text_sections.append(
            f"1 Week Down with ListMate:\n"
            f"You're currently enjoying your 30-day Pro trial. You can lock in your monthly ($1.99/mo) or annual ($9.99/yr) plan anytime—your billing will only start after your full 30-day trial finishes.\n"
            f"Tip: Explore Feature Discovery Tips in the app menu for smart aisle sorting and store filters."
        )
        html_sections.append(
            f'<div style="background:#f8fafc;border:1px solid #e2e8f0;padding:12px 16px;margin:14px 0;border-radius:8px;">'
            f'<strong style="color:#1e293b;display:block;margin-bottom:4px;">🌟 1 Week Down with ListMate:</strong>'
            f'<span style="color:#475569;font-size:13px;line-height:1.5;">Upgrading early preserves your full 30-day trial period before billing starts. Check out the <strong>Feature Discovery Tips</strong> in the app menu to learn about aisle sorting and store filters!</span>'
            f'</div>'
        )

    if 'trial_week3' in events:
        text_sections.append(
            f"3 Weeks with ListMate (~9 days left of trial):\n"
            f"Ensure uninterrupted syncing for your entire household by upgrading to monthly ($1.99/mo) or annual ($9.99/yr) before your trial ends."
        )
        html_sections.append(
            f'<div style="background:#f8fafc;border:1px solid #e2e8f0;padding:12px 16px;margin:14px 0;border-radius:8px;">'
            f'<strong style="color:#1e293b;display:block;margin-bottom:4px;">⏳ 3 Weeks with ListMate (~9 days left):</strong>'
            f'<span style="color:#475569;font-size:13px;line-height:1.5;">Lock in your household subscription ($1.99/mo or $9.99/yr) anytime without losing any remaining trial days.</span>'
            f'</div>'
        )

    if 'activation' in events:
        text_sections.append(
            f"You haven't added any items to ListMate yet!\n"
            f"Did you know sharing a real-time grocery list with your household can save hundreds of dollars each year in impulse and duplicate purchases? Tap here to get started:\n{app_link}"
        )
        html_sections.append(
            f'<div style="margin:14px 0;">'
            f'<h4 style="color:#2c5a2c;margin:0 0 6px 0;">👋 Getting Started</h4>'
            f'<p style="font-size:14px;color:#444;line-height:1.5;margin:0;">We noticed you haven\'t added any items yet. Sharing a live list with your partner or housemates makes store trips smoother and prevents duplicate buys.</p>'
            f'</div>'
        )

    if 'reengagement' in events:
        text_sections.append(
            f"It's been a while! We wanted to remind you that your shared lists are waiting for you.\n"
            f"Keep your household synced and cut down on extra store runs and duplicate buys:\n{app_link}"
        )
        html_sections.append(
            f'<div style="margin:14px 0;">'
            f'<h4 style="color:#2c5a2c;margin:0 0 6px 0;">🛒 It\'s been a while!</h4>'
            f'<p style="font-size:14px;color:#444;line-height:1.5;margin:0;">We wanted to remind you that your shared lists are waiting for you. Stay synced with your household to avoid duplicate buys and make every grocery run effortless.</p>'
            f'</div>'
        )

    if 'invite_expired' in events:
        inv_data = events['invite_expired']
        invitee_lbl = inv_data.get('invitee_email', 'a household member')
        hh_lbl = inv_data.get('household_name', 'your household')
        text_sections.append(
            f"Household Invite Expired:\n"
            f"The 7-day invitation code sent to {invitee_lbl} for {hh_lbl} has expired without being used.\n"
            f"You can generate and resend a fresh invite code anytime in Household Settings:\n{add_member_link}"
        )
        html_sections.append(
            f'<div style="background:#fffbeb;border-left:4px solid #f59e0b;padding:12px 16px;margin:14px 0;border-radius:4px;">'
            f'<strong style="color:#92400e;display:block;margin-bottom:4px;">⏳ Household Invite Expired:</strong>'
            f'<span style="color:#78350f;font-size:14px;line-height:1.5;">The invite code sent to <strong>{invitee_lbl}</strong> has expired. You can resend a fresh code anytime from your Household Settings.</span>'
            f'<div style="margin-top:8px;"><a href="{add_member_link}" style="color:#92400e;font-weight:bold;font-size:13px;text-decoration:underline;">Resend Invite &rarr;</a></div>'
            f'</div>'
        )

    action_buttons = (
        f'<div style="margin:24px 0 16px;">'
        f'<a href="{upgrade_link}" style="display:inline-block;background:#5ebe7e;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-size:15px;font-weight:bold;margin-right:10px;margin-bottom:8px;">⭐ Upgrade Household</a>'
        f'<a href="{add_member_link}" style="display:inline-block;background:#f0fdf4;color:#166534;border:1px solid #bbf7d0;padding:12px 20px;border-radius:8px;text-decoration:none;font-size:14px;font-weight:600;margin-bottom:8px;">👥 Add Members</a>'
        f'</div>'
    )
    html_sections.append(action_buttons)

    text_body = f"Hi {user_name},\n\n" + "\n\n---\n\n".join(text_sections) + f"\n\nUpgrade Household: {upgrade_link}\nAdd Members: {add_member_link}\n\n— The ListMate Team"
    html_body = f'<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;max-width:520px;margin:0 auto;padding:24px 20px;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;"><p style="font-size:16px;color:#333;margin-top:0;">Hi {user_name},</p>' + "".join(html_sections) + "</div>"

    unsub_txt, unsub_html = _get_unsub_blocks(user_id, "marketing emails", "You received this email because you have an active household on ListMate.")
    payload = {
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "reply_to": {"email": FROM_EMAIL, "name": FROM_NAME},
        "personalizations": [{
            "to": [{"email": to_email}],
            "custom_args": {
                "user_id": str(user_id) if user_id else "",
                "household_id": str(household_id) if household_id else "",
                "campaign": campaign,
            },
        }],
        "categories": [campaign],
        "custom_args": {
            "user_id": str(user_id) if user_id else "",
            "household_id": str(household_id) if household_id else "",
            "campaign": campaign,
        },
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": text_body + unsub_txt},
            {"type": "text/html", "value": html_body + unsub_html},
        ],
        "tracking_settings": {
            "click_tracking": {"enable": True, "enable_text": False},
            "open_tracking": {"enable": True},
        },
    }
    return _send_via_api(api_key, payload)


def send_feedback_resolved_email(
    to_email: str,
    user_name: str,
    feedback_title: str,
    feedback_id: int,
    build_number: str,
    resolution_note: str = "",
    request_url: str = "",
    user_id: int = 0,
    household_id: int = 0
) -> bool:
    """Send a celebratory notification to the user when their feedback/feature request has been addressed in a specific build."""
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        print("WARNING: SENDGRID_API_KEY not set — skipping email")
        return False

    campaign = "feedback_resolved"
    name_str = (user_name or "there").split(" ")[0].capitalize()
    clean_title = (feedback_title or "Your feedback").strip()
    build_label = f"Build #{build_number}" if build_number and not str(build_number).lower().startswith("build") else (build_number or "latest build")
    if not request_url:
        request_url = f"{BASE_URL}/open?url={quote(f'/requests/{feedback_id}')}"

    subject = f"Your ListMate feedback has been resolved in {build_label}! 🎉"

    res_note_txt = f"\n\nNote from our team:\n{resolution_note}" if resolution_note else ""
    res_note_html = f'<div style="background:#f8faf6;border-left:4px solid #5ebe7e;padding:12px 16px;margin:16px 0;border-radius:4px;"><strong style="color:#2c5a2c;display:block;margin-bottom:4px;">Note from the team:</strong><span style="color:#333;font-size:14px;line-height:1.5;">{resolution_note}</span></div>' if resolution_note else ""

    text_body = (
        f"Hi {name_str},\n\n"
        f"Great news! You previously gave us feedback:\n"
        f"\"{clean_title}\"\n\n"
        f"We're excited to let you know this has been addressed in {build_label}!"
        f"{res_note_txt}\n\n"
        f"You can view the resolution details and roadmap update here:\n"
        f"{request_url}\n\n"
        f"Thank you for helping us make ListMate better!\n\n"
        f"— The ListMate Team"
    )

    html_body = (
        f'<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;max-width:520px;margin:0 auto;padding:24px 20px;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;">'
        f'<div style="text-align:center;margin-bottom:20px;">'
        f'<span style="display:inline-block;background:#eaf8ef;color:#2c5a2c;font-size:12px;font-weight:700;padding:6px 14px;border-radius:20px;letter-spacing:0.5px;text-transform:uppercase;">🎉 You Asked, We Built It</span>'
        f'<h2 style="color:#2c5a2c;margin:12px 0 6px 0;font-size:22px;font-weight:700;">Addressed in {build_label}!</h2>'
        f'</div>'
        f'<p style="font-size:15px;color:#333;line-height:1.5;">Hi {name_str},</p>'
        f'<p style="font-size:15px;color:#333;line-height:1.5;">You previously shared feedback with us:</p>'
        f'<div style="background:#f1f5f9;border-radius:8px;padding:12px 16px;margin:12px 0;font-style:italic;color:#475569;font-size:14px;line-height:1.4;">'
        f'"{clean_title}"'
        f'</div>'
        f'<p style="font-size:15px;color:#333;line-height:1.5;">We wanted to close the loop and let you know that your suggestion has officially shipped in <strong>{build_label}</strong>.</p>'
        f'{res_note_html}'
        f'<div style="text-align:center;margin:28px 0 20px 0;">'
        f'<a href="{request_url}" style="background:#5ebe7e;color:#ffffff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:15px;font-weight:700;display:inline-block;box-shadow:0 2px 6px rgba(94,190,126,0.3);">View Resolution & Details →</a>'
        f'</div>'
        f'<div style="text-align:center;margin-top:16px;">'
        f'<a href="{BASE_URL}/open?url=/" style="color:#5ebe7e;text-decoration:none;font-size:13px;font-weight:600;">Open ListMate App</a>'
        f'</div>'
        f'<hr style="border:none;border-top:1px solid #edf2f7;margin:24px 0 16px 0;">'
        f'<p style="font-size:12px;color:#94a3b8;text-align:center;margin:0;">Thank you for being part of the ListMate community and helping us improve.</p>'
        f'</div>'
    )

    unsub_txt, unsub_html = _get_unsub_blocks(user_id, "feedback updates", "You received this email because you submitted feedback or a feature request on ListMate.")

    payload = {
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "reply_to": {"email": FROM_EMAIL, "name": FROM_NAME},
        "personalizations": [{
            "to": [{"email": to_email}],
            "custom_args": {
                "user_id": str(user_id) if user_id else "",
                "household_id": str(household_id) if household_id else "",
                "campaign": campaign,
                "feedback_id": str(feedback_id),
            },
        }],
        "categories": [campaign],
        "custom_args": {
            "user_id": str(user_id) if user_id else "",
            "household_id": str(household_id) if household_id else "",
            "campaign": campaign,
            "feedback_id": str(feedback_id),
        },
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": text_body + unsub_txt},
            {"type": "text/html", "value": html_body + unsub_html},
        ],
        "tracking_settings": {
            "click_tracking": {"enable": True, "enable_text": False},
            "open_tracking": {"enable": True},
        },
    }
    return _send_via_api(api_key, payload)

