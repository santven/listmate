# ListMate Premium, Trial & Extension Architecture (`premium_flow.md`)

## 1. Executive Summary & Entitlement Model

ListMate provides shared grocery shopping and real-time pantry collaboration. Premium subscriptions are billed **per household**, not per user. One subscription covers all invited household members (spouses, roommates, family members), who can view, edit, and cross off items concurrently.

Subscriptions and trials are managed across three tiers:
1. **Early Adopters (Households 1 - 25)**: Lifetime complimentary access to ListMate Premium.
2. **Standard Trial Users (Households 26+)**: Default 15-day free trial on signup with access to an extension ladder.
3. **Legacy Households (Prior 30-Day Cohort)**: Grandfathered households that received 30 days upfront.

---

## 2. Household Status & Entitlements

The backend dynamically computes household permissions via `get_household_status()` in `shared/auth.py`:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Household Registration                          │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                     ┌─────────────┴─────────────┐
                     │                           │
          [Household ID <= 25]          [Household ID > 25]
                     │                           │
                     ▼                           ▼
        ┌─────────────────────────┐ ┌─────────────────────────┐
        │  Early Adopter Status   │ │    Standard Signup      │
        │  is_premium = TRUE      │ │  subscription_status =  │
        │  subscription_status =  │ │       'trial'           │
        │       'premium'         │ │  trial_ends_at =        │
        │  trial_ends_at = NULL   │ │   NOW() + 15 days       │
        │  (Lifetime / No Billing)│ └────────────┬────────────┘
        └─────────────────────────┘              │
                                                 ▼
                                    ┌─────────────────────────┐
                                    │ Trial Extension Ladder  │
                                    │ Tier 1: 15-Day Pass     │
                                    │ Tier 2: 7-Day Pass      │
                                    │ Max Total Trial: 37 Days│
                                    └─────────────────────────┘
```

### Database Schema for Entitlements (`auth_households`)
| Column | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `is_premium` | `BOOLEAN` | `FALSE` | High-level entitlement boolean. |
| `subscription_status` | `TEXT` | `'free'` | `'free'`, `'trial'`, `'active'`, `'premium'`, `'canceled'`, `'expired'`. |
| `trial_ends_at` | `TIMESTAMP` | `NULL` | Trial expiration timestamp. |
| `subscription_ends_at`| `TIMESTAMP` | `NULL` | Paid subscription expiration timestamp from RevenueCat. |
| `trial_extension_claimed_at` | `TIMESTAMP` | `NULL` | General extension timestamp (backward compatibility). |
| `trial_ext_15d_claimed_at` | `TIMESTAMP` | `NULL` | Timestamp when the 15-day extension was claimed. |
| `trial_ext_7d_claimed_at` | `TIMESTAMP` | `NULL` | Timestamp when the 7-day extension was claimed. |
| `downgraded_at` | `TIMESTAMP` | `NULL` | Timestamp when the household lapsed from Premium/Trial to Free. |
| `lifecycle_status` | `VARCHAR(30)`| `'active'` | Retention state machine (`'active'`, `'lapsed'`, `'dormant'`, `'sunset_pending'`, `'sunsetted'`). |

---

## 3. The Trial Extension Ladder

To recover lapsed households without aggressive immediate paywalls, ListMate offers a structured, capped **Extension Ladder** via `claim_trial_extension()`:

```
[Standard 15-Day Trial] ──► [Claim Tier 1: +15 Days] ──► [Claim Tier 2: +7 Days] ──► [Lifetime Cap: 37 Days]
```

### Progression Rules:
1. **Initial Trial**: 15 days from registration.
2. **Tier 1 (15-Day Extension)**:
   - Available via expired winback campaigns (`trial_winback_ext_15d`) or in-app settings.
   - When claimed, `trial_ends_at` is extended by 15 days from `GREATEST(trial_ends_at, NOW())`.
   - Records `trial_ext_15d_claimed_at = NOW()`.
3. **Tier 2 (7-Day Extension)**:
   - Offered via the Day 37 post-trial cron (`trial_ext_day7`) or winback passes (`trial_winback_ext_7d`).
   - When claimed, `trial_ends_at` is extended by 7 days from `GREATEST(trial_ends_at, NOW())`.
   - Records `trial_ext_7d_claimed_at = NOW()`.
4. **Legacy 30-Day Cohort Safeguard**:
   - Households that already received 30 days initial trial (`(trial_ends_at - created_at) >= 20 days`) are recognized as legacy.
   - To maintain fairness, legacy 30d households are eligible **only** for the final 7-day tier, capping their lifetime trial at **37 days (30 + 7)**.
   - *Exception*: If a 15-day winback email was explicitly sent (`campaign = 'trial_winback_ext_15d'`), the promised 15 days are honored retroactively.
5. **Idempotency & Double-Claim Prevention**:
   - Clicking a claim link repeatedly safely returns a message stating that the offer was already activated and displays remaining trial days.

---

## 4. Endpoints & Deep-Link Claim Routing

Users claim extensions via deep-links embedded in emails or in-app buttons:

### Web & In-App Routes:
* **Direct Settings Link**:
  ```
  GET /settings?action=claim-extension&tier=15d
  GET /settings?action=claim-extension&tier=7d
  ```
* **Dedicated Claim Route**:
  ```
  GET /claim-extension?tier=15d
  ```
* **Internal API Endpoint**:
  ```
  POST /api/household/claim-extension
  Content-Type: application/json
  Payload: {"tier": "15d"}
  ```
  **Response Payload**:
  ```json
  {
    "ok": true,
    "message": "🎉 15 extra days of ListMate Premium have been added to your trial!",
    "days": 15,
    "days_left": 15
  }
  ```

---

## 5. Free Mode & Soft Landing Restrictions

When a trial or paid subscription expires without renewal:
1. `is_premium` evaluates to `false`.
2. `downgraded_at` is set to `NOW()`.
3. **Owner Access**: The household owner retains full read/write access to their personal list.
4. **Secondary Members (Partner Friction)**:
   - In accordance with `FREE_TIER_MEMBER_LIMIT = 1`, additional members switch to `is_read_only = true`.
   - Secondary members cannot add or cross off items until the household upgrades or grants an extension.
5. **Spin-Off Feature**: Secondary members can spin off into their own personal household via `/api/household/spin-off`, migrating their existing store lists and items.

---

## 6. RevenueCat Webhook Integration

RevenueCat webhooks (`/api/revenuecat/webhook`) maintain real-time sync with Google Play Store and Apple App Store billing events:

| RevenueCat Event Type | Database `is_premium` | Database `subscription_status` | Operational Effect |
| :--- | :---: | :---: | :--- |
| `INITIAL_PURCHASE` | `true` | `'active'` | User purchased monthly ($1.99) or annual ($9.99) subscription. UI updates immediately. |
| `RENEWAL` | `true` | `'active'` | Billing period renewed. `subscription_ends_at` bumped forward. |
| `UNCANCELLATION` | `true` | `'active'` | User resumed auto-renew before current period ended. |
| `NON_RENEWING_PURCHASE` | `true` | `'active'` | One-time or promo purchase applied. |
| `CANCELLATION` | (unchanged) | `'canceled'` | Auto-renew turned off. Access remains active until `subscription_ends_at`. |
| `EXPIRATION` | `false` | `'expired'` | Period elapsed. Account safely lands in Free tier (`is_premium = false`). |

### Webhook Idempotency:
Webhook payloads verify the authorization header and record transaction tokens to prevent duplicate activations or race conditions.
