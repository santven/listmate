# Daily Cron Job Scenarios (`scripts/cron_daily.py`)

## Overview
The `cron_daily.py` script runs daily to evaluate user and household lifecycle states and send automated, high-conversion email reminders.

The script aggregates notifications per user. If a user qualifies for multiple events on the same day, they receive a single combined notice rather than multiple separate emails.

Every automated reminder is tracked in the `email_events` table (`event_type = 'sent'`, `campaign = ...`) to prevent repeated or duplicate sends.

## Email Classification & Compliance

Our system strictly delineates between **Marketing** (lifecycle, engagement, promotional) and **Transactional** (essential account notices) emails to comply with CAN-SPAM and GDPR regulations.

| Email Type | Classification | Campaign Identifier | Condition / Target Audience |
| :--- | :--- | :--- | :--- |
| **Solo Owner Nudge (Day 3)** | 📢 **Marketing** | `solo_nudge` | Encourages single-member households to invite family/roommates. |
| **Trial Week 1 Check-in (Day 7)** | 📢 **Marketing** | `trial_week1` | Promotes early upgrades ($1.99/mo or $9.99/yr) and shares discovery tips. |
| **Trial Week 3 Check-in (Day 21)** | 📢 **Marketing** | `trial_week3` | Reminds users to lock in an upgrade before the trial ends in ~9 days. |
| **Activation (Day 3)** | 📢 **Marketing** | `activation` | Sent to users with 0 list items after 3 days. |
| **Re-engagement (Day 14)** | 📢 **Marketing** | `reengagement` | Sent to dormant users who haven't added items in 14+ days. |
| **Trial Expirations (Day 3 / Day 0)** | ⚖️ **Transactional** | `trial_exp_3days` / `trial_exp_today` | Essential service/account status notices (imminent access changes). |
| **Sub Expirations (Day 3 / Day 0)** | ⚖️ **Transactional** | `sub_exp_3days` / `sub_exp_today` | Essential payment renewal/lapsing notices. |

### Legal Safeguards
1. **`marketing_opt_in` Enforcement**: All marketing emails are guarded by `AND ahm.marketing_opt_in = TRUE` in their SQL queries. Users who disable marketing communications in their Settings will never be queried or sent these emails.
2. **Universal Unsubscribe Link**: Every marketing email includes a tokenized unsubscribe link in both plaintext and HTML formats (via `_get_unsub_link(user_id)`).

---

## Scenarios Evaluated

### 1. Expirations (Trial & Paid Subscription Ending Notices)
- **Classification**: ⚖️ **Transactional** (Sent regardless of marketing opt-in).
- **Trial 3 Days Left**: `h.subscription_status = 'trial'` and `trial_ends_at` is in 3 days. Tracked via `campaign = 'trial_exp_3days'`.
- **Trial Ends Today (Day 0)**: `h.subscription_status = 'trial'` and `trial_ends_at` is today. Tracked via `campaign = 'trial_exp_today'`.
- **Paid Subscription 3 Days Left**: `h.subscription_status IN ('premium', 'active')` and `subscription_ends_at` is in 3 days. Tracked via `campaign = 'sub_exp_3days'`.
- **Paid Subscription Ends Today (Day 0)**: `h.subscription_status IN ('premium', 'active')` and `subscription_ends_at` is today. Tracked via `campaign = 'sub_exp_today'`.
- **Buttons**:
  - ⭐ **Upgrade Household** (`/settings?action=upgrade&source=email_reminder`)
  - 👥 **Add Members** (`/settings?action=add-member&source=email_reminder`)

---

### 2. Solo Household Owner Nudge (Day 3 Solo Household)
- **Classification**: 📢 **Marketing**
- **Trigger Condition**: Household was created 3 or more days ago (`DATE(h.created_at) <= CURRENT_DATE - INTERVAL '3 days'`).
- **Target Audience**: Household has only 1 member (`auth_household_members` count = 1).
- **Tracking**: `email_events` with `campaign = 'solo_nudge'` and `event_type = 'sent'`.
- **Content & Purpose**:
  - Gently nudges the owner to invite partner, family members, or roommates.
  - Highlights that **only the household pays for a Pro subscription ($1.99/mo or $9.99/yr)** and that invited members join, edit, and sync completely free.
  - Explains real-time list sync benefits: zero duplicate buys, items cross off live across devices, and no more texting back and forth while shopping.
- **Buttons**:
  - 👥 **Invite Household Members** (`/settings?action=add-member&source=email_solo_nudge`)
  - ⭐ **View Pro Plans** (`/settings?action=upgrade&source=email_solo_nudge`)

