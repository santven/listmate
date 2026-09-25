# Daily Cron Job Scenarios & Automated Email Engine (`scripts/cron_daily.py`)

> **Related Architecture Specification**:
> For the comprehensive post-trial expiration cadence, partner friction recovery, dormancy state machine, 60-day breakup emails, 90-day deliverability sunsetting, and trial extension ladder architecture, see [`trial_and_retention_lifecycle_design.md`](./trial_and_retention_lifecycle_design.md).

---

## 1. Overview & Core Philosophy

The `scripts/cron_daily.py` script is ListMate's unified daily automation engine running at 3:00 AM UTC. It evaluates user, household, and invite states to send targeted lifecycle, onboarding, retention, and winback emails via SendGrid.

### Key Operational Rules:
1. **Unified Daily Cron**: All recurring daily checks are consolidated in `scripts/cron_daily.py`. No competing background email crons exist.
2. **Single Email Rule**: If a user qualifies for multiple events on the same day, `cron_daily.py` aggregates them into a single payload and sends **ONE** combined email (prioritizing the most critical alert) to avoid inbox fatigue.
3. **Idempotent Telemetry**: Every send is logged in `email_events` (`event_type = 'sent'`, `campaign = ...`) and timestamped on the parent table (`auth_households`, `invites`, or `auth_users`) to guarantee zero duplicate sends.
4. **PostgreSQL-Exclusive Architecture**: All queries use connection pooling (`db_pg.py`), parameterized statements, and strict `0` vs `None` checking.

---

## 2. Email Classification & Legal Compliance

Our email engine strictly distinguishes between **Marketing** (promotional, re-engagement, feature discovery) and **Transactional** (service continuity, billing, account security) emails to comply with CAN-SPAM, GDPR, and Apple Mail Privacy Protection (MPP):

| Email Category | Classification | Campaign Identifier | Target Audience / Trigger Condition |
| :--- | :--- | :--- | :--- |
| **Trial 3 Days Left** | ⚖️ **Transactional** | `trial_exp_3days` | Trial ends in 3 days; service continuity notice. |
| **Trial Ends Today (Day 0)** | ⚖️ **Transactional** | `trial_exp_today` | Trial ends today; soft landing to free tier reassurance. |
| **Paid Sub 3 Days Left** | ⚖️ **Transactional** | `sub_exp_3days` | Paid subscription renewal/lapse in 3 days. |
| **Paid Sub Ends Today** | ⚖️ **Transactional** | `sub_exp_today` | Paid subscription lapses today. |
| **Post-Trial Partner Nudge (Day 32)** | 📢 **Marketing** | `trial_lapsed_day2` | Multi-member households 2 days post-trial; highlights loss of 2-way live sync. |
| **Trial Extension Offer (Day 37)** | 📢 **Marketing** | `trial_ext_day7` | Unconverted households 7 days post-trial; complimentary 7-day trial extension offer. |
| **Trial Winback Pass (15d / 7d)** | 📢 **Marketing** | `trial_winback_ext_15d` / `trial_winback_ext_7d` | Long-term expired trial winback dispatch via `send_expired_trial_winback.py`. |
| **Breakup Permission Email (Day 60)** | 📢 **Marketing** | `breakup_day60` | Dormant households with 0 email opens in 45+ days; final opt-in permission check. |
| **Solo Household Nudge (Day 3)** | 📢 **Marketing** | `solo_nudge` | Single-member households on Day 3; encourages inviting partner/family. |
| **Store Nudge (Day 3)** | 📢 **Marketing** | `store_nudge` | Households on Day 3 with only General List; encourages adding custom store lists. |
| **Trial Week 1 Check-in (Day 7)** | 📢 **Marketing** | `trial_week1` | Active trial Day 7; feature discovery tips (aisle auto-sort, custom stores). |
| **Trial Week 3 Check-in (Day 21)** | 📢 **Marketing** | `trial_week3` | Active trial Day 21 (for legacy 30d trials); reminds to lock in annual/monthly upgrade. |
| **Activation (Day 3)** | 📢 **Marketing** | `activation` | Registered households with 0 list items after 3 days. |
| **Re-engagement (Day 14)** | 📢 **Marketing** | `reengagement` | Dormant households with no items added in 14+ days (max 1 send per 30 days). |
| **Pending Invite Reminder (Day 2)** | 📢 **Marketing** | `invite_reminder_day2` | Invitee has not accepted invite after 48 hours (5 days remaining). |
| **Pending Invite Final Urgency (Day 5)** | 📢 **Marketing** | `invite_reminder_day5` | Invitee has not accepted invite after 120 hours (2 days remaining). |
| **Expired Invite Notice (Day 7)** | ⚖️ **Transactional** | `invite_expired_inviter` | Sent to inviter/owner when an unaccepted invite expires after 7 days. |
| **Signup Abandonment (Day 2)** | 📢 **Marketing** | `signup_abandon_day2` | User registered 2+ days ago without creating or joining a household. |
| **Signup Abandonment (Day 5)** | 📢 **Marketing** | `signup_abandon_day5` | User registered 5+ days ago without a household; value & guidance tips. |
| **Signup Abandonment (Day 7)** | 📢 **Marketing** | `signup_abandon_day7` | Final notice before unattached registration account prune. |
| **Lifetime Premium Monthly Digest** | 📢 **Marketing** | `lifetime_digest` | Monthly usage digest & productivity report for Early Adopter/Lifetime owners. |

