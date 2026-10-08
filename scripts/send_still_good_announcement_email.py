#!/usr/bin/env python3
"""
scripts/send_still_good_announcement_email.py

One-time email campaign to all households announcing the new Still Good feature:
1. Premium & Active Households: Excitement feature update with visual guide on where to find it.
2. Trial Households: Excitement feature update + call-to-action button to upgrade.
3. Expired Households: Excitement feature update + 15-day free trial extension pass + button to upgrade.

Shared components in all tiers:
- Share with Friends & Family button (from 50-day milestone email)
- Update the App to Latest Version section with iOS & Android store buttons (from 50-day milestone email)
- Can preview all 3 templates (--preview) and save to static/preview_still_good_*.html
- Can test send to a single email (--test-email user@example.com --tier premium|trial|expired)
- Can dry-run (--dry-run) to inspect audience counts
- Can dispatch live (--send) with idempotency logging in `email_events` and suppression enforcement
"""

import os
import sys
import argparse
import datetime
from urllib.parse import quote

# Add workspace root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from email_helper import (
    _send_via_api,
    _get_unsub_blocks,
    is_email_suppressed_db,
    FROM_EMAIL,
    FROM_NAME,
    BASE_URL,
)

CAMPAIGN_NAME = "still_good_announcement"
REPLY_TO_EMAIL = "venragh@gmail.com"
REPLY_TO_NAME = "The ListMate Team"
APP_STORE_URL = "https://apps.apple.com/us/app/grocerlistmate/id6795402710"
PLAY_STORE_URL = "https://play.google.com/store/apps/details?id=com.pvkslabs.listmate&pcampaignid=web_share"


