#!/usr/bin/env python3
"""
One-Time Winback Campaign: Send complimentary trial extension offers to expired households.

Usage:
  python3 scripts/send_expired_trial_winback.py --dry-run
  python3 scripts/send_expired_trial_winback.py --send [--limit 50]
"""

import os
import sys
import argparse
import datetime
from urllib.parse import quote

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.auth import _run, _one, _calc_days_left
from email_helper import (
    BASE_URL,
    FROM_EMAIL,
    FROM_NAME,
    _get_unsub_blocks,
    _send_via_api,
)

def send_winback_extension_email(to_email: str, user_name: str, household_name: str, tier: str = "15d", user_id: int = 0, household_id: int = 0) -> bool:
    """Send one-time winback trial extension email."""
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        print("WARNING: SENDGRID_API_KEY not set — skipping email")
        return False

    campaign = "trial_winback_extension"
    ext_days = 7 if tier == "7d" else 15
    claim_link = f"{BASE_URL}/open?url={quote(f'/settings?action=claim-extension&tier={tier}&source=email_winback_ext')}"
    upgrade_link = f"{BASE_URL}/open?url={quote('/settings?action=upgrade&source=email_winback_ext')}"
    app_store_img = "https://cdn.jsdelivr.net/gh/santven/listmate@main/static/app_store_badge.png"
    google_play_img = "https://cdn.jsdelivr.net/gh/santven/listmate@main/static/google_play_badge.png"
    ios_link = "https://apps.apple.com/us/app/grocerlistmate/id6795402710"
    android_link = "https://play.google.com/store/apps/details?id=com.pvkslabs.listmate&pcampaignid=web_share"

    subject = f"We miss you on ListMate! Here's {ext_days} free days of Premium 🎁"
    safe_name = (user_name or "").strip() or "there"
    safe_hh = (household_name or "").strip() or "your household"

    unsub_txt, unsub_html = _get_unsub_blocks(user_id, "promotional updates", "You received this email because you registered a ListMate household.")

    plain_text = (
        f"Hi {safe_name},

"
        f"We noticed your free trial on ListMate ended a while back. Life gets busy, and grocery schedules change—so we'd love to invite you and {safe_hh} back with a fresh {ext_days}-day complimentary Premium pass!

"
        f"No credit card required. Tap the link below to instantly unlock all features:
"
        f"- Real-time list sync across everyone in your home
"
        f"- Automatic aisle sorting for faster shopping runs
"
        f"- Unlimited custom store lists (Trader Joe's, Costco, Safeway, etc.)

"
        f"Claim Your {ext_days}-Day Free Pass: {claim_link}

"
        f"Or upgrade to our Annual Plan for .99/year (just sh.83/month):
{upgrade_link}

"
        f"Warm regards,
The ListMate Team" + unsub_txt
    )

    html_content = (
        f'<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:520px;margin:0 auto;padding:24px 20px;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;">'
        f'<h2 style="color:#2c5a2c;margin-top:0;">🎁 A Fresh Start for Your Grocery List</h2>'
        f'<p style="font-size:16px;color:#333;">Hi {safe_name},</p>'
        f'<p style="font-size:15px;color:#333;line-height:1.5;">We noticed your free trial on ListMate wrapped up. Life gets busy, and routines change—so we'd love to invite you and <strong>{safe_hh}</strong> back with a fresh <strong>{ext_days}-day complimentary Premium pass</strong>!</p>'
        f'<div style="background:#f0fdf4;border:1px solid #bbf7d0;padding:14px 16px;margin:16px 0;border-radius:8px;">'
        f'<strong style="color:#166534;display:block;margin-bottom:6px;">✨ What's unlocked for {ext_days} days on us:</strong>'
        f'<ul style="margin:0;padding-left:20px;color:#274c36;font-size:14px;line-height:1.6;">'
        f'<li>Instant real-time sync across your entire household</li>'
        f'<li>Smart aisle sorting to eliminate store backtracking</li>'
        f'<li>Unlimited custom stores (Costco, Trader Joe's, Safeway, etc.)</li>'
        f'</ul>'
        f'</div>'
        f'<div style="margin:24px 0 16px;">'
        f'<a href="{claim_link}" style="display:inline-block;background:#5ebe7e;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-size:15px;font-weight:bold;margin-right:10px;margin-bottom:8px;">Claim {ext_days} Days of Premium Free &rarr;</a>'
        f'<a href="{upgrade_link}" style="display:inline-block;background:#f8fafc;color:#1e293b;border:1px solid #cbd5e1;padding:12px 18px;border-radius:8px;text-decoration:none;font-size:14px;font-weight:600;margin-bottom:8px;">Upgrade for .99/yr (Save 58%)</a>'
        f'</div>'
        f'<div style="text-align:center;margin:24px 0 10px 0;">'
        f'<a href="{ios_link}" target="_blank" rel="noopener noreferrer" style="display:inline-block;margin:0 6px;"><img src="{app_store_img}" alt="App Store" width="125" height="38" border="0" style="height:38px;width:auto;border-radius:6px;"></a>'
        f'<a href="{android_link}" target="_blank" rel="noopener noreferrer" style="display:inline-block;margin:0 6px;"><img src="{google_play_img}" alt="Google Play" width="125" height="38" border="0" style="height:38px;width:auto;border-radius:6px;"></a>'
        f'</div>'
        f'<p style="font-size:14px;color:#64748b;margin-top:20px;line-height:1.5;">Warm regards,<br><strong style="color:#334155;">The ListMate Team</strong></p>'
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
            {"type": "text/html", "value": html_content},
        ],
        "tracking_settings": {
            "click_tracking": {"enable": True, "enable_text": False},
            "open_tracking": {"enable": True},
        },
    }
    return _send_via_api(api_key, payload)

