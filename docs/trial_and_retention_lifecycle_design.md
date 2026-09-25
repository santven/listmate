# Post-Trial Lifecycle, Retention & Deliverability Architecture (`trial_and_retention_lifecycle_design.md`)

> **Cross-Reference & Two-Way Linkage**:
> * **Operational Daily Cron**: See [`cron_daily_scenarios.md`](./cron_daily_scenarios.md) for full email scenarios, single-email aggregation rules, and SendGrid telemetry schemas.
> * **Premium & Extension Engine**: See [`premium_flow.md`](./premium_flow.md) for trial extension ladder progression and RevenueCat billing details.
> * **Tracking GitHub Issues**: Linked to [#454](https://github.com/santven/listmate/issues/454) (Phase 1), [#455](https://github.com/santven/listmate/issues/455) (Phase 2), and [#456](https://github.com/santven/listmate/issues/456) (Phase 3).

---

## 1. Executive Summary & Design Goals

When users reach the end of their trial without upgrading, their households automatically transition to single-user Free mode. Without structured lifecycle management, multi-member households experience sudden partner-sync friction, dormant inboxes stay on broadcast lists indefinitely, and email deliverability suffers.

This architecture establishes a **clean, state-driven retention and deliverability engine**:
1. **Conversion Recovery**: High-empathy prompts highlighting multi-shopper sync friction (`trial_lapsed_day2`) and extension passes (`trial_ext_day7`, `trial_winback_ext_15d`).
2. **Deliverability & Sender Reputation**: Strict sunsetting rules to avoid emailing non-responsive inboxes, preserving top-tier inbox placement with Gmail, Apple Mail, and Yahoo.
3. **Intent Loop Automation**: Distinguishing between passive opens (Apple MPP) and active clicks to deliver frictionless deep-link reactivations.

---

## 2. Determining a "Trial-Ended" Household

A household is identified as **Trial Ended** across two coordinated layers:

### A. Real-Time Application Layer (`shared/auth.py`)
On every request, `get_household_status()` dynamically computes subscription privileges:
```python
is_prem = bool(hh.get("is_premium", False))
sub_status = hh.get("subscription_status", "free")
trial_ends_at = hh.get("trial_ends_at")

# If trial timestamp has elapsed:
if sub_status == 'trial' and trial_ends_at:
    now = datetime.datetime.now(datetime.timezone.utc)
    if trial_ends_at > now:
        is_prem = True   # Active trial
    else:
        is_prem = False  # Trial Ended
```
* **Immediate Soft Landing**: Account switches to Free mode (`is_premium = False`, `FREE_TIER_MEMBER_LIMIT = 1`).
* **Multi-User Friction**: Secondary members are assigned `is_read_only = True`. All past items, stores, and custom categories are 100% preserved.

### B. Database & Cron Layer (`scripts/cron_daily.py`)
Because a dormant user may not log in on the exact day their trial lapses, the daily cron evaluates timestamps relative to `CURRENT_DATE`:
```sql
SELECT h.id, h.name, u.email, u.name,
       COALESCE(h.downgraded_at, h.trial_ends_at) as ended_at,
       CURRENT_DATE - DATE(COALESCE(h.downgraded_at, h.trial_ends_at)) as days_since_ended
FROM auth_households h
JOIN auth_users u ON u.id = h.owner_id
WHERE h.is_premium = FALSE
  AND (
      (h.subscription_status = 'trial' AND h.trial_ends_at <= NOW())
      OR h.subscription_status IN ('expired', 'free')
  );
```

---

## 3. The Lifecycle State Machine

Rather than scattering ad-hoc date checks across queries, every household belongs to a defined **Lifecycle State** (`lifecycle_status`):

```
 ┌─────────────┐  Trial Lapses    ┌─────────────┐  Day 45+ No Items     ┌─────────────┐
 │ ACTIVE /    ├─────────────────►│   LAPSED    ├──────────────────────►│   DORMANT   │
 │ TRIALING    │                  │(Days 31-44) │                       │(Days 45-60) │
 └──────▲──────┘                  └──────┬──────┘                       └──────┬──────┘
        │                                │                                     │
        │ ◄─── ANY App Activity or       │                                     ▼ Day 60 No Opens
        │      Email Click Instantly     │                              ┌───────────────┐
        │      Restores Active State     │                              │SUNSET_PENDING │ (Breakup Email)
        │                                │                              └──────┬────────┘
        │                                │                                     │
        │                                │                                     ▼ Day 90 No Opens
        │                                │                              ┌───────────────┐
        └────────────────────────────────┴──────────────────────────────┤   SUNSETTED   │ (Muted)
                                                                        └───────────────┘
```

| State | Definition | Permitted Communications |
| :--- | :--- | :--- |
| `active` | Active trial, paid subscriber, or recently active user. | Full onboarding, transactional notices, discovery tips. |
| `lapsed` | Trial ended (Days 1–14 post-trial); account downgraded to Free. | Post-trial partner friction (`trial_lapsed_day2`) & 7-day extension (`trial_ext_day7`). |
| `dormant` | No app items added in 14+ days, trial lapsed. | Re-engagement notice (max 1 send per 30 days). |
| `sunset_pending` | 0 opens in 45+ days across recent emails. | Exactly 1 "Breakup / Permission" email (`breakup_day60`). |
| `sunsetted` | 0 engagement after breakup email (Day 90+). | **Zero marketing emails.** Essential account transactions only. |

---

## 4. End-to-End Retention & Extension Schedule

All campaigns are strictly governed by ListMate's **Single Email Rule** (`scripts/cron_daily.py`), ensuring no user receives more than 1 email per day:

| Stage | Trigger Timing | Campaign Identifier | Target Audience | Primary Focus & Value Prop |
| :--- | :---: | :--- | :--- | :--- |
| **Pre-Expiry** | T-3d | `trial_exp_3days` | All Trial Households | 3-day advance notice; review month's value & store items. |
| **Pre-Expiry** | T-0d | `trial_exp_today` | All Trial Households | Trial concludes tonight; soft landing reassurance. |
| **Lapsed** | T+2d (Day 32) | `trial_lapsed_day2` | Multi-Member (2+ users) | Highlight loss of two-way partner sync and read-only friction. |
| **Lapsed** | T+7d (Day 37) | `trial_ext_day7` | All Lapsed Households | Complimentary 7-day trial extension offer. |
| **Winback** | Post-Day 45 | `trial_winback_ext_15d` | Expired Households | Re-engagement with 15-day complimentary pass via `send_expired_trial_winback.py`. |
| **Winback** | Post-Day 60 | `trial_winback_ext_7d` | Expired (15d Claimed) | Secondary winback pass offering final 7-day extension. |
| **Breakup** | T+30d (Day 60) | `breakup_day60` | 0 opens in 45+ days | "Should we stop emailing you?" with 1-click preference buttons. |
| **Sunset** | Day 90+ | *(Internal Engine)*| 0 opens / 0 app visits | Automatically mute marketing; preserve domain sender score. |

---

## 5. Trial Extension Ladder Progression

ListMate implements a tiered extension model to provide generous evaluation time while capping lifetime free usage:

```
[Standard 15-Day Trial]
         │
         ▼
[Claim Tier 1: 15-Day Pass]  ──►  trial_ext_15d_claimed_at = NOW() (Total: 30 Days)
         │
         ▼
[Claim Tier 2: 7-Day Pass]   ──►  trial_ext_7d_claimed_at = NOW() (Total: 37 Days Capped)
         │
         ▼
[Lifetime Limit Reached]     ──►  "Your household has already claimed all complimentary extensions."
```

### Retroactive Legacy Safeguard:
Households from the legacy 30-day trial cohort have already enjoyed 30 initial trial days. They are routed directly to the final 7-day tier (`trial_ext_7d_claimed_at`), capping lifetime access at 37 days (30 + 7). If an email explicitly promised `trial_winback_ext_15d`, the system honors the full 15 days.

---

## 6. Behavioral Ingestion & Intent Loops

SendGrid Event Webhooks (`/api/webhooks/sendgrid`) feed real-time signals into the retention engine:

```
User Action                 System Response
────────────────────────────────────────────────────────────────────────────
User OPENS Email       ──►  • Updates `last_email_opened_at = NOW()`.
(Passive Intent)            • Resets the 60-day sunset clock.
                            • Keeps user in low-frequency monthly digest tier.
                            • (Does NOT trigger an automated email to avoid Apple MPP false-positives).

User CLICKS Link       ──►  • Updates `last_email_clicked_at = NOW()`.
(High Intent)               • Instantly transitions state to `active`.
                            • Deep links user directly to their store aisle or settings modal.
                            • Activates extension pass seamlessly via token/cookie.

User UNSUBSCRIBES      ──►  • Writes email immediately to `email_suppressions`.
or Hard Bounces             • Permanently excluded across all future cron queries.
```

---

## 7. Database Schema Reference (`auth_households`)

To support lifecycle evaluation without extra tables, these fields are maintained directly in `auth_households`:

```sql
ALTER TABLE auth_households 
  ADD COLUMN IF NOT EXISTS lifecycle_status VARCHAR(30) DEFAULT 'active',
  ADD COLUMN IF NOT EXISTS email_trial_lapsed_day2_sent_at TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS email_trial_ext_day7_sent_at TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS trial_extension_claimed_at TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS trial_ext_15d_claimed_at TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS trial_ext_7d_claimed_at TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS last_email_opened_at TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS last_email_clicked_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX IF NOT EXISTS idx_households_lifecycle ON auth_households(lifecycle_status);
```

---

## 8. Architectural Edge Cases & Tracking Issues

The following active edge cases have been identified through code auditing. Each issue is linked to its GitHub tracking record with a real-time status badge that updates automatically:

| Issue | Title & Description | Dynamic Status | Area |
| :---: | :--- | :---: | :---: |
| **[#510](https://github.com/santven/listmate/issues/510)** | **Ensure `downgraded_at` is populated when trial elapses**<br>Dynamic status check in `get_household_status()` does not trigger PostgreSQL `update_downgraded_at` trigger, leaving `downgraded_at` NULL until an external write. | [![Issue 510](https://img.shields.io/github/issues/detail/state/santven/listmate/510?label=Status)](https://github.com/santven/listmate/issues/510) | Database / Lifecycle |
| **[#511](https://github.com/santven/listmate/issues/511)** | **Replace strict date equality with bounded window for lifecycle emails**<br>Strict equality `DATE(...) = CURRENT_DATE - INTERVAL 'X days'` in `cron_daily.py` causes emails to be permanently skipped if a single daily run is missed or delayed. | [![Issue 511](https://img.shields.io/github/issues/detail/state/santven/listmate/511?label=Status)](https://github.com/santven/listmate/issues/511) | Cron Engine |
| **[#512](https://github.com/santven/listmate/issues/512)** | **Clarify and scope extension claim permissions for multi-member households**<br>Non-owner members can trigger `/api/household/claim-extension`, which consumes the household's one-time bonus extension pass without owner approval. | [![Issue 512](https://img.shields.io/github/issues/detail/state/santven/listmate/512?label=Status)](https://github.com/santven/listmate/issues/512) | Auth & Permissions |
| **[#513](https://github.com/santven/listmate/issues/513)** | **Make `send_expired_trial_winback.py` email check tier-aware**<br>`STARTS_WITH(ee.campaign, 'trial_winback_ext_')` in the winback script permanently blocks a lapsed household from getting the 7d winback pass if they received the 15d pass in the past. | [![Issue 513](https://img.shields.io/github/issues/detail/state/santven/listmate/513?label=Status)](https://github.com/santven/listmate/issues/513) | Winback Script |