### Legal Safeguards:
1. **`marketing_opt_in` Enforcement**: All marketing queries strictly check `AND COALESCE(ahm.marketing_opt_in, TRUE) = TRUE`. Opted-out users never receive marketing touches.
2. **Universal Unsubscribe**: Plaintext and HTML tokenized unsubscribe footers (`_get_unsub_blocks`) are appended to all marketing templates.
3. **Suppression Checking**: Every query verifies recipient email against `email_suppressions` (hard bounces, spam complaints, unsubscribes).

---

## 3. Detailed Campaign Scenarios

### 1. Expirations (Trial & Paid Subscription Ending Notices)
- **Classification**: ⚖️ **Transactional** (Always sent regardless of marketing opt-in).
- **Triggers**:
  - `trial_exp_3days`: `subscription_status = 'trial'` and `trial_ends_at = CURRENT_DATE + INTERVAL '3 days'`.
  - `trial_exp_today`: `subscription_status = 'trial'` and `trial_ends_at = CURRENT_DATE`.
  - `sub_exp_3days`: `subscription_status IN ('premium', 'active')` and `subscription_ends_at = CURRENT_DATE + INTERVAL '3 days'`.
  - `sub_exp_today`: `subscription_status IN ('premium', 'active')` and `subscription_ends_at = CURRENT_DATE`.
- **Action Buttons**:
  - ⭐ **Upgrade Household** (`/settings?action=upgrade&source=email_reminder`)
  - 👥 **Add Members** (`/settings?action=add-member&source=email_reminder`)

---

### 2. Post-Trial Partner Nudge (Day 32 — 2 Days Post-Trial)
- **Classification**: 📢 **Marketing**
- **Trigger**: `DATE(downgraded_at) = CURRENT_DATE - INTERVAL '2 days'` (or `trial_ends_at = CURRENT_DATE - INTERVAL '2 days'`), household is on free tier (`is_premium = FALSE`), and household has **2 or more members**.
- **Campaign Identifier**: `trial_lapsed_day2`
- **Value Proposition**:
  - Explains that secondary household members are now in read-only mode.
  - Highlights the real-time sync friction: spouse/partner cannot cross off items or add last-minute dinner ingredients while at the store.
  - Reassures that all lists, custom stores, and aisle orders are preserved and restore instantly upon upgrade.
- **Action Buttons**:
  - 👥 **Restore Partner Sync** (`/settings?action=upgrade&source=email_lapsed_day2`)

---

