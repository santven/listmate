#!/usr/bin/env python3
"""
scripts/send_collaborator_trial_milestone_email.py

Sends a personalized, data-backed conversion email to active collaborator Balasubramaniam G
(Household #66: 'lakshmi's List') celebrating their 1-month milestone, highlighting their
household achievements (16 items planned, 1 store visit), explaining that their household
Pro trial wraps up tomorrow (October 22), showcasing Still Good & Nourish, and providing
a single-tap household upgrade CTA.

Features:
- Responsive, branded HTML email template matching ListMate corporate design guidelines
- SendGrid REST API integration with open/click tracking
- Full logging to `email_events` table (user_id=95, household_id=66, campaign='collaborator_trial_milestone')
- Defense-in-depth suppression checks
- HTML preview generator (--preview)
- Dry-run mode (--dry-run)
- Send mode (--send)
"""

import os
import sys
import argparse
import datetime
from urllib.parse import quote

# Add repository root to path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Ensure DATABASE_URL is initialized from environment or .env before any db/auth imports
if not os.environ.get("DATABASE_URL") and not os.environ.get("PROD_DATABASE_URL"):
    env_path = "/Users/venkatsanthanam/antigravity/ListMate-PR-&-Architecture-Assistant/.env"
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("PROD_DB_URL="):
                    val = line.strip().split("=", 1)[1].strip("\"'")
                    os.environ["DATABASE_URL"] = val
                    os.environ["PROD_DATABASE_URL"] = val
                    break

from email_helper import (
    _send_via_api,
    _get_unsub_blocks,
    is_email_suppressed_db,
    FROM_EMAIL,
    FROM_NAME,
    BASE_URL,
)

CAMPAIGN_NAME = "collaborator_trial_milestone"
REPLY_TO_EMAIL = "venragh@gmail.com"
REPLY_TO_NAME = "The ListMate Team"

TARGET_EMAIL = "balasubramaniam.g@gmail.com"
TARGET_USER_NAME = "Balasubramaniam G"
TARGET_USER_ID = 95
TARGET_HOUSEHOLD_ID = 66
TARGET_HOUSEHOLD_NAME = "lakshmi's List"
MEMBER_SINCE_STR = "September 22, 2026"
ITEMS_ORGANIZED_COUNT = 16
STORE_VISITS_COUNT = 1
TRIAL_EXPIRES_STR = "Tomorrow, October 22 at 8:00 AM"


def get_db_connection():
    """Connect to production database using PROD_DB_URL or DATABASE_URL."""
    import psycopg2
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("PROD_DATABASE_URL")
    if not db_url:
        env_path = "/Users/venkatsanthanam/antigravity/ListMate-PR-&-Architecture-Assistant/.env"
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("PROD_DB_URL="):
                        db_url = line.strip().split("=", 1)[1].strip("\"'")
                        break
    if not db_url:
        raise ValueError("No database URL found in environment or .env file.")
    return psycopg2.connect(db_url)


