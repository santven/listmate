# Post-Trial Lifecycle, Retention & Deliverability Architecture

> **Cross-Reference & Two-Way Linkage**:
> * **Operational Daily Cron**: See [`cron_daily_scenarios.md`](./cron_daily_scenarios.md) for current active daily email scenarios, SendGrid telemetry tables, and single-email aggregation rules.
> * **Tracking GitHub Issues**: Linked to [#454](https://github.com/santven/listmate/issues/454) (Phase 1), [#455](https://github.com/santven/listmate/issues/455) (Phase 2), and [#456](https://github.com/santven/listmate/issues/456) (Phase 3).

---

## 1. Executive Summary & Design Goals

When users reach the end of their 30-day trial without upgrading, their households automatically transition to single-user Free mode. Without structured follow-up, multi-member households experience sudden partner-sync friction, dormant users remain on broadcast lists indefinitely, and high-intent email clicks are lost without dedicated landing flows.

This architecture establishes a **clean, state-driven lifecycle engine** that balances:
1. **Conversion Recovery**: High-empathy prompts highlighting multi-shopper sync friction and trial extensions.
2. **Deliverability & Sender Reputation**: Strict sunsetting rules to avoid emailing non-responsive inboxes, preserving high inbox placement with Gmail, Apple Mail, and Yahoo.
3. **Behavioral Intent Loops**: Distinguishing between passive opens (Apple MPP) and active clicks to deliver frictionless deep-link reactivation.

---

## 2. Determining a "Trial-Ended" User

A user's household is considered **Trial Ended** through two coordinated layers:

### A. Real-Time Application Layer (`shared/auth.py`)
On every request, `get_household_status()` dynamically computes subscription privileges:
```python
is_prem = bool(hh.get("is_premium", False))
sub_status = hh.get("subscription_status", "free")
trial_ends_at = hh.get("trial_ends_at")

# If trial timestamp has elapsed:
if sub_status == 'trial' and trial_ends_at:
    if trial_ends_at > datetime.datetime.now(datetime.timezone.utc):
        is_prem = True   # Active trial
    else:
        is_prem = False  # Trial Ended
```
* **Immediate Soft Landing**: Account switches to Free mode (`is_premium = False`, `FREE_TIER_MEMBER_LIMIT = 1`).
* **Multi-User Friction**: Secondary members are assigned `is_read_only = True`. All past items and custom stores are 100% preserved.

### B. Database & Cron Layer (`scripts/cron_daily.py`)
Because a dormant user may not log in on Day 31, the cron evaluates timestamps relative to `CURRENT_DATE`:
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

Rather than scattering multiple ad-hoc date checks across queries, every household belongs to a defined **Lifecycle State**:

```
 ┌─────────────┐  Day 30 Lapses   ┌─────────────┐  Day 45+ No Activity  ┌─────────────┐
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

| State | Definition | Communication Allowed |
| :--- | :--- | :--- |
| `ACTIVE` | Currently in 30-day trial or active paid subscriber. | Full onboarding, transactional notices, feature tips. |
| `LAPSED` | Trial ended (Days 31–44), account downgraded to Free. | Post-trial partner friction (Day 32) & 7-day extension (Day 37). |
| `DORMANT` | No app items added in 14+ days, trial lapsed (Days 45–60). | Max 1 re-engagement notice per 30 days. |
| `SUNSET_PENDING` | 0 opens in 45+ days across last 3 emails (Day 60). | Exactly 1 "Breakup / Permission" email. |
| `SUNSETTED` | 0 engagement after breakup email (Day 90+). | **Zero marketing emails.** Pure account transactions only. |

---

## 4. End-to-End Campaign Schedule

All campaigns are strictly governed by ListMate's **Single Email Rule** (`scripts/cron_daily.py`), ensuring no user receives more than 1 email per day:

| Stage | Trigger Timing | Campaign Identifier | Target Audience | Primary Focus & Value Prop |
| :--- | :---: | :--- | :--- | :--- |
| **Pre-Expiry** | Day 27 (T-3d) | `trial_exp_3days` | All Trial Households | 3-day advance notice; review month's value & store items. |
| **Pre-Expiry** | Day 30 (T-0d) | `trial_exp_today` | All Trial Households | Trial concludes tonight; soft landing reassurance. |
| **Lapsed** | Day 32 (T+2d) | `trial_lapsed_day2` | Multi-Member (2+ users) | Highlight loss of two-way partner sync and read-only friction. |
| **Lapsed** | Day 37 (T+7d) | `trial_ext_day7` | All Lapsed Households | Complimentary 7-day trial extension or intro discount. |
| **Dormant** | Day 45 (T+15d) | `reengagement` | Idle >14 days | Showcase what's new (aisle sorting, new store catalogs). |
| **Breakup** | Day 60 (T+30d) | `breakup_day60` | 0 opens in 45+ days | "Should we stop emailing you?" with 1-click preference buttons. |
| **Sunset** | Day 90+ | *(Internal)* | 0 opens / 0 app visits | Automatically mute marketing; preserve domain sender score. |

---

## 5. Behavioral Ingestion & Intent Loops

SendGrid Event Webhooks (`/api/webhooks/sendgrid`) feed real-time signals into the retention engine:

```
User Action                 System Response
────────────────────────────────────────────────────────────────────────────
User OPENS Email       ──►  • Updates `last_email_opened_at = NOW()`.
(Passive Intent)            • Resets the 60-day sunset clock.
                            • Keeps user in low-frequency monthly digest tier.
                            • (Does NOT trigger an automated email to avoid Apple MPP false-positives).

User CLICKS Link       ──►  • Updates `last_email_clicked_at = NOW()`.
(High Intent)               • Instantly transitions state to `ACTIVE`.
                            • Deep links user directly to their store aisle.
                            • Triggers contextual in-app modal (e.g., 7-day extension claim).
                            • If 0 items are added within 24 hours: 1-to-1 founder check-in nudge.

User UNSUBSCRIBES      ──►  • Writes email immediately to `email_suppressions`.
or Hard Bounces             • Permanently excluded across all cron queries.
```

---

## 6. Database Schema Additions

To support this engine without touching existing table structures, three clean fields are added to `auth_households`:

```sql
-- Phase 1 & 2 Migration
ALTER TABLE auth_households 
  ADD COLUMN IF NOT EXISTS lifecycle_status VARCHAR(30) DEFAULT 'active',
  ADD COLUMN IF NOT EXISTS email_trial_lapsed_day2_sent_at TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS email_trial_ext_day7_sent_at TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS last_email_opened_at TIMESTAMP WITH TIME ZONE,
  ADD COLUMN IF NOT EXISTS last_email_clicked_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX IF NOT EXISTS idx_households_lifecycle ON auth_households(lifecycle_status);
```

---

## 7. Phased Implementation Roadmap

* **Phase 1 ([Issue #454](https://github.com/santven/listmate/issues/454))**: Post-trial partner friction campaign (`trial_lapsed_day2`) and 7-day extension campaign (`trial_ext_day7`) in `cron_daily.py`.
* **Phase 2 ([Issue #455](https://github.com/santven/listmate/issues/455))**: Dormancy lifecycle engine, Day 60 Breakup email (`breakup_day60`), and Day 90 deliverability sunsetting.
* **Phase 3 ([Issue #456](https://github.com/santven/listmate/issues/456))**: Click-to-app intent loop, token-based deep-link authentication, and in-app welcome modals.