### 3. Post-Trial 7-Day Extension Offer (Day 37 — 7 Days Post-Trial)
- **Classification**: 📢 **Marketing**
- **Trigger**: `DATE(downgraded_at) = CURRENT_DATE - INTERVAL '7 days'` (or `trial_ends_at = CURRENT_DATE - INTERVAL '7 days'`), household unconverted (`is_premium = FALSE`), and `trial_ext_7d_claimed_at IS NULL`.
- **Campaign Identifier**: `trial_ext_day7`
- **Value Proposition**:
  - Offers a complimentary 7-day extension pass with zero credit card required.
  - Directly addresses hesitation and allows one final week of full Premium collaboration.
- **Action Buttons**:
  - 🎁 **Claim 7-Day Extension Pass** (`/settings?action=claim-extension&tier=7d&source=email_trial_ext_day7`)
  - ⭐ **Upgrade Subscription** (`/settings?action=upgrade&source=email_trial_ext_day7`)

---

### 4. Breakup Permission Email (Day 60 — 30 Days Post-Trial)
- **Classification**: 📢 **Marketing**
- **Trigger**: Household trial ended 30 days ago (`DATE(downgraded_at) = CURRENT_DATE - INTERVAL '30 days'`), household has 0 email opens in 45+ days, and lifecycle status is not already `sunsetted` or `sunset_pending`.
- **Campaign Identifier**: `breakup_day60`
- **Behavioral Impact**:
  - Sets `lifecycle_status = 'sunset_pending'`.
  - Asks permission before silencing notifications: *"Should we stop emailing you?"*
  - Provides a single-click button to keep account active, and a clear button to unsubscribe.
- **Action Buttons**:
  - ✨ **Keep My Free Account Active** (`/api/household/keep-active` or `/settings?action=keep-active`)
  - 🛑 **Unsubscribe from Updates** (Unsubscribe link)

---

### 5. Solo Household Owner Nudge (Day 3)
- **Classification**: 📢 **Marketing**
- **Trigger**: Household created 3+ days ago with exactly 1 member (`auth_household_members` count <= 1).
- **Campaign Identifier**: `solo_nudge`
- **Value Proposition**: Reminds owner that only 1 subscription is needed per household; invited family and roommates join and sync 100% free.
- **Action Buttons**:
  - 👥 **Invite Household Members** (`/settings?action=add-member&source=email_solo_nudge`)

---

