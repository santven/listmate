# Daily Cron Job Scenarios (`scripts/cron_daily.py`)

## Overview
The `cron_daily.py` script is designed to run daily (e.g., via a scheduled task or cron job) to evaluate user and household states and send automated emails to drive engagement, retention, and conversion.

The script aggregates notifications for a single user. If a user qualifies for multiple events on the same day, they receive a single combined notice rather than multiple separate emails.

## Scenarios Evaluated

### 1. Expirations (Trial Ending Warnings)
**Trigger Condition:** The script looks for households where `subscription_status` is `'trial'`.
**Target Dates:** It checks if the `trial_ends_at` date is either exactly **today (0 days left)** or exactly **3 days from today**.
**Action:**
- Sends a "trial ending soon" email with the `days_left` variable.
- For 3 days left, the email acts as a reminder to subscribe.
- For 0 days left (today), the email acts as a final warning that premium features and sync will be locked unless they upgrade.

### 2. Activations (Day 3 Inactive)
**Trigger Condition:** The script looks for households that were created exactly **3 days ago**.
**Condition:** It checks the `list_items` table. If the household has exactly **0 list items** added, the users are flagged.
**Action:**
- Sends an "activation/onboarding" email.
- This email is designed to help the user get started, explaining how to add items to their list or use the recipe features.

### 3. Re-engagement (Day 14 Inactive)
**Trigger Condition:** The script looks for households where the most recent item added to the `list_items` table was exactly **14 days ago**.
**Action:**
- Sends a "we miss you / re-engagement" email.
- The email is meant to draw the user back to the app if they have stopped using it for two weeks.

### 4. Combined Notifications
**Trigger Condition:** If a user triggers more than one of the above scenarios (e.g., their trial is expiring in 3 days AND they haven't added an item in 14 days, or their trial expires today AND they never added an item after 3 days).
**Action:**
- The script aggregates the events using a dictionary keyed by email address.
- Instead of spamming the user with two or three emails, the script uses the `send_combined_notice(email, user_name, events)` function from `email_helper.py` to send a single email addressing the multiple states.

## Testing & Maintenance
To run the script manually for testing:
```bash
python scripts/cron_daily.py
```
*Note: Make sure the environment variables (like Database connection strings and Email API keys) are configured correctly.*