def generate_email_content():
    """Generate (subject, plain_text, html_body) for the collaborator trial milestone email."""
    first_name = TARGET_USER_NAME.split()[0]
    subject = "Your month with ListMate (+ your trial update) 🛒"
    upgrade_url = f"{BASE_URL}/open?url={quote('/?modal=upgrade&source=email_collaborator_trial')}"
    still_good_url = f"{BASE_URL}/open?url={quote('/?screen=fridge&source=email_collaborator_trial')}"
    nourish_url = f"{BASE_URL}/open?url={quote('/?screen=nourish&source=email_collaborator_trial')}"

    unsub_desc = "You received this email because you are an active member of a household on ListMate."
    unsub_txt, unsub_html = _get_unsub_blocks(
        TARGET_USER_ID,
        "subscription updates and household milestones",
        unsub_desc,
    )

    # Plain text version
    plain_text = f"""Hi {first_name},

You have been actively collaborating on ListMate with {TARGET_HOUSEHOLD_NAME} since {MEMBER_SINCE_STR}!

Over the past month, your household has built an incredible shared kitchen routine:
• {MEMBER_SINCE_STR} — Collaborating together for 1 full month
• {ITEMS_ORGANIZED_COUNT} items planned and organized across your lists
• {STORE_VISITS_COUNT} store trip completed seamlessly

Your household is taking full advantage of what ListMate has to offer. Your 30-day Pro trial wraps up {TRIAL_EXPIRES_STR}.

To make sure your lists continue syncing in real-time without interruption, we would love to invite you to keep ListMate Pro active for your household.

==================================================
✨ WHAT'S NEW IN LISTMATE: 2 NEW FLAGSHIP EXPERIENCES
==================================================

1. 🍲 Still Good (Zero Food Waste)
Track perishables, fridge leftovers, and freezer meals with intelligent shelf-life countdowns. Save an estimated $1,200/year per household by eating food before it spoils.

2. 🥗 Nourish (Stress-Free Household Nutrition)
Describe what you ate in everyday conversational English ("2 dosas with paneer bhurji & chutney"). Our culinary AI estimates portions and macros in seconds, with 1-tap shared family meals and leftover logging straight from Still Good.

==================================================
⭐ SIMPLE, TRANSPARENT HOUSEHOLD PRICING
==================================================
A single ListMate Pro subscription covers EVERYONE in your household for just $9.99/year (less than $1/month) or $1.99/month. Invited members never pay.

Keep Household Pro Active:
{upgrade_url}

Thank you for being part of the ListMate community, and please reply directly to this note if you have any questions or ideas!

Warm regards,
The ListMate Team
ListMate ({BASE_URL})

{unsub_txt}
"""

    # Responsive HTML version
    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
