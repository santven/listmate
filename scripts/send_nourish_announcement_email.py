#!/usr/bin/env python3
"""
scripts/send_nourish_announcement_email.py

One-time email campaign to all households announcing the new ListMate Nourish feature,
segmented into 4 distinct cohorts:
1. Premium: subscription_status = 'premium' and is_premium = True (Lifetime/Founding VIP members)
2. Trial:   subscription_status = 'trial' (Active Pro Trial households)
3. Paid:    subscription_status = 'active' and is_premium = True (Active recurring paying subscribers)
4. Expired: subscription_status = 'expired' and is_premium = False (Expired trial households with 15-day pass)

Shared components in all tiers:
- Visual guide showing the top-left Suite Switcher (🛒 ListMate | 🍲 Still Good | 🥗 Nourish)
- Core pillars: Describe Plate AI, 1-Tap Shared Family Meals, Still Good Leftover Bridge, Coach Link Portal
- Update the App to Latest Version section with iOS & Android store buttons
- Share with Friends & Family button
- Preview all 4 templates (--preview) and save to static/preview_nourish_*.html
- Test send to a single email (--test-email user@example.com --tier premium|trial|paid|expired)
- Dry-run (--dry-run) to inspect audience counts
- Live dispatch (--send) with idempotency logging in `email_events` and suppression enforcement
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

CAMPAIGN_NAME = "nourish_announcement"
REPLY_TO_EMAIL = "venragh@gmail.com"
REPLY_TO_NAME = "The ListMate Team"
APP_STORE_URL = "https://apps.apple.com/us/app/grocerlistmate/id6795402710"
PLAY_STORE_URL = "https://play.google.com/store/apps/details?id=com.pvkslabs.listmate&pcampaignid=web_share"


def generate_email_content(
    tier: str = "premium",
    user_name: str = "",
    household_name: str = "",
    user_id: int = 0,
    household_id: int = 0,
    is_preview: bool = False,
) -> tuple:
    """
    Generates (subject, plain_text, html_body) for the specified household tier.
    Cohorts:
      - 'premium': subscription_status = 'premium' and is_premium = True (Lifetime/Founding VIP)
      - 'trial':   subscription_status = 'trial' (Active Pro trial)
      - 'paid':    subscription_status = 'active' and is_premium = True (Active paying subscriber)
      - 'expired': subscription_status = 'expired' and is_premium = False (Expired trial + 15-day pass)
    """
    safe_name = (user_name or "").strip()
    first_name = safe_name.split()[0] if safe_name else "Friend"
    hh_name = (household_name or "Your Household").strip()

    app_url = f"{BASE_URL}/open?url={quote('/?screen=nourish&source=email_nourish')}"
    feedback_url = f"{BASE_URL}/open?url={quote('/?action=feedback&source=email_nourish')}"
    share_url = f"{BASE_URL}/open?url={quote('/?action=share&source=email_nourish')}"
    upgrade_url = f"{BASE_URL}/open?url={quote('/settings?action=upgrade&source=email_nourish')}"
    claim_ext_15d_url = f"{BASE_URL}/open?url={quote('/settings?action=claim-extension&tier=15d&source=email_nourish')}"
    switcher_img_url = "https://raw.githubusercontent.com/santven/listmate/staging/docs/Screenshot_20261019-192821.png"

    # Tier-specific copy, subject, badges, and CTA blocks
    if tier == "premium":
        subject = "🥗 Introducing Nourish: Included with Your Lifetime Premium Membership"
        badge_text = "⭐ VIP LIFETIME MEMBER UPDATE • 100% INCLUDED"
        hero_title = "Meet Nourish: Included with Your Lifetime Membership"
        hero_subtitle = "No recurring fees, zero ad clutter & zero paywalls — thank you for being a founding member!"
        greeting_line = f"Hi {first_name},"
        intro_p1 = f"As a valued lifetime founding member of ListMate for <strong>{hh_name}</strong>, you helped bring our vision to life. That is why every new suite we build is automatically included in your membership forever — with zero recurring subscriptions or hidden upgrade fees."
        intro_p2 = "Today, we are proud to introduce <strong>ListMate Nourish</strong>: an intelligent food and macro tracker built specifically for households. While standalone apps like MyFitnessPal charge $80 to $130 per person every year and lock basic gram targets behind paywalls, Nourish is <strong>completely unlocked in your lifetime membership</strong> with zero ads and zero extra charges."
        cta_primary_html = f"""
          <div style="text-align:center;margin:28px 0 20px;">
            <a href="{app_url}" target="_blank" rel="noopener noreferrer" style="background:linear-gradient(135deg, #059669 0%, #10b981 100%);color:#ffffff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:700;display:inline-block;box-shadow:0 4px 12px rgba(16,185,129,0.35);">
              Open Nourish in ListMate ➔
            </a>
            <div style="margin-top:8px;font-size:12px;color:#64748b;">
              Tap to open directly in your ListMate app
            </div>
          </div>
        """
        unsub_desc = "You received this email because your household holds a lifetime Premium membership on ListMate."

    elif tier == "trial":
        subject = "🥗 New in ListMate: Nourish is Unlocked on Your Free Trial (+ Special Upgrade Offer)"
        badge_text = "✨ NEW FEATURE UNLOCKED • ACTIVE ON YOUR PRO TRIAL"
        hero_title = "Meet Nourish: Effortless Meal & Macro Tracking on Your Pro Trial"
        hero_subtitle = "Now unlocked on your household trial — track nutrition together without duplicate typing"
        greeting_line = f"Hi {first_name},"
        intro_p1 = f"We have exciting news for <strong>{hh_name}</strong>! We just launched our brand-new nutrition tracker, and it is <strong>fully unlocked on your active Pro Trial</strong> right now."
        intro_p2 = "Meet <strong>ListMate Nourish</strong> — an intelligent food and macro tracker that lets you describe meals in conversational English, share home-cooked dinners with family members in 1 tap, and bridge leftovers from Still Good directly to your diary."
        cta_primary_html = f"""
          <div style="background:#fefce8;border:1px solid #fef08a;border-radius:12px;padding:20px;text-align:center;margin:24px 0 20px;">
            <div style="font-size:14px;font-weight:700;color:#854d0e;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">
              🌟 Keep Nourish, Still Good & All Pro Features Forever
            </div>
            <p style="margin:0 0 16px;font-size:14px;color:#713f12;line-height:1.5;">
              While apps like MyFitnessPal charge $79.99/year <em>per person</em>, upgrade your entire household to ListMate Pro for just <strong>$9.99/year</strong> (less than $1/month) or $1.99/month for all members combined.
            </p>
            <div style="display:inline-block;">
              <a href="{upgrade_url}" target="_blank" rel="noopener noreferrer" style="background:linear-gradient(135deg, #059669 0%, #10b981 100%);color:#ffffff;padding:13px 26px;border-radius:10px;text-decoration:none;font-size:15px;font-weight:700;display:inline-block;box-shadow:0 3px 10px rgba(16,185,129,0.3);margin-right:8px;margin-bottom:6px;">
                Upgrade to ListMate Pro ➔
              </a>
              <a href="{app_url}" target="_blank" rel="noopener noreferrer" style="background:#ffffff;color:#1e293b;border:1px solid #cbd5e1;padding:12px 20px;border-radius:10px;text-decoration:none;font-size:14px;font-weight:600;display:inline-block;margin-bottom:6px;">
                Try Nourish Now
              </a>
            </div>
          </div>
        """
        unsub_desc = "You received this email because your household is currently enjoying a ListMate Pro Trial."

    elif tier == "paid":
        subject = "🥗 Meet Nourish: Included with Your Active ListMate Subscription"
        badge_text = "⭐ ACTIVE SUBSCRIBER UPDATE • INCLUDED IN YOUR PLAN"
        hero_title = "Meet Nourish: Included with Your Active ListMate Subscription"
        hero_subtitle = "Track nutrition together — zero ads, zero duplicate entry & zero extra charges"
        greeting_line = f"Hi {first_name},"
        intro_p1 = f"Thank you for being an active subscriber of ListMate Pro for <strong>{hh_name}</strong>! Your support enables us to keep building tools that make kitchen, food, and grocery management simpler."
        intro_p2 = "We are thrilled to include our newest suite, <strong>ListMate Nourish</strong>, in your active subscription at <strong>no extra charge</strong>. While standalone fitness apps like MyFitnessPal charge $79.99 to $129 per person every single year, your existing ListMate Pro subscription covers nutrition tracking for your entire household under one simple plan."
        cta_primary_html = f"""
          <div style="text-align:center;margin:28px 0 20px;">
            <a href="{app_url}" target="_blank" rel="noopener noreferrer" style="background:linear-gradient(135deg, #059669 0%, #10b981 100%);color:#ffffff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:700;display:inline-block;box-shadow:0 4px 12px rgba(16,185,129,0.35);">
              Open Nourish in ListMate ➔
            </a>
            <div style="margin-top:8px;font-size:12px;color:#64748b;">
              Tap to open directly in the ListMate app
            </div>
          </div>
        """
        unsub_desc = "You received this email because your household has an active subscription on ListMate."

    else:  # 'expired'
        subject = "🎁 Welcome Back to ListMate: Meet Nourish (+ 15 Days Free on Us!)"
        badge_text = "🎁 SPECIAL WELCOME BACK GIFT • 15-DAY FREE PASS"
        hero_title = "We Built Something Special: Meet Nourish (+ 15 Days Free!)"
        hero_subtitle = "A brand-new way to track nutrition together — come back and try it on us"
        greeting_line = f"Hi {first_name},"
        intro_p1 = f"It has been a little while since your free trial ended for <strong>{hh_name}</strong>, but our team has been working around the clock building features to simplify family mealtime."
        intro_p2 = "Today, we are thrilled to introduce <strong>ListMate Nourish</strong>: our brand-new nutrition and macro tracker. Because we would love to welcome you back, we are offering your household a complimentary <strong>15-Day Free Trial Extension Pass</strong> — zero commitment, no credit card required!"
        cta_primary_html = f"""
          <div style="background:#f0fdf4;border:2px solid #86efac;border-radius:12px;padding:22px;text-align:center;margin:24px 0 20px;">
            <div style="display:inline-block;background:#22c55e;color:#ffffff;font-size:11px;font-weight:800;letter-spacing:1px;text-transform:uppercase;padding:3px 10px;border-radius:12px;margin-bottom:8px;">
              🎁 Instant 1-Click Activation
            </div>
            <div style="font-size:17px;font-weight:800;color:#14532d;margin-bottom:6px;">
              Claim Your 15-Day Free Extension Pass
            </div>
            <p style="margin:0 0 16px;font-size:14px;color:#166534;line-height:1.5;max-width:440px;margin-left:auto;margin-right:auto;">
              Click below to instantly activate 15 full days of ListMate Pro for your entire household. Explore Nourish, Still Good, and collaborative grocery lists on us!
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
🥗 WHAT IS "LISTMATE NOURISH"?
==================================================
Traditional fitness apps like MyFitnessPal charge upwards of $80 to $130 a year, lock exact protein gram goals behind paywalls, and force family members to log the same home-cooked dinner separately.