def generate_email_content(
    tier: str = "premium_active",
    user_name: str = "",
    household_name: str = "",
    user_id: int = 0,
    household_id: int = 0,
) -> tuple:
    """
    Generates (subject, plain_text, html_body) for the specified household tier.
    Tiers:
      - 'premium_active': Premium & active subscribers (feature excitement + where to find screenshot guide)
      - 'trial': Households currently in free trial (feature excitement + upgrade button)
      - 'expired': Expired / free households (feature excitement + 15-day trial extension offer + upgrade button)
    """
    safe_name = (user_name or "").strip()
    first_name = safe_name.split()[0] if safe_name else "Friend"
    hh_name = (household_name or "Your Household").strip()

    app_url = f"{BASE_URL}/open?url={quote('/?screen=stillGood&source=email_still_good')}"
    feedback_url = f"{BASE_URL}/open?url={quote('/?action=feedback&source=email_still_good')}"
    share_url = f"{BASE_URL}/open?url={quote('/?action=share&source=email_still_good')}"
    upgrade_url = f"{BASE_URL}/open?url={quote('/settings?action=upgrade&source=email_still_good')}"
    claim_ext_15d_url = f"{BASE_URL}/open?url={quote('/settings?action=claim-extension&tier=15d&source=email_still_good')}"

    # Tier-specific copy, subject, badges, and CTA blocks
    if tier == "premium_active":
        subject = "🍲 Introducing Still Good: Track Leftovers & Stop Food Waste (Now in ListMate!)"
        badge_text = "⭐ VIP FEATURE UPDATE • INCLUDED IN YOUR MEMBERSHIP"
        hero_title = "Meet Still Good: Track Leftovers & End Food Waste"
        hero_subtitle = "Fresh from the ListMate kitchen — keep tabs on perishables & freezer meals"
        greeting_line = f"Hi {first_name},"
        intro_p1 = f"As a valued premium member of ListMate for <strong>{hh_name}</strong>, you get first access to everything we build to make kitchen and grocery management seamless."
        intro_p2 = "We are thrilled to unveil our newest major feature: <strong>Still Good</strong> — an intelligent leftovers and freezer meal manager designed to help prevent forgotten ingredients from ending up in the trash and estimate your household food savings."
        cta_primary_html = f"""
          <div style="text-align:center;margin:28px 0 20px;">
            <a href="{app_url}" target="_blank" rel="noopener noreferrer" style="background:linear-gradient(135deg, #059669 0%, #10b981 100%);color:#ffffff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:700;display:inline-block;box-shadow:0 4px 12px rgba(16,185,129,0.35);">
              Open Still Good in ListMate ➔
            </a>
            <div style="margin-top:8px;font-size:12px;color:#64748b;">
              Tap to open directly in the ListMate app
            </div>
          </div>
        """
        unsub_desc = "You received this email because your household has an active Premium membership on ListMate."

    elif tier == "trial":
        subject = "🍲 New in ListMate: Still Good is Unlocked on Your Free Trial (+ Special Upgrade Offer)"
        badge_text = "✨ NEW FEATURE UNLOCKED • ACTIVE ON YOUR PRO TRIAL"
        hero_title = "Introducing Still Good: Stop Tossing Perishables & Real Cash"
        hero_subtitle = "Now unlocked on your household trial — track leftovers & freeze with confidence"
        greeting_line = f"Hi {first_name},"
        intro_p1 = f"We have some exciting news for <strong>{hh_name}</strong>! We just launched one of our biggest features yet, and it is <strong>fully unlocked on your active Pro Trial</strong> right now."
        intro_p2 = "Meet <strong>Still Good</strong> — an intelligent perishables and freezer meal manager that helps you see how long cooked leftovers stay safe, nudges you when it is time to eat them, and estimates your last 7-day savings."
        cta_primary_html = f"""
          <div style="background:#fefce8;border:1px solid #fef08a;border-radius:12px;padding:20px;text-align:center;margin:24px 0 20px;">
            <div style="font-size:14px;font-weight:700;color:#854d0e;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">
              🌟 Keep Still Good & All Pro Features Forever
            </div>
            <p style="margin:0 0 16px;font-size:14px;color:#713f12;line-height:1.5;">
              Upgrade your household today for just <strong>$9.99/year</strong> (less than $1/month) or $1.99/month to ensure uninterrupted access for all members.
            </p>
            <div style="display:inline-block;">
              <a href="{upgrade_url}" target="_blank" rel="noopener noreferrer" style="background:linear-gradient(135deg, #059669 0%, #10b981 100%);color:#ffffff;padding:13px 26px;border-radius:10px;text-decoration:none;font-size:15px;font-weight:700;display:inline-block;box-shadow:0 3px 10px rgba(16,185,129,0.3);margin-right:8px;margin-bottom:6px;">
                Upgrade to ListMate Pro ➔
              </a>
              <a href="{app_url}" target="_blank" rel="noopener noreferrer" style="background:#ffffff;color:#1e293b;border:1px solid #cbd5e1;padding:12px 20px;border-radius:10px;text-decoration:none;font-size:14px;font-weight:600;display:inline-block;margin-bottom:6px;">
                Try Still Good Now
              </a>
            </div>
          </div>
        """
        unsub_desc = "You received this email because your household is currently enjoying a ListMate Pro Trial."

    else:  # 'expired'
        subject = "🎁 Welcome Back to ListMate: Meet Still Good (+ 15 Days Free on Us!)"
        badge_text = "🎁 SPECIAL WELCOME BACK GIFT • 15-DAY FREE PASS"
        hero_title = "We Built Something Special: Meet Still Good (+ 15 Days Free!)"
        hero_subtitle = "A brand new way to end household food waste — come back and try it on us"
        greeting_line = f"Hi {first_name},"
        intro_p1 = f"It has been a little while since your free trial ended for <strong>{hh_name}</strong>, but our team has been hard at work building features to make family life easier."
        intro_p2 = "Today, we are thrilled to introduce <strong>Still Good</strong>: our brand new leftovers and freezer meal tracker. Because we would love to welcome you back, we are offering your household a complimentary <strong>15-Day Free Trial Extension Pass</strong> — zero commitment, no credit card required!"
        cta_primary_html = f"""
          <div style="background:#f0fdf4;border:2px solid #86efac;border-radius:12px;padding:22px;text-align:center;margin:24px 0 20px;">
            <div style="display:inline-block;background:#22c55e;color:#ffffff;font-size:11px;font-weight:800;letter-spacing:1px;text-transform:uppercase;padding:3px 10px;border-radius:12px;margin-bottom:8px;">
              🎁 Instant 1-Click Activation
            </div>
            <div style="font-size:17px;font-weight:800;color:#14532d;margin-bottom:6px;">
              Claim Your 15-Day Free Extension Pass
            </div>
            <p style="margin:0 0 16px;font-size:14px;color:#166534;line-height:1.5;max-width:440px;margin-left:auto;margin-right:auto;">
              Click below to instantly activate 15 full days of ListMate Pro for your entire household. Explore Still Good, real-time shared shopping lists, and aisle sorting on us!
            </p>
            <div style="margin-bottom:12px;">
              <a href="{claim_ext_15d_url}" target="_blank" rel="noopener noreferrer" style="background:#16a34a;color:#ffffff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:700;display:inline-block;box-shadow:0 4px 12px rgba(22,163,74,0.35);margin-right:8px;margin-bottom:8px;">
                Claim 15 Free Days Now ➔
              </a>
              <a href="{upgrade_url}" target="_blank" rel="noopener noreferrer" style="background:#ffffff;color:#1e293b;border:1px solid #cbd5e1;padding:13px 20px;border-radius:10px;text-decoration:none;font-size:14px;font-weight:600;display:inline-block;margin-bottom:8px;">
                Upgrade for $9.99/yr
              </a>
            </div>
            <div style="font-size:12px;color:#15803d;font-weight:500;">
              ✓ No credit card needed &bull; Instant activation for all household members
            </div>
          </div>
        """
        unsub_desc = "You received this email because you created a household on ListMate."

    unsub_txt, unsub_html = _get_unsub_blocks(
        user_id,
        "feature announcements and product updates",
        unsub_desc,
    )

    # Plain text version
    plain_text = f"""{greeting_line}

{intro_p1}

{intro_p2}

==================================================
🍲 WHAT IS "STILL GOOD"?
==================================================
The average family throws away over $1,500 worth of forgotten groceries and leftovers every year. Still Good stops the cycle:

• 🥗 Track Fridge Leftovers & Takeout: Save cooked dishes with one tap (defaults to today's leftovers!).
• ⏱️ Clear color-coded badges show you exactly when food is fresh, eat soon, urgent, or ready to freeze.
• ❄️ 1-Click Freezer Stash: Freeze perishable meals before they spoil. Tap "Thaw" in the morning and get an automatic reminder when dinner is ready.
• 💵 7-Day Savings Estimation: See an estimate of your household's last 7-day food savings based on rescued meals.

==================================================
📍 WHERE TO FIND IT IN LISTMATE
==================================================
Still Good is integrated directly into your everyday app experience:
1. Home Screen: Tap the vibrant green [🍲 Still Good] button located right at the top of your Grocery List.
2. Main Menu: Open the side drawer (☰) anytime to jump directly to 🍲 Still Good.

"""

    if tier == "expired":
        plain_text += f"""==================================================
🎁 CLAIM YOUR 15-DAY FREE EXTENSION PASS
==================================================
Activate 15 full days of ListMate Pro on us (no credit card required):
{claim_ext_15d_url}

Or upgrade for $9.99/year ($1.99/month):
{upgrade_url}

"""
    elif tier == "trial":
        plain_text += f"""==================================================
⭐ LOCK IN LISTMATE PRO FOR YOUR HOUSEHOLD
==================================================
Keep Still Good and all premium features for $9.99/year or $1.99/month:
{upgrade_url}

Open Still Good:
{app_url}

"""
    else:
        plain_text += f"""==================================================
🚀 OPEN STILL GOOD IN LISTMATE
==================================================
{app_url}

"""

    plain_text += f"""==================================================
📲 UPDATE TO THE LATEST VERSION (v1.10.3)
==================================================
Make sure your app is updated to enjoy Still Good and the newest speed enhancements:
• Apple App Store (iOS): {APP_STORE_URL}
• Google Play Store (Android): {PLAY_STORE_URL}

==================================================
🎁 SHARE LISTMATE WITH FRIENDS & FAMILY
==================================================
Know another couple, roommate, or family looking to take the stress out of weekly grocery runs? Invite them to try ListMate:
{share_url}

==================================================
💡 SHARE YOUR FEEDBACK
==================================================
How is Still Good working for your household? What would you like to see next?
Feedback link: {feedback_url}
(Or simply reply directly to this email — I read every note!)

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

        <!-- Main Container Card -->
        <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width:620px;background-color:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.06);border:1px solid #e2e8f0;">
          
          <!-- Top Header Banner -->
          <tr>
            <td style="background:linear-gradient(135deg, #047857 0%, #10b981 100%);padding:36px 32px 30px;text-align:center;color:#ffffff;">
              <div style="display:inline-block;background:rgba(255,255,255,0.22);border-radius:20px;padding:4px 14px;font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#f0fdf4;margin-bottom:12px;">
                {badge_text}
              </div>
              <h1 style="margin:0;font-size:26px;font-weight:800;letter-spacing:-0.5px;line-height:1.25;color:#ffffff;">
                {hero_title}
              </h1>
              <p style="margin:8px 0 0;font-size:15px;color:#d1fae5;font-weight:500;">
                {hero_subtitle}
              </p>
            </td>
          </tr>

          <!-- Main Content Body -->
          <tr>
            <td style="padding:32px 32px 24px;">

              <!-- Greeting & Introduction -->
              <p style="margin:0 0 16px;font-size:16px;color:#1e293b;font-weight:600;">
                {greeting_line}
              </p>
              <p style="margin:0 0 16px;font-size:15px;color:#334155;line-height:1.65;">
                {intro_p1}
              </p>
              <p style="margin:0 0 24px;font-size:15px;color:#334155;line-height:1.65;">
                {intro_p2}
              </p>

              <!-- Tier-specific Callout / Upgrade / Extension Box -->
              {cta_primary_html}

              <!-- Visual Location Guide / Screenshot Mockup -->
              <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;padding:20px;margin-bottom:28px;">
                <div style="text-align:center;margin-bottom:16px;">
                  <span style="font-size:11.5px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#059669;">Quick Visual Guide</span>
                  <h3 style="margin:4px 0 0;font-size:17px;font-weight:700;color:#0f172a;">Where to Find "Still Good" in Your App</h3>
                  <p style="margin:4px 0 0;font-size:13px;color:#64748b;">It is ready for you right now on your Home screen and main navigation</p>
                </div>

                <!-- High-Fidelity UI Mockup Box -->
                <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="background:#ffffff;border:2px solid #cbd5e1;border-radius:12px;overflow:hidden;box-shadow:0 3px 10px rgba(0,0,0,0.05);margin-bottom:16px;">
                  <!-- Mockup Top App Bar -->
                  <tr style="background:#15803d;">
                    <td style="padding:12px 16px;color:#ffffff;font-size:14px;font-weight:700;">
                      <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0">
                        <tr>
                          <td align="left" style="color:#ffffff;font-weight:800;font-size:16px;letter-spacing:0.3px;">
                            <span style="background:#ffffff;color:#15803d;padding:2px 6px;border-radius:6px;font-size:14px;margin-right:6px;">🛒</span> Grocery List
                            <span style="font-size:11px;font-weight:700;background:rgba(255,255,255,0.22);color:#ffffff;padding:2px 8px;border-radius:10px;margin-left:8px;vertical-align:middle;">PRO</span>
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>

                  <!-- Mockup Action Row with Highlighted Still Good Button -->
                  <tr style="background:#f8fafc;">
                    <td style="padding:14px 16px 10px;">
                      <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0">
                        <tr>
                          <td align="left" style="font-size:12px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;">
                            GROCERY LIST
                          </td>
                          <td align="right">
                            <!-- Glowing Golden Halo Still Good Button Mockup -->
                            <div style="display:inline-block;background:linear-gradient(135deg, #059669, #10b981);color:#ffffff;padding:8px 14px;border-radius:10px;font-size:13px;font-weight:700;box-shadow:0 0 0 2px #fef3c7, 0 0 14px rgba(245, 158, 11, 0.75);border:1px solid #10b981;">
                              🍲 Still Good
                            </div>
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>

                  <!-- Mockup Quick Add Box -->
                  <tr style="background:#f8fafc;">
                    <td style="padding:4px 16px 14px;">
                      <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="background:#ffffff;border:2px solid #22c55e;border-radius:10px;overflow:hidden;">
                        <tr>
                          <td style="padding:10px 14px;color:#94a3b8;font-size:13.5px;">Quick add (e.g. Milk)...</td>
                          <td align="right" style="padding:6px 10px;">
                            <span style="background:#22c55e;color:#ffffff;padding:6px 14px;border-radius:6px;font-size:12px;font-weight:700;">Add</span>
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>

                  <!-- Mockup Callout Pointer Note -->
                  <tr style="background:#fefce8;border-top:1px dashed #fef08a;">
                    <td style="padding:10px 14px;font-size:12.5px;color:#854d0e;line-height:1.4;">
                      👉 <strong>Where to find it:</strong> Look for the glowing green <strong>🍲 Still Good</strong> button directly above your Quick Add box on your Home Screen.
                    </td>
                  </tr>
                </table>

                <!-- Two Ways to Access Bullet Points -->
                <div style="font-size:13px;color:#475569;line-height:1.5;">
                  <div style="margin-bottom:6px;">
                    <strong style="color:#0f172a;">1. Home Screen Action Button:</strong> Look for the <strong>🍲 Still Good</strong> button directly above your grocery items list.
                  </div>
                  <div>
                    <strong style="color:#0f172a;">2. Navigation Menu:</strong> You can also tap the ☰ menu icon at any time and choose <strong>🍲 Still Good</strong>.
                  </div>
                </div>
              </div>

              <!-- Feature Highlights Breakdown -->
              <div style="margin-bottom:28px;">
                <div style="font-size:12px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#10b981;margin-bottom:8px;">
                  ✨ Key Capabilities
                </div>
                <h3 style="margin:0 0 16px;font-size:18px;font-weight:700;color:#0f172a;">
                  How Still Good Protects Your Food & Wallet
                </h3>

                <!-- Feature 1: Fridge & Leftovers Tracking -->
                <div style="background:#ffffff;border:1px solid #e2e8f0;border-left:4px solid #10b981;border-radius:8px;padding:14px 16px;margin-bottom:12px;">
                  <div style="font-size:15px;font-weight:700;color:#0f172a;margin-bottom:4px;">
                    🥗 Instant Leftover Tracking (With 1-Tap Defaults)
                  </div>
                  <div style="font-size:13.5px;color:#475569;line-height:1.55;">
                    Save cooked dishes in seconds. If you don't feel like typing, ListMate automatically defaults to <em>"Thursday left overs"</em> and selects your storage location.
                  </div>
                </div>

                <!-- Feature 2: Safe Timing Badges -->
                <div style="background:#ffffff;border:1px solid #e2e8f0;border-left:4px solid #2563eb;border-radius:8px;padding:14px 16px;margin-bottom:12px;">
                  <div style="font-size:14px;color:#334155;line-height:1.55;">
                    ⏱️ Clear color-coded badges show exactly what is <strong>Fresh</strong>, <strong>Eat Soon</strong>, or <strong>Urgent</strong>. Rest easy knowing meals are consumed safely before spoilage.
                  </div>
                </div>

                <!-- Feature 3: 1-Click Batch Freeze & Dinner Thaw Reminders -->
                <div style="background:#ffffff;border:1px solid #e2e8f0;border-left:4px solid #0284c7;border-radius:8px;padding:14px 16px;margin-bottom:12px;">
                  <div style="font-size:15px;font-weight:700;color:#0f172a;margin-bottom:4px;">
                    ❄️ 1-Click Batch Freeze & Thaw Reminders
                  </div>
                  <div style="font-size:13.5px;color:#475569;line-height:1.55;">
                    Heading out of town or made too much chili? Transfer items to the freezer with 1 tap. When you're ready, tap "Thaw" and ListMate keeps you on track for dinner.
                  </div>
                </div>

                <!-- Feature 4: 7-Day Savings Estimation -->
                <div style="background:#ffffff;border:1px solid #e2e8f0;border-left:4px solid #f59e0b;border-radius:8px;padding:14px 16px;margin-bottom:12px;">
                  <div style="font-size:15px;font-weight:700;color:#0f172a;margin-bottom:4px;">
                    💵 7-Day Savings Estimation
                  </div>
                  <div style="font-size:13.5px;color:#475569;line-height:1.55;">
                    Still Good estimates your last 7-day savings based on rescued leftovers and frozen meals directly in your Still Good view.
                  </div>
                </div>
              </div>

              <!-- Store Buttons Section (From 50-day Email) -->
              <div style="background:#f1f5f9;border-radius:12px;padding:24px 20px;text-align:center;margin-bottom:28px;">
                <div style="font-size:15px;font-weight:700;color:#0f172a;margin-bottom:6px;">
                  📲 Update to the Latest Version Today
                </div>
                <p style="margin:0 0 16px;font-size:13.5px;color:#475569;line-height:1.5;">
                  Make sure your app is updated to <strong>v1.10.3</strong> to enjoy Still Good, new trip alerts, and performance enhancements.
                </p>

                <!-- Custom Styled Store Buttons -->
                <table role="presentation" border="0" cellspacing="0" cellpadding="0" style="margin:0 auto;">
                  <tr>
                    <td style="padding:0 8px 8px 0;">
                      <a href="{APP_STORE_URL}" target="_blank" rel="noopener noreferrer" style="background:#000000;color:#ffffff;padding:12px 22px;border-radius:10px;text-decoration:none;font-size:14px;font-weight:700;display:inline-block;box-shadow:0 3px 8px rgba(0,0,0,0.18);white-space:nowrap;">
                        <span style="font-size:16px;margin-right:6px;vertical-align:middle;"></span> Update on App Store
                      </a>
                    </td>
                    <td style="padding:0 0 8px 8px;">
                      <a href="{PLAY_STORE_URL}" target="_blank" rel="noopener noreferrer" style="background:#0f172a;color:#ffffff;border:1px solid #334155;padding:12px 22px;border-radius:10px;text-decoration:none;font-size:14px;font-weight:700;display:inline-block;box-shadow:0 3px 8px rgba(0,0,0,0.18);white-space:nowrap;">
                        <span style="font-size:14px;margin-right:6px;vertical-align:middle;">▶</span> Update on Google Play
                      </a>
                    </td>
                  </tr>
                </table>
              </div>

              <!-- Share with Friends Section (From 50-day Email) -->
              <div style="background:#fafafa;border:1px solid #e2e8f0;border-radius:12px;padding:20px;margin-bottom:28px;text-align:center;">
                <h3 style="margin:0 0 6px;font-size:16px;font-weight:700;color:#0f172a;">
                  🎁 Share ListMate with Friends & Family
                </h3>
                <p style="margin:0 0 14px;font-size:13.5px;color:#64748b;line-height:1.5;max-width:440px;margin-left:auto;margin-right:auto;">
                  Know another couple, roommate, or family looking to take the stress out of weekly grocery runs and reduce food waste? Invite them to try ListMate with your personal link.
                </p>
                <a href="{share_url}" target="_blank" rel="noopener noreferrer" style="background:#0f172a;color:#ffffff;padding:11px 22px;border-radius:8px;text-decoration:none;font-size:13.5px;font-weight:700;display:inline-block;">
                  Share App with Friends &rarr;
                </a>
              </div>

              <!-- Feedback Section -->
              <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:12px;padding:18px 20px;margin-bottom:24px;">
                <h4 style="margin:0 0 6px;font-size:15px;font-weight:700;color:#166534;">
                  💬 We'd Love Your Thoughts on Still Good
                </h4>
                <p style="margin:0 0 12px;font-size:13px;color:#274c36;line-height:1.5;">
                  Have an idea for a food safety preset or an improvement to the leftovers flow? Reply directly to this email or send us a quick note in the app:
                </p>
                <a href="{feedback_url}" target="_blank" rel="noopener noreferrer" style="color:#16a34a;font-weight:700;font-size:13px;text-decoration:none;">
                  Send Feedback in App &rarr;
                </a>
              </div>

              <!-- Sign-off -->
              <div style="border-top:1px solid #e2e8f0;padding-top:20px;">
                <p style="margin:0 0 6px;font-size:15px;color:#334155;line-height:1.6;">
                  Thank you for being part of the ListMate community. We hope Still Good saves your family both time and real dollars every week!
                </p>
                <p style="margin:16px 0 0;font-size:15px;color:#1e293b;font-weight:600;">
                  Warm regards,<br>
                  <span style="color:#0f172a;font-weight:800;">The ListMate Team</span><br>
                  <span style="font-size:13px;color:#64748b;font-weight:400;">ListMate (<a href="{BASE_URL}" style="color:#16a34a;text-decoration:none;">grocerlist.app</a>)</span>
                </p>
              </div>

            </td>
          </tr>

          <!-- Footer with Unsubscribe -->
          <tr>
            <td style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:20px 32px;text-align:center;font-size:12px;color:#94a3b8;line-height:1.5;">
              <p style="margin:0 0 6px;">
                {unsub_desc}
              </p>
              <p style="margin:0 0 10px;">
                <a href="{app_url}" style="color:#16a34a;text-decoration:none;font-weight:600;">Open ListMate</a> &bull; 
                <a href="{feedback_url}" style="color:#64748b;text-decoration:none;">Send Feedback</a> &bull; 
                <a href="https://grocerlist.app/privacy" style="color:#64748b;text-decoration:none;">Privacy Policy</a>
              </p>
              <div>
                {unsub_html}
              </div>
            </td>
          </tr>

        </table>

      </td>
    </tr>
  </table>

</body>
</html>"""

    return subject, plain_text, html_body


