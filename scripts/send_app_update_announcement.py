#!/usr/bin/env python3
"""One-Time App Update Announcement: Notify active users of Version 1.0.1.

Usage:
  # 1. Preview the email template in the terminal or write to HTML file:
  python3 scripts/send_app_update_announcement.py --preview

  # 2. Send a test email to yourself for verification:
  python3 scripts/send_app_update_announcement.py --test-email venragh@gmail.com

  # 3. Dry-run to count eligible recipients, suppressed users, and already sent:
  python3 scripts/send_app_update_announcement.py --dry-run

  # 4. Instant dispatch to all eligible (unsuppressed) users:
  python3 scripts/send_app_update_announcement.py --send

Guardrails:
- Filters out all suppressed emails in `email_suppressions` (unsubscribes, bounces, spam reports).
- Defense-in-depth: checks `is_email_suppressed_db()` in `_send_via_api`.
- Idempotent: Logs `campaign = 'app_update_v1_0_1'` to `email_events` to ensure no user receives duplicate emails.
- Defensive typing: Coerces numeric IDs to avoid the 0 vs None falsiness trap.
"""

import os
import sys
import argparse
from urllib.parse import quote

# Add workspace root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from email_helper import (
    _send_via_api,
    _get_unsub_blocks,
    is_email_suppressed_db,
    FROM_EMAIL,
    FROM_NAME,
    BASE_URL,
)

CAMPAIGN_NAME = "app_update_v1_0_1"
APP_STORE_URL = "https://apps.apple.com/us/app/grocerlistmate/id6795402710"
PLAY_STORE_URL = "https://play.google.com/store/apps/details?id=com.pvkslabs.listmate"
WEB_APP_URL = os.environ.get("APP_URL", "https://grocerlist.app").rstrip("/")

APP_STORE_BADGE = "https://cdn.jsdelivr.net/gh/santven/listmate@main/static/app_store_badge.png"
PLAY_STORE_BADGE = "https://cdn.jsdelivr.net/gh/santven/listmate@main/static/google_play_badge.png"


