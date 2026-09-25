#!/usr/bin/env python3
"""
One-Time Winback Campaign: Send complimentary trial extension offers to expired households.

Usage:
  python3 scripts/send_expired_trial_winback.py --dry-run
  python3 scripts/send_expired_trial_winback.py --send --limit 50
  python3 scripts/send_expired_trial_winback.py --send

Guardrails:
- Checks email_suppressions and unsubscribe status
- Idempotent: Tracks 'trial_winback_extension' event in email_events to prevent duplicate sends
- Defaults to 15-day extension offer (or 7-day if 15d was already claimed)
"""

import os
import sys
import argparse
import datetime
from urllib.parse import quote

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db_pg
from email_helper import _send_via_api, _get_unsub_blocks, FROM_EMAIL, FROM_NAME

BASE_URL = os.environ.get("APP_URL", "https://grocerlist.app").rstrip("/")

def send_winback_email(
    to_email: str,
    user_name: str,
    household_name: str,
    user_id: int,
    household_id: int,
    extension_tier: str = "15d",
    dry_run: bool = True
) -> bool:
    """Sends the winback email offering a 15-day (or 7-day) extension pass."""
    ext_days = 7 if str(extension_tier).strip().lower() in ('7', '7d') else 15
    tier_slug = '7d' if ext_days == 7 else '15d'
    extension_link = f"{BASE_URL}/open?url={quote(f'/settings?action=claim-extension&tier={tier_slug}&source=email_winback')}"
    upgrade_link = f"{BASE_URL}/open?url={quote('/settings?action=upgrade&source=email_winback')}"

    safe_name = user_name or "there"
    safe_hh = household_name or "your household"
    campaign = f"trial_winback_ext_{tier_slug}"
    subject = f"A gift for {safe_hh}: Come back to ListMate with {ext_days} days free! 🎁"

    unsub_txt, unsub_html = _get_unsub_blocks(
        user_id,
        "product updates and promotions",
        "You received this email because you created a ListMate household."
    )

    plain_body = (
        f"Hi {safe_name},\n\n"
        f"We noticed it's been a while since your ListMate trial ended. We've added several updates to make shared grocery shopping and pantry tracking faster, smoother, and completely hassle-free.\n\n"
        f"We'd love to invite you and {safe_hh} back with a complimentary {ext_days}-Day Premium Pass—completely on us, no credit card required!\n\n"
        f"Claim Your {ext_days}-Day Free Pass:\n{extension_link}\n\n"
        f"Or upgrade directly for $9.99/year or $1.99/month:\n{upgrade_link}\n\n"
        f"— The ListMate Team" + unsub_txt
    )

    html_body = (
        f'<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;max-width:520px;margin:0 auto;padding:24px 20px;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;">'
        f'<h2 style="color:#2c5a2c;margin-top:0;">🎁 We Miss You at ListMate!</h2>'
        f'<p style="font-size:16px;color:#333;">Hi {safe_name},</p>'
        f'<p style="font-size:15px;color:#333;line-height:1.5;">We noticed it\'s been a while since your free trial ended. We\'d love to welcome you and <strong>{safe_hh}</strong> back to stress-free grocery planning.</p>'
        f'<p style="font-size:15px;color:#333;line-height:1.5;">Enjoy a complimentary <strong>{ext_days}-Day Premium Pass</strong> with full access to shared lists, aisle categorization, and real-time syncing across all your devices.</p>'
        f'<div style="background:#f0fdf4;border:1px solid #bbf7d0;padding:14px 16px;margin:16px 0;border-radius:8px;">'
        f'<strong style="color:#166534;display:block;margin-bottom:6px;">✨ What\'s waiting for you:</strong>'
        f'<ul style="margin:0;padding-left:20px;color:#274c36;font-size:14px;line-height:1.6;">'
        f'<li>Instant real-time sync with all household members</li>'
        f'<li>Smart aisle sorting for fast grocery runs</li>'
        f'<li>Unlimited custom stores and recipe ingredient imports</li>'
        f'</ul>'
        f'</div>'
        f'<div style="margin:24px 0 16px;">'
        f'<a href="{extension_link}" style="display:inline-block;background:#5ebe7e;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-size:15px;font-weight:bold;margin-right:10px;margin-bottom:8px;">Claim {ext_days} Free Days</a>'
        f'<a href="{upgrade_link}" style="display:inline-block;background:#f8fafc;color:#1e293b;border:1px solid #cbd5e1;padding:12px 18px;border-radius:8px;text-decoration:none;font-size:14px;font-weight:600;margin-bottom:8px;">Upgrade for $9.99/yr or $1.99/mo</a>'
        f'</div>'
        f'<p style="font-size:13px;color:#666;line-height:1.4;">Zero commitment. No credit card required. Clicking activates your pass instantly.</p>'
        f'</div>' + unsub_html
    )

    if dry_run:
        print(f"[DRY-RUN] Would send winback email to: {to_email} (User ID: {user_id}, Household: {household_id}, Tier: {tier_slug})")
        return True

    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        print("ERROR: SENDGRID_API_KEY not configured — cannot send email.")
        return False

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
        "categories": [campaign, "winback"],
        "custom_args": {
            "user_id": str(user_id) if user_id else "",
            "household_id": str(household_id) if household_id else "",
            "campaign": campaign,
        },
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": plain_body},
            {"type": "text/html", "value": html_body},
        ],
        "tracking_settings": {
            "click_tracking": {"enable": True, "enable_text": False},
            "open_tracking": {"enable": True},
        },
    }

    success = _send_via_api(api_key, payload)
    if success:
        try:
            u_id = int(user_id) if user_id is not None and str(user_id).isdigit() and int(user_id) != 0 else None
            hh_id = int(household_id) if household_id is not None and str(household_id).isdigit() and int(household_id) != 0 else None
            db_pg.execute_query(
                """
                INSERT INTO email_events (user_id, household_id, campaign, event_type, email, created_at)
                VALUES (%s, %s, %s, 'sent', %s, NOW())
                """,
                (u_id, hh_id, campaign, to_email)
            )
        except Exception as e:
            print(f"Warning: Failed to record email_event for {to_email}: {e}")
    return success

