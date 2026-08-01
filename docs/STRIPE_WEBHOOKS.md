# Stripe Webhooks Architecture

## 1. Overview
ListMate uses Stripe webhooks to handle out-of-band events regarding user subscriptions, such as successful checkouts, subscription updates, renewals, cancellations, and expirations. This document outlines which events are processed and how they affect the household's subscription status in the database.

## 2. Events Processed

The ListMate backend (`app.py`) listens to a dedicated Stripe webhook endpoint (`/api/webhooks/stripe`). The following events are currently processed:

### `checkout.session.completed`
- **When it fires**: A user successfully completes a checkout session to subscribe to ListMate Premium.
- **Action**: Extracts the `customer` ID, `household_id`, and `current_period_end`.
- **Outcome**: Upgrades the household to Premium (`is_premium = True`), sets `subscription_status = 'active'`, and stores the `stripe_customer_id` and `subscription_ends_at` timestamps for tracking.

### `customer.subscription.created`
- **When it fires**: A new subscription is created on a customer's account (often right after a checkout session or via API).
- **Action**: Inspects the subscription status (e.g., `active`, `trialing`) and metadata. It pulls the `current_period_end` from the root object or from the first item in the `items.data` list if not available at the root.
- **Outcome**: Marks the household as premium, sets the status, and updates the `subscription_ends_at` timestamp.

### `customer.subscription.updated`
- **When it fires**: A subscription changes state. This handles auto-renewals, plan upgrades/downgrades, and users clicking "Cancel" in the Stripe Customer Portal.
- **Action**: We inspect `status`, `cancel_at_period_end`, `cancel_at`, and `canceled_at`.
- **Outcome**: 
  - If a user cancels their plan via the portal, Stripe sets `cancel_at_period_end = true`. We update the user's `subscription_status` to `canceled` but keep `is_premium = True` so they maintain access until their billing period ends (`subscription_ends_at`).
  - Upon a successful auto-renewal, the event updates the new `current_period_end` (extended by another month/year), and we bump the `subscription_ends_at` in the database.

### `customer.subscription.deleted`
- **When it fires**: A subscription reaches its absolute end. This occurs at the end of the billing period for a canceled subscription, or immediately if the subscription is revoked/voided by an admin or due to prolonged payment failures.
- **Action**: Finds the household by `stripe_customer_id`.
- **Outcome**: Instantly sets `is_premium = False`, `subscription_status = 'canceled'`, and updates `subscription_ends_at = NOW()`. The user loses Premium access immediately.

## 3. Subscription Expired vs Auto-Renewal vs Card Declines

- **Auto-Renewal**: When Stripe automatically charges a card and renews a subscription for the next cycle, Stripe fires `customer.subscription.updated` with the new `current_period_end`. Our system captures this and extends the user's `subscription_ends_at` date.
- **Card Decline (Past Due)**: If a payment fails, Stripe enters its retry logic. Typically, the subscription state changes to `past_due`, firing a `customer.subscription.updated` event. We currently map any state that is not `active` or `trialing` to `is_premium = False`. So if the status becomes `past_due` or `unpaid`, the user loses Premium benefits until they update their card.
- **Expiry / End of Cancellation**: When a user cancels, they retain access until `current_period_end`. At the exact moment it ends, Stripe fires `customer.subscription.deleted`. Our system catches this and fully revokes `is_premium`.

## 4. Why We Map Cancel_At to Canceled

When a user cancels their subscription, they don't immediately lose access. They retain access until the end of the current billing cycle. To provide a clear UI, when `cancel_at_period_end`, `cancel_at`, or `canceled_at` are set in a `customer.subscription.updated` event, we mark `subscription_status = 'canceled'` but keep `is_premium = True`. The frontend uses this to display "✨ Premium (Cancels MM/DD/YYYY)" so the user knows exactly when they will be downgraded.