def generate_email_content(user_name: str = "", user_id: int = 0, household_id: int = 0) -> tuple:
    """Generates (subject, plain_text, html_body) for the v1.0.1 release announcement."""
    safe_name = (user_name or "").strip()
    greeting = f"Hi {safe_name}," if safe_name else "Hi there,"

    subject = "✨ What's New in ListMate 1.0.1: Native Push Notifications, Smarter Grocery Sorting & More"

    unsub_txt, unsub_html = _get_unsub_blocks(
        user_id,
        "product updates and release announcements",
        "You received this email because you have a ListMate account.",
    )

    plain_text = (
        f"{greeting}\n\n"
        f"We're excited to let you know that ListMate Version 1.0.1 is now officially live on the Apple App Store, Google Play Store, and Web!\n\n"
        f"Here is what's new in this update:\n\n"
        f"• 🔔 Push Notification Support: Native background notifications to keep your household in sync as shared lists are updated.\n"
        f"• ⚡ Lightning-Fast Grocery Sorting: Upgraded search and self-learning categorization engine that organizes your items across aisles in milliseconds.\n"
        f"• 📲 Smooth In-App Updates: Instant, non-intrusive alerts when new improvements are ready so your app is always up to date.\n"
        f"• 🔋 Stability & Battery Optimization: Smoother navigation, lower memory footprint, and performance polish.\n\n"
        f"Get the latest update today:\n"
        f"- Apple App Store (iOS): {APP_STORE_URL}\n"
        f"- Google Play Store (Android): {PLAY_STORE_URL}\n"
        f"- Web App: {WEB_APP_URL}\n\n"
        f"Thank you for using ListMate to simplify your grocery shopping!\n\n"
        f"— The ListMate Team\n"
        f"{unsub_txt}"
    )

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ListMate 1.0.1 Update</title>
</head>
<body style="margin:0;padding:20px 10px;background-color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased;">
  <div style="max-width:540px;margin:0 auto;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e2e8f0;box-shadow:0 4px 6px -1px rgba(0,0,0,0.05);">
    
    <!-- Header with Brand Accent -->
    <div style="background:#5ebe7e;background:linear-gradient(135deg, #15803d 0%, #5ebe7e 100%);padding:28px 24px;text-align:center;">
      <div style="display:inline-block;background:rgba(255,255,255,0.2);padding:6px 14px;border-radius:20px;color:#ffffff;font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;margin-bottom:8px;">
        🚀 Version 1.0.1 Released
      </div>
      <h1 style="color:#ffffff;margin:0;font-size:24px;font-weight:800;letter-spacing:-0.5px;">
        ListMate Just Got Better
      </h1>
      <p style="color:rgba(255,255,255,0.9);margin:6px 0 0;font-size:14px;">
        Push notifications, smarter categorization, and speed enhancements
      </p>
    </div>

    <!-- Main Content Container -->
    <div style="padding:28px 24px;">
      <p style="font-size:16px;color:#1e293b;margin-top:0;margin-bottom:16px;font-weight:600;">
        {greeting}
      </p>
      <p style="font-size:15px;color:#475569;line-height:1.6;margin-top:0;margin-bottom:24px;">
        We're thrilled to share that <strong>ListMate Version 1.0.1</strong> is now live on the Apple App Store, Google Play Store, and Web. This release lays the foundation for real-time household collaboration and brings major performance improvements to your shopping experience.
      </p>

      <!-- Feature Highlights Card -->
      <div style="background-color:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:20px;margin-bottom:28px;">
        <div style="font-size:13px;font-weight:700;color:#166534;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:14px;">
          ✨ What's New in Version 1.0.1:
        </div>

        <!-- Feature Item 1 -->
        <table style="width:100%;margin-bottom:14px;border-collapse:collapse;">
          <tr>
            <td style="width:36px;vertical-align:top;font-size:22px;line-height:1;">🔔</td>
            <td style="vertical-align:top;">
              <strong style="color:#0f172a;font-size:14px;display:block;margin-bottom:2px;">Native Push Notifications</strong>
              <span style="color:#64748b;font-size:13px;line-height:1.5;display:block;">
                Full Apple APNs and Android FCM infrastructure to support instant household alerts when shared groceries change.
              </span>
            </td>
          </tr>
        </table>

        <!-- Feature Item 2 -->
        <table style="width:100%;margin-bottom:14px;border-collapse:collapse;">
          <tr>
            <td style="width:36px;vertical-align:top;font-size:22px;line-height:1;">⚡</td>
            <td style="vertical-align:top;">
              <strong style="color:#0f172a;font-size:14px;display:block;margin-bottom:2px;">Smarter, Faster Grocery Categorization</strong>
              <span style="color:#64748b;font-size:13px;line-height:1.5;display:block;">
                Self-learning item taxonomy with in-memory caching sorts your groceries into aisles in under 0.1ms without slowing down the app.
              </span>
            </td>
          </tr>
        </table>

        <!-- Feature Item 3 -->
        <table style="width:100%;margin-bottom:14px;border-collapse:collapse;">
          <tr>
            <td style="width:36px;vertical-align:top;font-size:22px;line-height:1;">📲</td>
            <td style="vertical-align:top;">
              <strong style="color:#0f172a;font-size:14px;display:block;margin-bottom:2px;">Seamless Update Alerts</strong>
              <span style="color:#64748b;font-size:13px;line-height:1.5;display:block;">
                Helpful in-app drawers notify you when store updates are available, so you and your household are always on the newest build.
              </span>
            </td>
          </tr>
        </table>

        <!-- Feature Item 4 -->
        <table style="width:100%;border-collapse:collapse;">
          <tr>
            <td style="width:36px;vertical-align:top;font-size:22px;line-height:1;">🔋</td>
            <td style="vertical-align:top;">
              <strong style="color:#0f172a;font-size:14px;display:block;margin-bottom:2px;">Performance & Battery Polish</strong>
              <span style="color:#64748b;font-size:13px;line-height:1.5;display:block;">
                Sub-500ms server response times, reduced memory usage, and defensive error-recovery prevent hiccups while shopping.
              </span>
            </td>
          </tr>
        </table>
      </div>

      <!-- Call to Action Section -->
      <div style="text-align:center;margin-bottom:24px;">
        <p style="font-size:14px;font-weight:600;color:#1e293b;margin-bottom:14px;">
          Update or download the latest release:
        </p>
        <div style="display:inline-block;margin:0 auto;">
          <a href="{APP_STORE_URL}" target="_blank" style="text-decoration:none;display:inline-block;margin:0 6px 10px 6px;">
            <img src="{APP_STORE_BADGE}" alt="Download on the App Store" style="height:42px;width:auto;border-radius:6px;border:0;">
          </a>
          <a href="{PLAY_STORE_URL}" target="_blank" style="text-decoration:none;display:inline-block;margin:0 6px 10px 6px;">
            <img src="{PLAY_STORE_BADGE}" alt="Get it on Google Play" style="height:42px;width:auto;border-radius:6px;border:0;">
          </a>
        </div>
        <div style="margin-top:8px;">
          <a href="{WEB_APP_URL}" target="_blank" style="font-size:13px;color:#166534;font-weight:600;text-decoration:underline;">
            Or open the Web App at grocerlist.app &rarr;
          </a>
        </div>
      </div>

      <p style="font-size:14px;color:#64748b;line-height:1.5;margin-bottom:0;text-align:center;">
        Have feedback or feature requests? Simply reply to this email—we read every message!
      </p>

    </div>

    <!-- Divider -->
    <div style="height:1px;background-color:#e2e8f0;margin:0;"></div>

    <!-- Footer with Unsubscribe -->
    <div style="padding:16px 24px;background-color:#fafafa;">
      {unsub_html}
    </div>

  </div>
