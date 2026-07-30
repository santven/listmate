# ListMate Premium & Trial Subscription Flow

## Registration & Onboarding
The application handles premium entitlements using a combination of early-adopter logic, trial periods, and RevenueCat integration.

1. **Early Adopters (Households 1 - 100):**
   - **`is_premium`**: `true`
   - **`subscription_status`**: `'premium'`
   - **Experience**: These users will *never* see the "Upgrade" button or trial banners. They have lifetime access to all premium features without expiration.

2. **Standard Users (Households 101+):**
   - **`is_premium`**: `true` (dynamically evaluated during the trial period)
   - **`subscription_status`**: `'trial'`
   - **`trial_ends_at`**: Set to 30 days from the date of registration.
   - **Experience**: During the 30-day window, these users have full access to all Premium features (e.g., AI Recipe Planner, ad-free experience). They will see a trial banner indicating how many days are left, and they will see the "Upgrade" button in settings, allowing them to purchase a subscription at any time.

## Trial Expiration & Upgrading
- **On Day 31 (Trial Expiry):**
  - If the user has not upgraded, the backend will dynamically evaluate their `is_premium` status as `false` because `now > trial_ends_at` and `subscription_status` is still `'trial'`. (Eventually, a webhook or lazy-evaluation will mark their status as `'expired'`).
  - **Experience**: The user loses access to Premium features, ads will appear, and they will be prompted to upgrade via the paywall modal if they try to access a premium feature (like the Recipe Planner).
- **Upgrading via RevenueCat:**
  - When the user upgrades (either during the trial or after expiration), the client-side app or RevenueCat webhook (`INITIAL_PURCHASE`) sets:
    - **`is_premium`**: `true`
    - **`subscription_status`**: `'active'`
  - **Experience**: The user regains or maintains full access to all Premium features. The UI removes trial banners and upgrade buttons, displaying a "Premium" badge.

## RevenueCat Webhook Mapping
RevenueCat events are mapped to our backend database (`auth_households`) as follows:

| RevenueCat Event Type | Database `is_premium` | Database `subscription_status` | Description |
| :--- | :--- | :--- | :--- |
| `INITIAL_PURCHASE` | `true` | `'active'` | User purchased a premium subscription. |
| `RENEWAL` | `true` | `'active'` | User's subscription renewed successfully. |
| `UNCANCELLATION` | `true` | `'active'` | User resumed their subscription before it expired. |
| `NON_RENEWING_PURCHASE` | `true` | `'active'` | User purchased a non-renewing premium package. |
| `CANCELLATION` | (unchanged) | `'canceled'` | User canceled their subscription. They retain premium access until the period ends (RevenueCat handles the expiration event later). |
| `EXPIRATION` | `false` | `'expired'` | User's subscription lapsed or canceled period ended. Premium access is revoked. |