### 6. Store Nudge (Day 3)
- **Classification**: 📢 **Marketing**
- **Trigger**: Household created 3+ days ago with at least 1 item in `list_items`, but NO custom stores created (only default "General List").
- **Campaign Identifier**: `store_nudge`
- **Value Proposition**: Educates user on creating store-specific lists (e.g. Costco, Trader Joe's, Safeway) to unlock aisle categorization and faster grocery runs.
- **Action Buttons**:
  - ➕ **Add a Store** (`/?action=add_store&source=email_store_nudge`) — Deep-links to home and auto-focuses the new store input with a glowing discovery highlight.

---

### 7. Trial Check-ins (Week 1 & Week 3)
- **Classification**: 📢 **Marketing**
- **Trigger**:
  - `trial_week1`: Active trial created 7+ days ago.
  - `trial_week3`: Active trial created 21+ days ago.
- **Value Proposition**: Feature discovery tips, aisle auto-sort highlights, and early subscription options ($1.99/mo or $9.99/yr).

---

### 8. Activation (Day 3) & Re-engagement (Day 14)
- **Classification**: 📢 **Marketing**
- **Trigger**:
  - `activation`: Created 3+ days ago with 0 items on any list.
  - `reengagement`: Most recent list item added was 14+ days ago (maximum 1 send per 30 days).

---

### 9. Pending & Expired Household Invites Lifecycle
- **Classification**:
  - `invite_reminder_day2` (📢 Marketing): Sent to invitee email 48 hours after invite creation.
  - `invite_reminder_day5` (📢 Marketing): Sent to invitee email 120 hours after creation (2 days before expiry).
  - `invite_expired_inviter` (⚖️ Transactional): Sent to the inviter/owner on Day 7 when an unaccepted invite expires, prompting them to resend.

---

### 10. Signup Abandonment Nudges (Days 2, 5, and 7)
- **Classification**: 📢 **Marketing**
- **Trigger**: Registered users in `auth_users` with `household_id = 0` (unattached to any household):
  - `signup_abandon_day2`: Gentle reminder after 48 hours to complete setup or accept an invite.
  - `signup_abandon_day5`: Value walkthrough explaining shared shopping workflows.
  - `signup_abandon_day7`: Final urgency notice before automated registration cleanup.
- **Engagement-Aware Pruning**: On Day 10+, `cleanup_abandoned_signups()` securely prunes unattached abandoned signups *unless* the user clicked an email in the last 14 days or opened an email in the last 7 days.

---

### 11. Lifetime Premium Monthly Digest
- **Classification**: 📢 **Marketing**
- **Campaign Identifier**: `lifetime_digest`
- **Trigger**: Dispatched on the 1st of each month to Early Adopter and Lifetime households (`is_premium = TRUE` and `subscription_status = 'premium'`).
- **Content**: Summarizes monthly items crossed off, store visits, top shopping destinations, and active household collaborators.

---

## 4. `email_events` Telemetry & Webhook Architecture

All email delivery actions and incoming SendGrid webhook events (`/api/webhooks/sendgrid`) stream directly to the `email_events` table:

```sql
CREATE TABLE IF NOT EXISTS email_events (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    event_type VARCHAR(50) NOT NULL,      -- sent, delivered, open, click, bounce, dropped, spamreport
    campaign VARCHAR(100),                -- e.g. trial_ext_day7, trial_winback_ext_15d, solo_nudge
    user_id INTEGER REFERENCES auth_users(id) ON DELETE SET NULL,
    household_id INTEGER REFERENCES auth_households(id) ON DELETE SET NULL,
    target_url TEXT,                      -- Captured on 'click' events
    user_agent TEXT,
    ip_address VARCHAR(45),
    sg_event_id VARCHAR(100) UNIQUE,      -- Idempotency key from SendGrid
    sg_message_id VARCHAR(100),
    reason TEXT,                          -- Reason for bounce or drop
    event_timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

### Telemetry Intent Resolution:
* **Passive Opens (`open`)**: Updates `last_email_opened_at` on `auth_households`. Resets the 60-day sunset clock. Does **not** trigger reactive emails to avoid Apple MPP privacy pre-fetch distortion.
* **Active Clicks (`click`)**: Updates `last_email_clicked_at` on `auth_households`. Instantly transitions household `lifecycle_status` back to `'active'`, logging intent.

---

## 5. Manual Execution & Verification

Run the daily cron runner locally or in a staging container:
```bash
# Execute full daily sweep
python scripts/cron_daily.py

# Execute specific target tests
python -c "import scripts.cron_daily as cd; cd.test_lifetime_digest(target_hhid=1)"
```

---

## 6. Known Edge Cases & Tracking Issues

| Issue | Title & Description | Dynamic Status | Area |
| :---: | :--- | :---: | :---: |
| **[#510](https://github.com/santven/listmate/issues/510)** | **Ensure `downgraded_at` is populated when trial elapses**<br>Dynamic status check in `get_household_status()` does not fire PostgreSQL trigger, leaving `downgraded_at` NULL until an external write. | [![Issue 510](https://img.shields.io/github/issues/detail/state/santven/listmate/510?label=Status)](https://github.com/santven/listmate/issues/510) | Database / Lifecycle |
| **[#511](https://github.com/santven/listmate/issues/511)** | **Replace strict date equality with bounded window for lifecycle emails**<br>Strict equality `DATE(...) = CURRENT_DATE - INTERVAL 'X days'` causes emails to be permanently skipped if a single daily run is missed or delayed. | [![Issue 511](https://img.shields.io/github/issues/detail/state/santven/listmate/511?label=Status)](https://github.com/santven/listmate/issues/511) | Cron Engine |
| **[#513](https://github.com/santven/listmate/issues/513)** | **Make `send_expired_trial_winback.py` email check tier-aware**<br>`STARTS_WITH(ee.campaign, 'trial_winback_ext_')` in the winback script permanently blocks a lapsed household from getting the 7d winback pass if they received the 15d pass in the past. | [![Issue 513](https://img.shields.io/github/issues/detail/state/santven/listmate/513?label=Status)](https://github.com/santven/listmate/issues/513) | Winback Script |