</body>
</html>
"""

    return subject, plain_text, html_body


def send_update_email(
    to_email: str,
    user_name: str = "",
    user_id: int = 0,
    household_id: int = 0,
    dry_run: bool = True,
) -> bool:
    """Dispatches the v1.0.1 announcement email to a single recipient."""
    clean_email = (to_email or "").strip().lower()
    if not clean_email or "@" not in clean_email:
        return False

    if is_email_suppressed_db(clean_email):
        print(f"[Suppressed] Skipping {clean_email}: Present in email_suppressions")
        return False

    subject, plain_text, html_body = generate_email_content(
        user_name=user_name,
        user_id=user_id,
        household_id=household_id,
    )

    if dry_run:
        print(f"[DRY-RUN] Would send to: {clean_email} (User ID: {user_id}, Name: '{user_name}')")
        return True

    api_key = os.environ.get("SENDGRID_API_KEY", "")
    if not api_key:
        print("ERROR: SENDGRID_API_KEY environment variable is not set. Cannot dispatch email.")
        return False

    payload = {
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "reply_to": {"email": FROM_EMAIL, "name": FROM_NAME},
        "personalizations": [
            {
                "to": [{"email": clean_email}],
                "custom_args": {
                    "user_id": str(user_id) if user_id else "",
                    "household_id": str(household_id) if household_id else "",
                    "campaign": CAMPAIGN_NAME,
                },
            }
        ],
        "categories": [CAMPAIGN_NAME, "release_announcement"],
        "custom_args": {
            "user_id": str(user_id) if user_id else "",
            "household_id": str(household_id) if household_id else "",
            "campaign": CAMPAIGN_NAME,
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

    success = _send_via_api(api_key, payload)
    if success:
        try:
            import db_pg
            u_id = int(user_id) if user_id and str(user_id).isdigit() and int(user_id) != 0 else None
            hh_id = int(household_id) if household_id and str(household_id).isdigit() and int(household_id) != 0 else None
            db_pg.execute_query(
                """
                INSERT INTO email_events (user_id, household_id, campaign, event_type, email, created_at)
                VALUES (%s, %s, %s, 'sent', %s, NOW())
                """,
                (u_id, hh_id, CAMPAIGN_NAME, clean_email),
            )
            print(f"[Sent] Successfully delivered to {clean_email}")
        except Exception as e:
            print(f"[Warning] Email sent to {clean_email}, but recording email_event failed: {e}")
    else:
        print(f"[Failed] SendGrid returned error for {clean_email}")

    return success


def get_eligible_users() -> tuple:
    """Queries all users, identifying eligible recipients minus suppressions and prior campaign sends.

    Returns:
      (eligible_users, suppressed_count, already_sent_count)
    """
    import db_pg
    all_users = db_pg.execute_query(
        """
        SELECT id, email, name, household_id
        FROM auth_users
        WHERE email IS NOT NULL AND TRIM(email) != ''
        ORDER BY id ASC
        """
    )

    eligible = []
    suppressed_count = 0
    already_sent_count = 0

    # Query already sent emails for this campaign
    sent_rows = db_pg.execute_query(
        "SELECT LOWER(TRIM(email)) AS email FROM email_events WHERE campaign = %s AND event_type = 'sent'",
        (CAMPAIGN_NAME,),
    )
    sent_emails = {r["email"] for r in sent_rows if r.get("email")}

    for u in all_users:
        clean_email = (u.get("email") or "").strip().lower()
        if not clean_email or "@" not in clean_email:
            continue

        if clean_email in sent_emails:
            already_sent_count += 1
            continue

        if is_email_suppressed_db(clean_email):
            suppressed_count += 1
            continue

        eligible.append(u)

    return eligible, suppressed_count, already_sent_count


def main():
    parser = argparse.ArgumentParser(description="Announce ListMate 1.0.1 release to active users.")
    parser.add_argument("--preview", action="store_true", help="Print email preview (plain text and subject) and save preview.html.")
    parser.add_argument("--test-email", type=str, help="Send a single live test email to the specified address.")
    parser.add_argument("--dry-run", action="store_true", help="Count eligible users and preview recipients without sending.")
    parser.add_argument("--send", action="store_true", help="Execute live dispatch to all eligible users.")
    parser.add_argument("--limit", type=int, default=0, help="Optional limit on number of emails to send (e.g. for batching).")

    args = parser.parse_args()

    if args.preview:
        subject, plain, html = generate_email_content(user_name="Ven", user_id=1, household_id=1)
        print("=" * 60)
        print("EMAIL SUBJECT:")
        print(subject)
        print("=" * 60)
        print("PLAIN TEXT BODY:")
        print(plain)
        print("=" * 60)
        preview_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "update_preview.html")
        with open(preview_file, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Saved complete HTML preview to: {preview_file}")
        return

    if args.test_email:
        print(f"Sending live test email to: {args.test_email}...")
        success = send_update_email(
            to_email=args.test_email,
            user_name="Ven (Test)",
            user_id=1,
            household_id=1,
            dry_run=False,
        )
        if success:
            print("Test email sent successfully! Please check your inbox.")
        else:
            print("Failed to send test email. Check SendGrid credentials.")
        return

    if args.dry_run or args.send:
        eligible, suppressed_count, already_sent_count = get_eligible_users()
        total_found = len(eligible) + suppressed_count + already_sent_count

        print("\n" + "=" * 60)
        print(f"ListMate 1.0.1 Announcement Campaign: {CAMPAIGN_NAME}")
        print("=" * 60)
        print(f"Total Users in DB:              {total_found}")
        print(f"Suppressed (Unsub/Bounced/Spam): {suppressed_count}")
        print(f"Already Sent (Idempotent):       {already_sent_count}")
        print(f"Eligible Recipients to Send:     {len(eligible)}")
        print("=" * 60)

        if args.dry_run:
            print("\nSample eligible recipients (first 5):")
            for u in eligible[:5]:
                print(f"  • ID {u['id']}: {u['name']} <{u['email']}> (Household: {u.get('household_id')})")
            print(f"\n[DRY-RUN] No emails were sent. Run with --send to dispatch to all {len(eligible)} users.")
            return

        if args.send:
            if not eligible:
                print("No eligible recipients to send to.")
                return

            to_send = eligible if args.limit <= 0 else eligible[:args.limit]
            print(f"Starting live dispatch to {len(to_send)} users...\n")

            sent_count = 0
            fail_count = 0

            for u in to_send:
                ok = send_update_email(
                    to_email=u["email"],
                    user_name=u.get("name", ""),
                    user_id=u["id"],
                    household_id=u.get("household_id", 0),
                    dry_run=False,
                )
                if ok:
                    sent_count += 1
                else:
                    fail_count += 1

            print("\n" + "=" * 60)
            print(f"Dispatch Complete!")
            print(f"Successfully Sent: {sent_count}")
            print(f"Failed / Skipped:  {fail_count}")
            print("=" * 60)
            return

    parser.print_help()


if __name__ == "__main__":
    main()