def query_households_by_tier() -> dict:
    """
    Queries all registered households and their users, classifying them into:
      - 'premium_active': Active paid/lifetime premium members
      - 'trial': Currently active trial households
      - 'expired': Expired trial, canceled, or free households
    """
    try:
        import db_pg
        query = """
            SELECT 
                h.id AS household_id,
                h.name AS household_name,
                h.is_premium,
                h.subscription_status,
                h.trial_ends_at,
                h.subscription_ends_at,
                u.id AS user_id,
                u.name AS user_name,
                u.email
            FROM auth_households h
            JOIN auth_users u ON u.household_id = h.id
            WHERE u.email IS NOT NULL AND TRIM(u.email) != ''
            ORDER BY h.id ASC, u.id ASC;
        """
        rows = db_pg.execute_query(query) or []
    except Exception as e:
        print(f"[Notice] Could not connect to live database ({e}). Using sample database households for dry run.")
        rows = [
            {"household_id": 1, "household_name": "Miller Household", "is_premium": True, "subscription_status": "premium", "trial_ends_at": None, "subscription_ends_at": None, "user_id": 1, "user_name": "Jordan Miller", "email": "member@example.com"},
            {"household_id": 2, "household_name": "Taylor Household", "is_premium": True, "subscription_status": "active", "trial_ends_at": None, "subscription_ends_at": None, "user_id": 2, "user_name": "Alex Taylor", "email": "alex.taylor@example.com"},
            {"household_id": 3, "household_name": "Rivera Household", "is_premium": False, "subscription_status": "trial", "trial_ends_at": (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)).isoformat(), "subscription_ends_at": None, "user_id": 3, "user_name": "Maria Rivera", "email": "maria.rivera@example.com"},
            {"household_id": 4, "household_name": "Chen Household", "is_premium": False, "subscription_status": "expired", "trial_ends_at": (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=10)).isoformat(), "subscription_ends_at": None, "user_id": 4, "user_name": "David Chen", "email": "david.chen@example.com"},
        ]

    segmented = {
        "premium_active": [],
        "trial": [],
        "expired": [],
    }

    now_utc = datetime.datetime.now(datetime.timezone.utc)

    for r in rows:
        sub_status = (r.get("subscription_status") or "free").strip().lower()
        is_prem = bool(r.get("is_premium"))
        trial_ends_at = r.get("trial_ends_at")

        is_trial_valid = False
        if sub_status == "trial" and trial_ends_at:
            try:
                t_end = trial_ends_at
                if isinstance(t_end, str):
                    if "T" in t_end:
                        t_end = datetime.datetime.fromisoformat(t_end.replace("Z", "+00:00"))
                    else:
                        t_end = datetime.datetime.strptime(t_end, "%Y-%m-%d %H:%M:%S")
                if not getattr(t_end, "tzinfo", None):
                    t_end = t_end.replace(tzinfo=datetime.timezone.utc)
                if t_end > now_utc:
                    is_trial_valid = True
            except Exception:
                pass

        if sub_status in ["premium", "active"]:
            segmented["premium_active"].append(r)
        elif is_prem and sub_status not in ["expired", "trial", "canceled", "free"]:
            segmented["premium_active"].append(r)
        elif is_trial_valid:
            segmented["trial"].append(r)
        else:
            segmented["expired"].append(r)

    return segmented