def run_winback(dry_run: bool = True, limit: int = None):
    print("=== Starting Expired Households Trial Winback Campaign ===")
    print(f"Mode: {'DRY RUN (No emails dispatched)' if dry_run else 'LIVE DISPATCH'}")

    query = """
    SELECT DISTINCT ON (h.id)
        h.id as household_id,
        h.name as household_name,
        u.id as user_id,
        u.email,
        u.name as user_name,
        h.trial_ends_at,
        h.trial_ext_15d_claimed_at,
        h.trial_extension_claimed_at,
        h.trial_ext_7d_claimed_at
    FROM auth_households h
    JOIN auth_users u ON u.id = COALESCE(
        h.owner_id,
        (SELECT ahm2.user_id FROM auth_household_members ahm2 WHERE ahm2.household_id = h.id ORDER BY (CASE WHEN ahm2.role = 'owner' THEN 0 ELSE 1 END), ahm2.joined_at ASC LIMIT 1),
        (SELECT u2.id FROM auth_users u2 WHERE u2.household_id = h.id ORDER BY u2.id ASC LIMIT 1)
    )
    LEFT JOIN auth_household_members ahm ON ahm.user_id = u.id AND ahm.household_id = h.id
    WHERE h.is_premium = FALSE
      AND h.subscription_status != 'active'
      AND (
          h.trial_ends_at IS NOT NULL AND h.trial_ends_at < NOW()
          OR h.subscription_status IN ('expired', 'free')
      )
      AND COALESCE(h.trial_ext_15d_claimed_at, h.trial_extension_claimed_at) IS NULL
      AND COALESCE(ahm.marketing_opt_in, TRUE) = TRUE
      AND NOT EXISTS (
          SELECT 1 FROM email_suppressions es WHERE LOWER(es.email) = LOWER(u.email)
      )
      AND NOT EXISTS (
          SELECT 1 FROM email_events ee 
          WHERE (ee.household_id = h.id OR ee.email = u.email)
            AND ee.campaign = 'trial_winback_extension'
            AND ee.event_type = 'sent'
      )
      AND COALESCE(h.lifecycle_status, 'active') NOT IN ('sunsetted', 'sunset_pending')
    ORDER BY h.id, u.id ASC
    """

    rows = _run(query)
    print(f"Found {len(rows)} eligible expired household(s) for winback offer.")

    if limit and limit > 0:
        rows = rows[:limit]
        print(f"Capped to {limit} household(s) by limit flag.")

    dispatched = 0
    for r in rows:
        email = r.get("email")
        user_name = r.get("user_name") or ""
        hh_name = r.get("household_name") or "your household"
        uid = r.get("user_id")
        hhid = r.get("household_id")

        print(f"  [{hhid}] {email} ({user_name} / {hh_name})")
        if not dry_run:
            sent = send_winback_extension_email(email, user_name, hh_name, tier="15d", user_id=uid, household_id=hhid)
            if sent:
                _run("""
                    INSERT INTO email_events (email, event_type, campaign, user_id, household_id, event_timestamp, created_at)
                    VALUES (%s, 'sent', 'trial_winback_extension', %s, %s, NOW(), NOW())
                """, (email, uid, hhid))
                dispatched += 1
        else:
            dispatched += 1

    print(f"=== Winback Campaign Finished: {dispatched} household(s) processed ===")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="One-time expired household trial extension winback")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Dry run mode (default)")
    parser.add_argument("--send", action="store_true", help="Execute live dispatch")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of recipients")
    args = parser.parse_args()

    is_dry_run = not args.send
    run_winback(dry_run=is_dry_run, limit=args.limit)