def run_winback(dry_run: bool = True, limit: int = None):
    print("=" * 60)
    print(f"Starting Expired Trial Winback Campaign (dry_run={dry_run}, limit={limit})")
    print("=" * 60)

    # 1. Fetch eligible expired households
    query = """
    SELECT DISTINCT ON (h.id)
        h.id as household_id,
        h.name as household_name,
        u.id as user_id,
        u.email,
        u.name as user_name,
        h.subscription_status,
        h.trial_ends_at,
        h.trial_extension_claimed_at,
        h.trial_ext_15d_claimed_at,
        h.trial_ext_7d_claimed_at
    FROM auth_households h
    JOIN auth_users u ON u.id = COALESCE(
        h.owner_id,
        (SELECT ahm2.user_id FROM auth_household_members ahm2 WHERE ahm2.household_id = h.id ORDER BY (CASE WHEN ahm2.role = 'owner' THEN 0 ELSE 1 END), ahm2.joined_at ASC LIMIT 1),
        (SELECT u2.id FROM auth_users u2 WHERE u2.household_id = h.id ORDER BY u2.id ASC LIMIT 1)
    )
    WHERE
        h.is_premium = FALSE
        AND (h.subscription_status IS NULL OR h.subscription_status NOT IN ('premium', 'active', 'lifetime'))
        AND h.trial_ends_at IS NOT NULL
        AND h.trial_ends_at < NOW()
        AND NOT EXISTS (
            SELECT 1 FROM email_suppressions es WHERE LOWER(es.email) = LOWER(u.email)
        )
        AND NOT EXISTS (
            SELECT 1 FROM email_events ee 
            WHERE ee.household_id = h.id 
              AND ee.campaign LIKE 'trial_winback_ext_%' 
              AND ee.event_type = 'sent'
        )
    ORDER BY h.id, u.id ASC
    """

    rows = db_pg.execute_query(query)
    print(f"Found {len(rows)} expired household(s) eligible for winback campaign.")

    if limit and limit > 0:
        rows = rows[:limit]
        print(f"Limited run to {len(rows)} household(s).")

    sent_count = 0
    fail_count = 0

    for r in rows:
        email = r.get("email")
        if not email:
            continue

        c_15d = r.get("trial_ext_15d_claimed_at") or r.get("trial_extension_claimed_at")
        c_7d = r.get("trial_ext_7d_claimed_at")

        if not c_15d:
            tier = "15d"
        elif not c_7d:
            tier = "7d"
        else:
            # Both claimed, skip winback pass
            continue

        ok = send_winback_email(
            to_email=email,
            user_name=r.get("user_name") or "",
            household_name=r.get("household_name") or "",
            user_id=r.get("user_id") or 0,
            household_id=r.get("household_id") or 0,
            extension_tier=tier,
            dry_run=dry_run
        )

        if ok:
            sent_count += 1
        else:
            fail_count += 1

    print("=" * 60)
    print(f"Winback Campaign Complete: {sent_count} sent/simulated, {fail_count} failed.")
    print("=" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send winback emails to expired trial users")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Preview recipients without sending")
    parser.add_argument("--send", action="store_true", default=False, help="Actually send the emails via SendGrid")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of emails to send")
    args = parser.parse_args()

    is_dry = not args.send or args.dry_run
    run_winback(dry_run=is_dry, limit=args.limit)