def has_already_received(user_id: int, clean_email: str) -> bool:
    """Checks email_events to prevent sending duplicate campaign emails."""
    try:
        import db_pg
        rows = db_pg.execute_query(
            """
            SELECT id FROM email_events
            WHERE campaign = %s AND (email = %s OR (user_id = %s AND user_id > 0))
            LIMIT 1;
            """,
            (CAMPAIGN_NAME, clean_email, user_id),
        )
        return bool(rows)
    except Exception:
        return False


def send_campaign_email(
    tier: str,
    to_email: str,
    user_name: str = "",
    household_name: str = "",
    user_id: int = 0,
    household_id: int = 0,
    dry_run: bool = True,
    api_key: str = "",
    force: bool = False,
) -> bool:
    """Dispatches a single Still Good announcement email."""
    clean_email = (to_email or "").strip().lower()
    if not clean_email or "@" not in clean_email:
        return False

    if is_email_suppressed_db(clean_email):
        print(f"[Suppressed] Skipping {clean_email} (in email_suppressions)")
        return False

    if not force and has_already_received(user_id, clean_email):
        print(f"[Already Sent] Skipping {clean_email} (already received {CAMPAIGN_NAME})")
        return False

    subject, plain_text, html_body = generate_email_content(
        tier=tier,
        user_name=user_name,
        household_name=household_name,
        user_id=user_id,
        household_id=household_id,
    )

    if dry_run:
        print(f"[DRY-RUN] [{tier.upper()}] Would send to: {clean_email} (User ID: {user_id}, Name: '{user_name}', Household: '{household_name}')")
        return True

    sendgrid_key = api_key or os.environ.get("SENDGRID_API_KEY", "")
    if not sendgrid_key:
        print(f"ERROR: SENDGRID_API_KEY not configured. Cannot send to {clean_email}.")
        return False

    payload = {
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "reply_to": {"email": REPLY_TO_EMAIL, "name": REPLY_TO_NAME},
        "personalizations": [
            {
                "to": [{"email": clean_email}],
                "custom_args": {
                    "user_id": str(user_id) if user_id else "",
                    "household_id": str(household_id) if household_id else "",
                    "campaign": CAMPAIGN_NAME,
                    "tier": tier,
                },
            }
        ],
        "categories": [CAMPAIGN_NAME, f"still_good_{tier}"],
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

    success = _send_via_api(sendgrid_key, payload)
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
            print(f"[Sent] [{tier.upper()}] Successfully delivered to {clean_email}")
        except Exception as e:
            print(f"[Warning] Email sent to {clean_email}, but logging event failed: {e}")
    else:
        print(f"[Failed] [{tier.upper()}] SendGrid returned error for {clean_email}")

    return success


def main():
    parser = argparse.ArgumentParser(description="Send Still Good announcement emails to all households.")
    parser.add_argument("--preview", action="store_true", help="Generate and save HTML previews for all 3 tiers.")
    parser.add_argument("--dry-run", action="store_true", help="Inspect and count recipients per tier without sending.")
    parser.add_argument("--test-email", type=str, help="Send a test email to the given address.")
    parser.add_argument("--tier", type=str, choices=["premium_active", "trial", "expired"], default="premium_active", help="Target tier for test email (default: premium_active).")
    parser.add_argument("--send", action="store_true", help="Dispatch real emails to all eligible households.")
    parser.add_argument("--force", action="store_true", help="Bypass idempotency checks.")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of emails to dispatch.")
    args = parser.parse_args()

    # 1. Preview mode
    if args.preview:
        out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
        tiers = ["premium_active", "trial", "expired"]
        for t in tiers:
            _, _, html = generate_email_content(
                tier=t,
                user_name="Alex Morgan",
                household_name="Morgan Family",
                user_id=42,
                household_id=12,
            )
            filename = f"preview_still_good_{t}.html"
            filepath = os.path.join(out_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[Preview] Saved {t} template preview to: {filepath}")
        return

    # 2. Test email mode
    if args.test_email:
        print(f"[*] Sending test email ({args.tier}) to {args.test_email}...")
        ok = send_campaign_email(
            tier=args.tier,
            to_email=args.test_email,
            user_name="Test User",
            household_name="Test Household",
            user_id=1,
            household_id=1,
            dry_run=False,
            force=True,
        )
        if ok:
            print(f"[Success] Test email delivered to {args.test_email}.")
        else:
            print(f"[Failed] Could not deliver test email to {args.test_email}.")
        return

    # 3. Dry-run or Send mode
    segmented = query_households_by_tier()
    print("=" * 60)
    print("📊 STILL GOOD ANNOUNCEMENT CAMPAIGN AUDIENCE")
    print("=" * 60)
    print(f"1. Premium & Active Households: {len(segmented['premium_active'])} recipient(s)")
    print(f"2. Trial Households:           {len(segmented['trial'])} recipient(s)")
    print(f"3. Expired Households:         {len(segmented['expired'])} recipient(s)")
    total_all = sum(len(v) for v in segmented.values())
    print(f"Total Households / Users:       {total_all} recipient(s)")
    print("=" * 60)

    if not args.send and not args.dry_run:
        print("Please specify --dry-run, --preview, --test-email, or --send.")
        return

    dry_run = not args.send
    sent_count = 0

    for tier_name, audience in segmented.items():
        print(f"\n[*] Processing Tier: {tier_name.upper()} ({len(audience)} users)...")
        for u in audience:
            if args.limit > 0 and sent_count >= args.limit:
                print(f"[*] Hit limit of {args.limit} emails.")
                break

            send_campaign_email(
                tier=tier_name,
                to_email=u["email"],
                user_name=u.get("user_name") or "",
                household_name=u.get("household_name") or "",
                user_id=u["user_id"],
                household_id=u["household_id"],
                dry_run=dry_run,
                force=args.force,
            )
            sent_count += 1

    print(f"\n[Completed] Processed {sent_count} recipient(s) (dry_run={dry_run}).")


if __name__ == "__main__":
    main()
