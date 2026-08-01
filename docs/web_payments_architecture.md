# Web Payments Architecture: RevenueCat & Stripe

## 1. Overview
ListMate uses RevenueCat as the central source of truth for cross-platform subscriptions (iOS, Android, and Web). For web payments, RevenueCat integrates with Stripe. Stripe handles the actual credit card processing, vaulting, and recurring billing, while RevenueCat normalizes these events into a standard format for our backend.

## 2. The Purchase Flow
1. **User Intent:** A free user on the web app clicks "Upgrade to Pro".
2. **RevenueCat Web Billing Link:** The frontend fetches (or constructs) a RevenueCat Web Billing link specific to that user's App User ID (which is their ListMate Household ID / User ID).
3. **Stripe Checkout:** The user is redirected to a hosted Stripe Checkout page. Stripe knows who the user is because RevenueCat passed the App User ID to Stripe during link generation.
4. **Completion & Redirect:** After payment, Stripe redirects the user back to ListMate (e.g., `/settings?purchase=success`).
5. **Webhook Fulfillment:** Stripe notifies RevenueCat of the successful payment. RevenueCat fires an `INITIAL_PURCHASE` webhook to our backend. Our backend upgrades the household to `is_premium = true`.
6. **Frontend Polling:** Because the webhook can take a few seconds, the frontend briefly short-polls the `/api/auth/household` endpoint. Once `is_premium` is true, it shows the success UI.

## 3. Auto-Renewal Flow
- Stripe is the billing engine. Every month/year, Stripe automatically charges the vaulted credit card.
- Upon a successful charge, Stripe sends a webhook to RevenueCat.
- RevenueCat normalizes this and fires a `RENEWAL` webhook to the ListMate backend.
- The ListMate database updates identically to an Android or iOS renewal.

## 4. Cancellation Flow & The Stripe Customer Portal
Web users cannot manage subscriptions via Google Play or the App Store. Instead, they use the **Stripe Customer Portal**.

1. **The Portal Link:** The ListMate backend calls the RevenueCat REST API to request a "Management URL" for the specific user.
2. **No Login Required:** RevenueCat uses the user's underlying Stripe Customer ID to generate a secure, short-lived (temporary) Stripe Customer Portal URL. The user does not need to remember a separate Stripe password.
3. **User Action:** The user clicks "Manage Subscription" in ListMate, clicks the secure link, and lands in the Stripe Portal where they can update their credit card or click "Cancel Plan".
4. **Cancellation Webhook:** If they cancel, Stripe alerts RevenueCat. RevenueCat fires a `CANCELLATION` webhook to our backend.
5. **Grace Period:** The user's `is_premium` status remains active until the end of their current billing cycle, at which point the backend downgrades them to Free.

## 5. Handling Upgrades & Downgrades (Annual vs Monthly)
When a user switches between the Monthly and Yearly plans using the Stripe Customer Portal:
- **Stripe Configuration:** In your Stripe Dashboard (Settings > Customer Portal), you can configure how plan changes are handled. 
  - **Upgrades (Monthly to Annual):** Usually set to take effect *immediately*, charging the user the prorated difference.
  - **Downgrades (Annual to Monthly):** The best practice is to configure downgrades to take effect at the *end of the current billing cycle*. This prevents you from having to issue partial refunds or manage complex account credits. The user remains on the Annual plan until it expires, at which point it seamlessly converts to Monthly.
- **RevenueCat Webhook:** When the plan actually changes, Stripe notifies RevenueCat. RevenueCat then fires a `PRODUCT_CHANGE` webhook to our backend.
- **Backend Logic:** Because both Monthly and Yearly unlock the same `is_premium` status in ListMate, a downgrade doesn't revoke access. Our webhook handler simply observes the `PRODUCT_CHANGE` event (if we are tracking the specific plan type in our database) or ignores it and just keeps `is_premium = true`.

---

## 6. Admin Setup: Step-by-Step Guide

### Phase A: Setting up Stripe
1. **Create Account:** Go to [Stripe.com](https://stripe.com) and create an account. Fill out your business details to activate it (or use Test Mode for now).
2. **Create Products (Monthly & Yearly):**
   - *Important:* RevenueCat maps to Stripe **Products**, not individual Prices. If you add multiple prices to one Stripe product, RevenueCat will only see one.
   - In the Stripe Dashboard, go to **Product Catalog** -> **Add Product**.
   - **Product 1:** Name it "ListMate Pro - Monthly". Add a single **Monthly** price (e.g., $2.99 / month). Save the product.
   - **Product 2:** Click **Add Product** again. Name it "ListMate Pro - Yearly". Add a single **Yearly** price (e.g., $29.99 / year). Save the product.
3. **Configure the Customer Portal:**
   - Go to **Settings** -> **Customer Portal**.
   - Enable the portal and configure what customers can do (update payment methods, cancel subscriptions, and switch plans).
   - *Crucial for Downgrades:* Under the "Update subscriptions" settings, configure downgrades to take effect "At the end of the billing period" to avoid prorated refund headaches.

### Phase B: Linking Stripe to RevenueCat (Stripe Billing)
1. **Install Stripe App:**
   - In your RevenueCat Dashboard, go to **Project Settings** -> **Web** (on the left navigation bar).
   - Select the **Stripe Billing** tab and connect via the Stripe Marketplace App.
   - **Important:** Because you installed the Stripe app from the marketplace, **RevenueCat automatically configures the necessary webhooks in your Stripe account**. You do not need to manually configure webhook endpoints or events!

### Phase C: Mapping Products in RevenueCat
1. **Import Stripe Products:**
   - In RevenueCat, go to **Products**.
   - Because Stripe is connected, your Stripe Monthly and Yearly products are pulled in and available to import.
2. **Add to Entitlements:**
   - Go to **Entitlements** -> select your "Pro" entitlement.
   - Attach the Stripe Monthly product to the Monthly offering, and the Stripe Yearly product to the Yearly offering.
3. **Checkout Integration:**
   - With the "Stripe Billing" setup, your app will handle creating Stripe Checkout sessions, and the manual Stripe webhook you configured will notify RevenueCat of the purchases to automatically unlock entitlements.