Nourish changes the game:

• 💬 Describe Plate AI: Just type what you ate in everyday conversational English ("2 dosas with paneer bhurji and chutney"). Our culinary AI deconstructs the dish, estimates portions, and logs macros in seconds.
• 👨‍👩‍👧 1-Tap Shared Family Meals: Cooked dinner for the household? Log it once, tap "Share", and family members get an automatic 1-tap add bottom drawer.
• 🍲 Leftover Bridge (Still Good): Mark fridge leftovers as "Enjoyed" in Still Good and log them directly into your diary with 1 tap.
• 🔒 100% Private by Default: Your personal calorie diary is completely private to you.
• 🩺 Coach Link Portal: Generate a secure, read-only link for personal trainers, nutritionists, or coaches to inspect 7-day calorie trends and send actionable advice.

==================================================
📍 WHERE TO FIND IT IN LISTMATE
==================================================
Nourish is integrated directly into your everyday app experience:
1. Top-Left App Switcher: Tap the app icon in the top-left corner of your header (🛒▾) to open the Household Suite menu, then select 🍎 Nourish [NEW].
2. Main Menu Drawer: Open the side drawer (☰) anytime to select 🍎 Nourish (Food Log).

"""

    if tier == "expired":
        plain_text += f"""==================================================
🎁 CLAIM YOUR 15-DAY FREE EXTENSION PASS
==================================================
Activate 15 full days of ListMate Pro on us (no credit card required):
{claim_ext_15d_url}