</head>
<body style="margin:0;padding:0;background-color:#f4f6f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1e293b;-webkit-font-smoothing:antialiased;line-height:1.6;">

  <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color:#f4f6f8;padding:32px 12px;">
    <tr>
      <td align="center">

        <!-- Main Card Container -->
        <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width:620px;background-color:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.06);border:1px solid #e2e8f0;">
          
          <!-- Header Banner -->
          <tr>
            <td style="background:linear-gradient(135deg, #047857 0%, #10b981 100%);padding:36px 32px 30px;text-align:center;color:#ffffff;">
              <div style="display:inline-block;background:rgba(255,255,255,0.22);border-radius:20px;padding:4px 14px;font-size:11.5px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#f0fdf4;margin-bottom:12px;">
                🎉 1-MONTH MILESTONE • PRO TRIAL UPDATE
              </div>
              <h1 style="margin:0;font-size:25px;font-weight:800;letter-spacing:-0.5px;line-height:1.25;color:#ffffff;">
                Your First Month with ListMate
              </h1>
              <p style="margin:8px 0 0;font-size:15px;color:#d1fae5;font-weight:500;">
                Celebrating your household's shared kitchen and shopping routine
              </p>
            </td>
          </tr>

          <!-- Main Body -->
          <tr>
            <td style="padding:32px 32px 24px;">

              <!-- Greeting & Context -->
              <p style="margin:0 0 16px;font-size:16px;color:#1e293b;font-weight:600;">
                Hi {first_name},
              </p>
              <p style="margin:0 0 18px;font-size:15px;color:#334155;line-height:1.65;">
                You've been collaborating on ListMate with <strong>{TARGET_HOUSEHOLD_NAME}</strong> since <strong>{MEMBER_SINCE_STR}</strong>! Over the past month, your household has been an active, engaged part of our community:
              </p>

              <!-- Milestone Metric Cards -->
              <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-bottom:24px;">
                <tr>
                  <td style="padding:14px 16px;background:#f8fafc;border:1px solid #e2e8f0;border-left:4px solid #10b981;border-radius:10px;margin-bottom:8px;display:block;">
                    <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0">
                      <tr>
                        <td width="36" style="font-size:22px;vertical-align:top;line-height:1;">📅</td>
                        <td>
                          <div style="font-size:14px;font-weight:700;color:#0f172a;">Member Since {MEMBER_SINCE_STR}</div>
                          <div style="font-size:13px;color:#64748b;margin-top:2px;">1 full month of real-time household collaboration and sync.</div>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td style="padding:14px 16px;background:#f8fafc;border:1px solid #e2e8f0;border-left:4px solid #059669;border-radius:10px;margin-bottom:8px;display:block;">
                    <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0">
                      <tr>
                        <td width="36" style="font-size:22px;vertical-align:top;line-height:1;">🛒</td>
                        <td>
                          <div style="font-size:14px;font-weight:700;color:#0f172a;">{ITEMS_ORGANIZED_COUNT} Items Planned &amp; Organized</div>
                          <div style="font-size:13px;color:#64748b;margin-top:2px;">Shared grocery items categorized by store aisle for effortless shopping.</div>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td style="padding:14px 16px;background:#f8fafc;border:1px solid #e2e8f0;border-left:4px solid #2563eb;border-radius:10px;display:block;">
                    <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0">
                      <tr>
                        <td width="36" style="font-size:22px;vertical-align:top;line-height:1;">🏪</td>
                        <td>
                          <div style="font-size:14px;font-weight:700;color:#0f172a;">{STORE_VISITS_COUNT} Shopping Trip Completed</div>
                          <div style="font-size:13px;color:#64748b;margin-top:2px;">Checked off in real-time so your household never bought duplicates.</div>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- Trial Expiration Notice & Household Pricing -->
              <div style="background:#fefce8;border:1px solid #fef08a;border-radius:12px;padding:20px;text-align:center;margin-bottom:28px;">
                <div style="display:inline-block;background:#fef08a;color:#854d0e;font-size:11px;font-weight:800;letter-spacing:1px;text-transform:uppercase;padding:3px 10px;border-radius:12px;margin-bottom:8px;">
                  ⏳ Trial Wraps Up {TRIAL_EXPIRES_STR}
                </div>
                <div style="font-size:16px;font-weight:800;color:#713f12;margin-bottom:6px;">
                  Keep Your Entire Household Synced
                </div>
                <p style="margin:0 0 16px;font-size:14px;color:#854d0e;line-height:1.55;max-width:480px;margin-left:auto;margin-right:auto;">
                  Your household's 30-day Pro trial expires tomorrow. A single ListMate Pro plan covers <strong>everyone in your household</strong> for just <strong>$9.99/year</strong> (less than $1/month) or $1.99/month. All members continue collaborating and syncing with zero extra fees.
                </p>
                <div>
                  <a href="{upgrade_url}" target="_blank" rel="noopener noreferrer" style="background:linear-gradient(135deg, #059669 0%, #10b981 100%);color:#ffffff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:15px;font-weight:700;display:inline-block;box-shadow:0 3px 12px rgba(16,185,129,0.35);">
                    Keep Household Pro Active ➔
                  </a>
                </div>
                <div style="font-size:12px;color:#a16207;margin-top:8px;">
                  Tap to upgrade directly in ListMate • Instant activation for all members
                </div>
              </div>

              <!-- Flagship Features Showcase -->
              <div style="margin-bottom:28px;">
                <div style="text-align:center;margin-bottom:16px;">
                  <span style="font-size:11px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#059669;">
                    ✨ Complete Kitchen Companion
                  </span>
                  <h3 style="margin:4px 0 0;font-size:18px;font-weight:800;color:#0f172a;">
                    Two Raving New Features in ListMate
                  </h3>
                  <p style="margin:4px 0 0;font-size:13px;color:#64748b;">
                    Included at no extra charge in your household's Pro membership
                  </p>
                </div>

                <!-- Still Good Card -->
                <div style="background:#ffffff;border:1px solid #e2e8f0;border-left:4px solid #059669;border-radius:12px;padding:16px;margin-bottom:12px;box-shadow:0 2px 6px rgba(0,0,0,0.03);">
                  <div style="font-size:15px;font-weight:700;color:#065f46;margin-bottom:4px;">
                    🍲 1. Still Good (Stop Fridge &amp; Freezer Food Waste)
                  </div>
                  <div style="font-size:13.5px;color:#475569;line-height:1.55;">
                    Track perishables, fridge leftovers, and freezer meals with intelligent shelf-life countdowns. Save an estimated $1,200/year per household by eating food before it spoils.
                  </div>
                </div>

                <!-- Nourish Card -->
                <div style="background:#ffffff;border:1px solid #e2e8f0;border-left:4px solid #10b981;border-radius:12px;padding:16px;box-shadow:0 2px 6px rgba(0,0,0,0.03);">
                  <div style="font-size:15px;font-weight:700;color:#047857;margin-bottom:4px;">
                    🥗 2. Nourish (Stress-Free Household Nutrition)
                  </div>
                  <div style="font-size:13.5px;color:#475569;line-height:1.55;">
                    Describe what you ate in everyday plain English (<em>"2 dosas with paneer bhurji &amp; chutney"</em>). Culinary AI deconstructs portions and macros in seconds, with 1-tap shared family meals and leftover logging straight from Still Good.
                  </div>
                </div>
              </div>

              <!-- Secondary CTA Box -->
              <div style="text-align:center;padding:16px;background:#f8fafc;border-radius:12px;border:1px solid #e2e8f0;">
                <p style="margin:0 0 12px;font-size:14px;color:#475569;">
                  Ready to keep collaborating with {TARGET_HOUSEHOLD_NAME}?
                </p>
                <a href="{upgrade_url}" target="_blank" rel="noopener noreferrer" style="background:#0f172a;color:#ffffff;padding:12px 24px;border-radius:8px;text-decoration:none;font-size:14px;font-weight:700;display:inline-block;">
                  Upgrade Household for $9.99/Year ➔
                </a>
              </div>

              <!-- Sign-off -->
              <div style="margin-top:28px;font-size:14px;color:#475569;line-height:1.6;">
                Thank you for being part of the ListMate community, and please feel free to reply directly to this email with any feedback or questions!
                <br><br>
                Warm regards,<br>
                <strong style="color:#0f172a;">The ListMate Team</strong>
              </div>

            </td>
          </tr>

        </table>
        <!-- End Card -->

        {unsub_html}

      </td>
    </tr>
  </table>