---

### 3. Trial Week 1 Check-in (Day 7)
- **Classification**: 📢 **Marketing**
- **Trigger Condition**: Household on `'trial'` status created 7 or more days ago (`DATE(h.created_at) <= CURRENT_DATE - INTERVAL '7 days'`).
- **Tracking**: `email_events` with `campaign = 'trial_week1'` and `event_type = 'sent'`.
- **Content & Purpose**:
  - Asks what they think of ListMate and how their first week went.
  - Highlights early upgrade options ($1.99/mo or $9.99/yr) while reassuring that **upgrading early still gives them their full 30-day trial period** (paid billing begins only after the 30-day trial concludes).
  - Recommends the **Feature Discovery Tips** in the app menu to learn about aisle auto-sorting, store filters (Patel Brothers, Costco, Trader Joe's), and multi-store planning.
- **Buttons**:
  - ⭐ **Upgrade Subscription** (`/settings?action=upgrade&source=email_trial_week1`)
  - 👥 **Add Members** (`/settings?action=add-member&source=email_trial_week1`)

---

### 4. Trial Week 3 Check-in (Day 21)
- **Classification**: 📢 **Marketing**
- **Trigger Condition**: Household on `'trial'` status created 21 or more days ago (`DATE(h.created_at) <= CURRENT_DATE - INTERVAL '21 days'`).
- **Tracking**: `email_events` with `campaign = 'trial_week3'` and `event_type = 'sent'`.
- **Content & Purpose**:
  - Check-in at 3 weeks (~9 days left in trial).
  - Reminds user to lock in their household plan ($1.99/mo or $9.99/yr) before trial expiration, preserving remaining free trial days.
  - Reminds that 1 subscription covers the entire household.
- **Buttons**:
  - ⭐ **Upgrade Subscription** (`/settings?action=upgrade&source=email_trial_week3`)
  - 👥 **Add Members** (`/settings?action=add-member&source=email_trial_week3`)

---

### 5. Activations (Day 3+ Inactive, 0 Items)
- **Classification**: 📢 **Marketing**
- **Trigger Condition**: Household created 3+ days ago with 0 items in `list_items`.
- **Tracking**: `email_events` with `campaign = 'activation'` and `event_type = 'sent'`.
- **Buttons**:
  - 🛒 **Add First Item** (`/?source=email_activation`)
  - 👥 **Invite Members** (`/settings?action=add-member&source=email_activation`)

---

### 6. Re-engagement (Day 14+ Inactive)
- **Classification**: 📢 **Marketing**
- **Trigger Condition**: Most recent item added was 14+ days ago.
- **Tracking**: `email_events` with `campaign = 'reengagement'` and `event_type = 'sent'` (sent only if no send in the last 30 days).
- **Buttons**:
  - 🛒 **Plan Your Next Trip** (`/?source=email_reengagement`)
  - 👥 **Invite Members** (`/settings?action=add-member&source=email_reengagement`)

---

## `email_events` Table Architecture

All email deliveries and SendGrid webhook telemetry events (sent, delivered, opened, clicked, bounced, etc.) are recorded in the `email_events` table:

| Column | Type | Description |
|---|---|---|
| `id` | `SERIAL PRIMARY KEY` | Auto-incrementing identifier. |
| `email` | `VARCHAR(255)` | Recipient email address. |
| `event_type` | `VARCHAR(50)` | `sent`, `delivered`, `open`, `click`, `bounce`, `dropped`, etc. |
| `campaign` | `VARCHAR(100)` | Campaign identifier (e.g. `solo_nudge`, `trial_week1`, `activation`). |
| `user_id` | `INTEGER` | Foreign key referencing `auth_users(id)`. |
| `household_id` | `INTEGER` | Foreign key referencing `auth_households(id)`. |
| `target_url` | `TEXT` | Target URL for `click` events. |
| `user_agent` | `TEXT` | User agent from webhook telemetry. |
| `ip_address` | `VARCHAR(45)` | IP address from webhook telemetry. |
| `sg_event_id` | `VARCHAR(100) UNIQUE` | Unique SendGrid event ID for idempotent webhook ingestion. |
| `sg_message_id` | `VARCHAR(100)` | SendGrid message ID. |
| `reason` | `TEXT` | Error reason for bounces/drops. |
| `event_timestamp` | `TIMESTAMP` | Timestamp when the event occurred. |
| `created_at` | `TIMESTAMP` | Record creation timestamp. |

---

## Testing & Maintenance
To run the script manually:
```bash
python scripts/cron_daily.py
```