Or upgrade your household for $9.99/year ($1.99/month):
{upgrade_url}

"""
    elif tier == "trial":
        plain_text += f"""==================================================
⭐ LOCK IN LISTMATE PRO FOR YOUR HOUSEHOLD
==================================================
Keep Nourish and all premium features for $9.99/year or $1.99/month:
{upgrade_url}

Open Nourish:
{app_url}

"""
    else:
        plain_text += f"""==================================================
🚀 OPEN NOURISH IN LISTMATE
==================================================
{app_url}

"""

    plain_text += f"""==================================================
📲 UPDATE TO THE LATEST VERSION (v1.11.0)
==================================================
Make sure your app is updated to enjoy Nourish and the newest features:
• Apple App Store (iOS): {APP_STORE_URL}
• Google Play Store (Android): {PLAY_STORE_URL}

==================================================
🎁 SHARE LISTMATE WITH FRIENDS & FAMILY
==================================================
Know another couple, roommate, or family looking to take the stress out of weekly grocery runs and healthy eating? Invite them to try ListMate:
{share_url}

==================================================
💡 SHARE YOUR FEEDBACK
==================================================
How is Nourish working for your household? What would you like to see next?
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

              <!-- Visual Location Guide / Switcher Screenshot -->
              <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;padding:22px;margin-bottom:28px;">
                <div style="text-align:center;margin-bottom:18px;">
                  <span style="font-size:11.5px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:#059669;">Quick Visual Guide</span>
                  <h3 style="margin:4px 0 0;font-size:18px;font-weight:800;color:#0f172a;">Where to Find "Nourish" in Your App</h3>
                  <p style="margin:4px 0 0;font-size:13px;color:#64748b;">Tap the top-left suite button anytime to switch between apps</p>
                </div>

                <!-- Authentic App Switcher Screenshot Frame -->
                <div style="text-align:center;margin-bottom:18px;">
                  <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width:320px;margin:0 auto;background:#ffffff;border:1px solid #cbd5e1;border-radius:14px;overflow:hidden;box-shadow:0 6px 20px rgba(0,0,0,0.08);">
                    <tr>
                      <td style="padding:0;background:#2e7d32;line-height:0;text-align:center;">
                        <img src="{switcher_img_url}" alt="ListMate Household Suite Switcher: Tap top-left to select Nourish" width="320" style="display:block;width:100%;max-width:320px;height:auto;border:0;outline:none;text-decoration:none;" />
                      </td>
                    </tr>
                    <tr>
                      <td style="padding:12px 14px;background:#fefce8;border-top:1px dashed #fef08a;text-align:left;">
                        <div style="font-size:12.5px;color:#854d0e;line-height:1.45;">
                          👉 <strong>Pro-Tip:</strong> Tap the app icon in the top-left of your header (<strong>🛒▴</strong>) to reveal the <strong>Household Suite</strong> menu, then tap <strong>🍎 Nourish <span style="background:#10b981;color:#ffffff;font-size:10px;font-weight:800;padding:1px 6px;border-radius:999px;">NEW</span></strong>.
                        </div>
                      </td>
                    </tr>
                  </table>
                </div>

                <!-- Two Ways to Access Bullet Points -->
                <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:14px 16px;font-size:13.5px;color:#475569;line-height:1.55;">
                  <div style="margin-bottom:8px;">
                    <strong style="color:#0f172a;">1. Top-Left App Switcher:</strong> Tap the app icon in your header (<strong>🛒▴</strong>) anytime to reveal the <strong>Household Suite</strong> dropdown and select <strong>🍎 Nourish</strong>.
                  </div>
                  <div>
                    <strong style="color:#0f172a;">2. Main Menu Drawer:</strong> You can also tap the ☰ menu icon at any time and choose <strong>🍎 Nourish (Food Log)</strong>.
                  </div>
                </div>
              </div>

              <!-- 4 Core Pillars Section -->
              <h2 style="margin:0 0 16px;font-size:18px;font-weight:800;color:#0f172a;letter-spacing:-0.3px;">
                🥗 The 4 Things You'll Love About Nourish
              </h2>

              <table role="presentation" width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-bottom:28px;">
                <tr>
                  <td style="padding:12px 14px;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;margin-bottom:10px;display:block;">
                    <div style="font-size:14.5px;font-weight:700;color:#0f172a;margin-bottom:4px;">
                      💬 1. Describe Plate AI (Zero Tedious Searching)
                    </div>
                    <div style="font-size:13.5px;color:#475569;line-height:1.5;">
                      Type what you ate in everyday conversational English (*"2 dosas with paneer bhurji & coconut chutney"*). Our culinary AI deconstructs ingredients, portions, and macros automatically.
                    </div>
                  </td>
                </tr>
                <tr>
                  <td style="padding:12px 14px;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;margin-bottom:10px;display:block;">
                    <div style="font-size:14.5px;font-weight:700;color:#0f172a;margin-bottom:4px;">
                      👨‍👩‍👧 2. 1-Tap Shared Family Meals
                    </div>
                    <div style="font-size:13.5px;color:#475569;line-height:1.5;">
                      Cooked dinner for the household? Log it once, tap "Share", and other family members receive a friendly alert with a 1-tap add bottom drawer. No more logging the same meal twice.
                    </div>
                  </td>
                </tr>
                <tr>
                  <td style="padding:12px 14px;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;margin-bottom:10px;display:block;">
                    <div style="font-size:14.5px;font-weight:700;color:#0f172a;margin-bottom:4px;">
                      🍲 3. From Fridge to Diary (Still Good Bridge)
                    </div>
                    <div style="font-size:13.5px;color:#475569;line-height:1.5;">
                      When you finish leftovers in Still Good, simply tap "Enjoyed" to log them straight to your lunch or dinner diary without re-entering ingredients.
                    </div>
                  </td>
                </tr>
                <tr>
                  <td style="padding:12px 14px;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;display:block;">
                    <div style="font-size:14.5px;font-weight:700;color:#0f172a;margin-bottom:4px;">
                      🩺 4. Coach Link Portal &amp; Trend Analytics
                    </div>
                    <div style="font-size:13.5px;color:#475569;line-height:1.5;">
                      Working with a personal trainer, dietitian, or coach? Generate a private read-only Coach Link so they can inspect 7-day intake charts and leave feedback notes directly in your app.
                    </div>
                  </td>
                </tr>
              </table>

              <!-- App Store Download / Update Badges -->
              <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;padding:20px;text-align:center;margin-bottom:28px;">
                <div style="font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#64748b;margin-bottom:6px;">
                  📲 Make Sure Your App is Up-to-Date
                </div>
                <div style="font-size:15px;font-weight:700;color:#0f172a;margin-bottom:14px;">
                  ListMate v1.11.0 is Available on iOS and Android
                </div>
                <div>
                  <a href="{APP_STORE_URL}" target="_blank" rel="noopener noreferrer" style="display:inline-block;background:#000000;color:#ffffff;padding:10px 18px;border-radius:10px;text-decoration:none;font-size:13px;font-weight:700;margin:0 4px 6px;">
                     Download on App Store
                  </a>
                  <a href="{PLAY_STORE_URL}" target="_blank" rel="noopener noreferrer" style="display:inline-block;background:#000000;color:#ffffff;padding:10px 18px;border-radius:10px;text-decoration:none;font-size:13px;font-weight:700;margin:0 4px 6px;">
                    ▶ Get it on Google Play
                  </a>
                </div>
              </div>

              <!-- Share with Friends & Family -->
              <div style="background:#ecfdf5;border:1px solid #a7f3d0;border-radius:14px;padding:20px;text-align:center;margin-bottom:28px;">
                <div style="font-size:15px;font-weight:800;color:#065f46;margin-bottom:4px;">
                  🎁 Know a Friend Who Tracks Food?
                </div>
                <p style="margin:0 0 14px;font-size:13.5px;color:#047857;line-height:1.5;">
                  Share ListMate with friends or family tired of paying $80/year for clunky calorie trackers.
                </p>
                <a href="{share_url}" target="_blank" rel="noopener noreferrer" style="background:#10b981;color:#ffffff;padding:10px 22px;border-radius:8px;text-decoration:none;font-size:13.5px;font-weight:700;display:inline-block;">
                  Share ListMate with Friends ➔
                </a>
              </div>

              <!-- Founder Sign-off -->
              <div style="border-top:1px solid #e2e8f0;padding-top:20px;font-size:14px;color:#475569;line-height:1.6;">
                <p style="margin:0 0 10px;">
                  We built Nourish to bring sanity back to household meal planning and healthy living. Have ideas or feedback? Just reply directly to this email — I read and answer every note.
                </p>
                <p style="margin:0;font-weight:600;color:#0f172a;">
                  Warm regards,<br>
                  <span style="color:#059669;">The ListMate Team</span>
                </p>
              </div>

            </td>
          </tr>

          <!-- Footer Unsubscribe Block -->
          <tr>
            <td style="background-color:#f8fafc;border-top:1px solid #e2e8f0;padding:24px 32px;text-align:center;font-size:12px;color:#94a3b8;line-height:1.6;">
              {unsub_html}
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
    Queries all registered households and their users, strictly classifying them into:
      1. Premium: subscription_status = 'premium' and is_premium = True (Lifetime/Founding VIP)
      2. Trial:   subscription_status = 'trial' (Active Pro Trial)
      3. Paid:    subscription_status = 'active' and is_premium = True (Active recurring subscribers)
      4. Expired: subscription_status = 'expired' and is_premium = False (Expired trial households)
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
        "premium": [],
        "trial": [],
        "paid": [],
        "expired": [],
    }

    for r in rows:
        sub_status = (r.get("subscription_status") or "").strip().lower()
        is_prem = bool(r.get("is_premium"))

        # 1. Premium - subscription status = premium and is_premium = true
        if sub_status == "premium" and is_prem:
            segmented["premium"].append(r)
        # 2. Trial - subscription status = trial
        elif sub_status == "trial":
            segmented["trial"].append(r)
        # 3. Paid - subscription status = active and is_premium = true
        elif sub_status == "active" and is_prem:
            segmented["paid"].append(r)
        # 4. Expired - subscription status = expired and is_premium = false
        elif sub_status == "expired" and not is_prem:
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
    """Dispatches a single Nourish announcement email."""
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
        "categories": [CAMPAIGN_NAME, f"nourish_{tier}"],
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
    parser = argparse.ArgumentParser(description="Send Nourish announcement emails to all households.")
    parser.add_argument("--preview", action="store_true", help="Generate and save HTML previews for all 4 cohorts.")
    parser.add_argument("--dry-run", action="store_true", help="Inspect and count recipients per cohort without sending.")
    parser.add_argument("--test-email", type=str, help="Send a test email to the given address.")
    parser.add_argument("--tier", type=str, choices=["premium", "trial", "paid", "expired"], default="premium", help="Target cohort for test email: premium, trial, paid, or expired (default: premium).")
    parser.add_argument("--send", action="store_true", help="Dispatch real emails to all eligible households.")
    parser.add_argument("--force", action="store_true", help="Bypass idempotency checks.")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of emails to dispatch.")
    parser.add_argument("--api-key", type=str, default="", help="SendGrid API key (defaults to SENDGRID_API_KEY env).")
    args = parser.parse_args()

    # 1. Preview mode
    if args.preview:
        out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
        tiers = ["premium", "trial", "paid", "expired"]
        for t in tiers:
            _, _, html = generate_email_content(
                tier=t,
                user_name="Venkat Raghavan",
                household_name="Raghavan Family",
                user_id=101,
                household_id=1,
                is_preview=True,
            )
            filename = f"preview_nourish_{t}.html"
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
            user_name="Venkat Raghavan",
            household_name="Raghavan Family",
            user_id=101,
            household_id=1,
            dry_run=False,
            api_key=args.api_key,
            force=True,
        )
        if ok:
            print(f"[Success] Test email ({args.tier}) delivered to {args.test_email}.")
        else:
            print(f"[Failed] Could not deliver test email to {args.test_email}.")
        return

    # 3. Dry-run or Send mode
    segmented = query_households_by_tier()
    print("=" * 65)
    print("📊 NOURISH ANNOUNCEMENT CAMPAIGN AUDIENCE")
    print("=" * 65)
    print(f"1. Premium (status='premium', is_premium=True): {len(segmented['premium'])} recipient(s)")
    print(f"2. Trial   (status='trial'):                    {len(segmented['trial'])} recipient(s)")
    print(f"3. Paid    (status='active', is_premium=True):  {len(segmented['paid'])} recipient(s)")
    print(f"4. Expired (status='expired', is_premium=False): {len(segmented['expired'])} recipient(s)")
    total_all = sum(len(v) for v in segmented.values())
    print("-" * 65)
    print(f"Total Eligible Recipients:                      {total_all} recipient(s)")
    print("=" * 65)

    if not args.send and not args.dry_run:
        print("Please specify --dry-run, --preview, --test-email, or --send.")
        return

    dry_run = not args.send
    sent_count = 0

    for tier_name, audience in segmented.items():
        print(f"\n[*] Processing Cohort: {tier_name.upper()} ({len(audience)} users)...")
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
                api_key=args.api_key,
                force=args.force,
            )
            sent_count += 1

    print(f"\n[Completed] Processed {sent_count} recipient(s) (dry_run={dry_run}).")


if __name__ == "__main__":
    main()