</body>
</html>
"""
    return subject, plain_text, html_body


def log_email_event(email, target_url):
    """Inserts a record into email_events table."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO email_events (
                    email, event_type, campaign, user_id, household_id, target_url, event_timestamp, created_at
                ) VALUES (%s, 'sent', %s, %s, %s, %s, NOW(), NOW())
                """,
                (email, CAMPAIGN_NAME, TARGET_USER_ID, TARGET_HOUSEHOLD_ID, target_url),
            )
        conn.commit()
        print(f"[LOGGED] Recorded '{CAMPAIGN_NAME}' event in email_events table for {email}")
    finally:
        conn.close()


def send_email(api_key: str, dry_run: bool = False, force: bool = False, test_email: str = "") -> bool:
    """Dispatches the email and logs event in database."""
    recipient_email = (test_email or TARGET_EMAIL).strip()
    is_test = bool(test_email)

    print("==========================================================")
    print(" Dispatching Collaborator Trial Milestone Conversion Email" + (" [TEST MODE]" if is_test else ""))
    print("==========================================================")
    print(f" Recipient : {recipient_email} " + (f"(Simulating User #{TARGET_USER_ID}: {TARGET_USER_NAME})" if is_test else f"<{TARGET_EMAIL}> (User #{TARGET_USER_ID})"))
    print(f" Household : {TARGET_HOUSEHOLD_NAME} (HH #{TARGET_HOUSEHOLD_ID})")
    print(f" Campaign  : {CAMPAIGN_NAME}")
    print(f" Dry Run   : {dry_run}")
    print("----------------------------------------------------------")

    # Suppression check
    if not is_test and is_email_suppressed_db(TARGET_EMAIL):
        print(f"ABORT: {TARGET_EMAIL} is in email_suppressions table. Cannot send.")
        return False

    # Check if already sent
    if not is_test and not force:
        try:
            conn = get_db_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id FROM email_events 
                    WHERE campaign = %s AND email = %s AND event_type = 'sent'
                    LIMIT 1
                    """,
                    (CAMPAIGN_NAME, TARGET_EMAIL),
                )
                existing = cur.fetchone()
            conn.close()
            if existing:
                print(f"[ALREADY SENT] {TARGET_EMAIL} has already received campaign '{CAMPAIGN_NAME}' (event ID: {existing[0]}). Use --force to override.")
                return False
        except Exception as e:
            print(f"[WARNING] Could not check existing email_events: {e}")

    subject, plain_text, html_body = generate_email_content()
    if is_test:
        subject = f"[TEST] {subject}"
    upgrade_url = f"{BASE_URL}/open?url={quote('/?modal=upgrade&source=email_collaborator_trial')}"

    if dry_run:
        print("[DRY RUN SUCCESS] Email content generated successfully.")
        print(f"Recipient: {recipient_email}")
        print(f"Subject: {subject}")
        print("Would send via SendGrid" + (" (skipping email_events in test mode)." if is_test else " and record in email_events."))
        return True

    sendgrid_key = api_key or os.environ.get("SENDGRID_API_KEY", "")
    if not sendgrid_key:
        print("ERROR: SENDGRID_API_KEY not configured. Please supply via --api-key or SENDGRID_API_KEY env var.")
        return False

    payload = {
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "reply_to": {"email": REPLY_TO_EMAIL, "name": REPLY_TO_NAME},
        "personalizations": [
            {
                "to": [{"email": recipient_email}],
                "custom_args": {
                    "user_id": str(TARGET_USER_ID),
                    "household_id": str(TARGET_HOUSEHOLD_ID),
                    "campaign": CAMPAIGN_NAME,
                    "is_test": str(is_test),
                },
            }
        ],
        "categories": [CAMPAIGN_NAME, "collaborator_conversion"],
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

    print(f"Sending via SendGrid REST API to {recipient_email}...")
    success = _send_via_api(sendgrid_key, payload)

    if success:
        print(f"[SUCCESS] Email successfully delivered to {recipient_email} via SendGrid!")
        if not is_test:
            try:
                log_email_event(TARGET_EMAIL, upgrade_url)
            except Exception as e:
                print(f"[ERROR] Could not log to email_events: {e}")
        else:
            print("[TEST MODE] Skipped recording in production email_events table.")
        return True
    else:
        print(f"[FAILURE] SendGrid rejected or failed dispatch to {recipient_email}.")
        return False


def main():
    parser = argparse.ArgumentParser(description="Send Collaborator Trial Milestone Email")
    parser.add_argument("--preview", action="store_true", help="Generate and save HTML preview file")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending")
    parser.add_argument("--send", action="store_true", help="Send real email to Balasubramaniam G")
    parser.add_argument("--test-email", type=str, default="", help="Send test email to your own address")
    parser.add_argument("--api-key", type=str, default="", help="SendGrid API key")
    parser.add_argument("--force", action="store_true", help="Bypass idempotency check")

    args = parser.parse_args()

    if args.preview:
        subject, _, html_body = generate_email_content()
        preview_path = os.path.join(REPO_ROOT, "static", "preview_collaborator_milestone.html")
        with open(preview_path, "w", encoding="utf-8") as f:
            f.write(html_body)
        print(f"Preview saved to: {preview_path}")
        return

    if not args.send and not args.dry_run and not args.test_email:
        print("Please specify either --dry-run, --preview, --test-email <addr>, or --send.")
        return

    send_email(
        api_key=args.api_key,
        dry_run=args.dry_run,
        force=args.force,
        test_email=args.test_email,
    )


if __name__ == "__main__":
    main()
