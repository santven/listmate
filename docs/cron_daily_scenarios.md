# Daily Cron Job Scenarios (`scripts/cron_daily.py`)

## Overview
The `cron_daily.py` script runs daily to evaluate user and household lifecycle states and send automated, high-conversion email reminders.

The script aggregates notifications per user. If a user qualifies for multiple events on the same day, they receive a single combined notice rather than multiple separate emails.

Every automated reminder is tracked with explicit database timestamp fields on `auth_households` to prevent repeated or duplicate sends.

---

## Scenarios Evaluated

### 1. Expirations (Trial & Paid Subscription Ending Notices)
- **Trial 3 Days Left**: `h.subscription_status = 'trial'` and `trial_ends_at` is in 3 days. Tracked via `email_trial_exp_3days_sent_at`.
- **Trial Ends Today (Day 0)**: `h.subscription_status = 'trial'` and `trial_ends_at` is today. Tracked via `email_trial_exp_today_sent_at`.
- **Paid Subscription 3 Days Left**: `h.subscription_status IN ('premium', 'active')` and `subscription_ends_at` is in 3 days. Tracked via `email_sub_exp_3days_sent_at`.
- **Paid Subscription Ends Today (Day 0)**: `h.subscription_status IN ('premium', 'active')` and `subscription_ends_at` is today. Tracked via `email_sub_exp_today_sent_at`.
- **Buttons**:
  - ⭐ **Upgrade Household** (`/settings?action=upgrade&source=email_reminder`)
  - 👥 **Add Members** (`/settings?action=add-member&source=email_reminder`)

---

### 2. Solo Household Owner Nudge (Day 3 Solo Household)
- **Trigger Condition**: Household was created 3 or more days ago (`DATE(h.created_at) <= CURRENT_DATE - INTERVAL '3 days'`).
- **Target Audience**: Household has only 1 member (`auth_household_members` count = 1).
- **Tracking Column**: `email_solo_nudge_sent_at` (must be `NULL` to trigger; updated with timestamp upon sending).
- **Content & Purpose**:
  - Gently nudges the owner to invite partner, family members, or roommates.
  - Highlights that **only the household pays for a Pro subscription ($1.99/mo or $9.99/yr)** and that invited members join, edit, and sync completely free.
  - Explains real-time list sync benefits: zero duplicate buys, items cross off live across devices, and no more texting back and forth while shopping.
- **Buttons**:
  - 👥 **Invite Household Members** (`/settings?action=add-member&source=email_solo_nudge`)
  - ⭐ **View Pro Plans** (`/settings?action=upgrade&source=email_solo_nudge`)

---

### 3. Trial Week 1 Check-in (Day 7)
- **Trigger Condition**: Household on `'trial'` status created 7 or more days ago (`DATE(h.created_at) <= CURRENT_DATE - INTERVAL '7 days'`).
- **Tracking Column**: `email_trial_week1_sent_at` (must be `NULL` to trigger; updated with timestamp upon sending).
- **Content & Purpose**:
  - Asks what they think of ListMate and how their first week went.
  - Highlights early upgrade options ($1.99/mo or $9.99/yr) while reassuring that **upgrading early still gives them their full 30-day trial period** (paid billing begins only after the 30-day trial concludes).
  - Recommends the **Feature Discovery Tips** in the app menu to learn about aisle auto-sorting, store filters (Patel Brothers, Costco, Trader Joe's), and multi-store planning.
- **Buttons**:
  - ⭐ **Upgrade Subscription** (`/settings?action=upgrade&source=email_trial_week1`)
  - 👥 **Add Members** (`/settings?action=add-member&source=email_trial_week1`)

---

### 4. Trial Week 3 Check-in (Day 21)
- **Trigger Condition**: Household on `'trial'` status created 21 or more days ago (`DATE(h.created_at) <= CURRENT_DATE - INTERVAL '21 days'`).
- **Tracking Column**: `email_trial_week3_sent_at` (must be `NULL` to trigger; updated with timestamp upon sending).
- **Content & Purpose**:
  - Check-in at 3 weeks (~9 days left in trial).
  - Reminds user to lock in their household plan ($1.99/mo or $9.99/yr) before trial expiration, preserving remaining free trial days.
  - Reminds that 1 subscription covers the entire household.
- **Buttons**:
  - ⭐ **Upgrade Subscription** (`/settings?action=upgrade&source=email_trial_week3`)
  - 👥 **Add Members** (`/settings?action=add-member&source=email_trial_week3`)

---

### 5. Activations (Day 3+ Inactive, 0 Items)
- **Trigger Condition**: Household created 3+ days ago with 0 items in `list_items`.
- **Tracking Column**: `email_activation_sent_at`.
- **Buttons**:
  - 🛒 **Add First Item** (`/?source=email_activation`)
  - 👥 **Invite Members** (`/settings?action=add-member&source=email_activation`)

---

### 6. Re-engagement (Day 14+ Inactive)
- **Trigger Condition**: Most recent item added was 14+ days ago.
- **Tracking Column**: `email_reengagement_sent_at` (sent only if `NULL` or previous send was 30+ days ago).
- **Buttons**:
  - 🛒 **Plan Your Next Trip** (`/?source=email_reengagement`)
  - 👥 **Invite Members** (`/settings?action=add-member&source=email_reengagement`)

---

## Tracking Fields in `auth_households` Table

| Field Name | Type | Description |
|---|---|---|
| `email_solo_nudge_sent_at` | `TIMESTAMP` | Timestamp when Day 3 solo household member invite nudge was sent. |
| `email_trial_week1_sent_at` | `TIMESTAMP` | Timestamp when Day 7 (Week 1) trial feedback & discovery email was sent. |
| `email_trial_week3_sent_at` | `TIMESTAMP` | Timestamp when Day 21 (Week 3) trial check-in was sent. |
| `email_activation_sent_at` | `TIMESTAMP` | Timestamp when Day 3 zero-item activation email was sent. |
| `email_reengagement_sent_at` | `TIMESTAMP` | Timestamp when 14-day inactivity re-engagement email was sent. |
| `email_trial_exp_3days_sent_at` | `TIMESTAMP` | Timestamp when 3-day trial expiration notice was sent. |
| `email_trial_exp_today_sent_at` | `TIMESTAMP` | Timestamp when Day 0 trial expiration notice was sent. |
| `email_sub_exp_3days_sent_at` | `TIMESTAMP` | Timestamp when 3-day subscription expiration notice was sent. |
| `email_sub_exp_today_sent_at` | `TIMESTAMP` | Timestamp when Day 0 subscription expiration notice was sent. |

---

## Testing & Maintenance
To run the script manually:
```bash
python scripts/cron_daily.py
```

