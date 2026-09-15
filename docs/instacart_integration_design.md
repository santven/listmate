# Design Document: Order via Instacart Integration

**Feature Name:** Order via Instacart (Shoppable Cart & Store Visit Tracking)  
**Status:** Shipped to `staging`  
**GitHub Issue:** [#447](https://github.com/santven/listmate/issues/447)  
**Pull Request:** [#448](https://github.com/santven/listmate/pull/448)  
**Target Platforms:** Web (PWA), iOS (Capacitor), Android (Capacitor)  

---

## 1. Executive Summary & Problem Statement

### The Problem
ListMate is designed as a household grocery planner that organizes shopping across multiple physical stores (e.g., Costco, Patel Brothers, Trader Joe's, General List). However, users frequently encounter scenarios where they cannot or prefer not to visit a store in person due to time constraints, illness, or convenience. Previously, users had to manually re-type their ListMate items into Instacart, Walmart, or another delivery app, resulting in friction and loss of list synchronization.

### The Solution
The **Order via Instacart** integration bridges planning with automated fulfillment. Users can select any or all open items across their household stores, convert them into a shoppable Instacart cart with a single tap, launch directly into Instacart to review matches and place their order, and seamlessly reconcile their ListMate grocery list and store visit history upon returning to the app.

---

## 2. Core Architecture & High-Level Flow

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant App as ListMate Frontend (PWA/Capacitor)
    participant Backend as ListMate Backend (Flask/PostgreSQL)
    participant Instacart as Instacart Platform / Connect API

    User->>App: Clicks "🥕 Order via Instacart" in Burger Menu
    App->>App: Opens `#screenInstacart`, pre-selects open items
    opt Add unlisted items
        User->>App: Quick-adds new item -> saved to General List
    end
    User->>App: Taps "Create Instacart Cart"
    App->>Backend: POST /api/integrations/instacart/cart {items, title}
    alt API Key Configured
        Backend->>Instacart: POST /v2/partners/lists (Bearer Token)
        Instacart-->>Backend: Return custom shoppable list URL
    else Key Not Set (Universal Fallback)
        Backend->>Backend: Generate universal partner_cart URL
    end
    Backend-->>App: { ok: true, url, items_count, item_ids }
    App->>App: Shows "Your Cart is Ready!" modal
    User->>App: Taps "Open Instacart Cart"
    App->>App: Writes pending state to localStorage
    App->>Instacart: Opens Cart URL in Browser / Capacitor InAppBrowser
    Note over User,Instacart: User reviews items, selects store & completes checkout on Instacart
    User->>App: Returns / switches back to ListMate
    App->>App: Detects focus/visibilitychange; verifies pending items
    App->>User: Prompts "Welcome Back! Did you place your order?"
    alt User clicks "Yes, Mark as Purchased"
        App->>Backend: POST /api/integrations/instacart/complete {item_ids}
        Backend->>Backend: 1. Find or create "Instacart" store<br/>2. Mark items purchased<br/>3. Upsert item_purchase_stats<br/>4. Upsert store_visits (+count)
        Backend-->>App: { ok: true, completed_count, store_id }
        App->>App: Clears localStorage, triggers celebration, reloads list
    else User clicks "Keep on List"
        App->>App: Sets dismissed_modal=true, shows pending banner
    else User clicks "Start New Order"
        App->>App: Clears pending state, re-opens Instacart screen
    end
```

---

## 3. Detailed Component Specifications

### 3.1. Frontend Navigation & Screen Layout
- **Navigation Entry Point**: An entry labeled `🥕 Order via Instacart` in the burger navigation drawer (`#burgerMenu`).
- **Deep Linking**: Direct access via URL parameter `?screen=instacart`.
- **The Instacart Screen (`#screenInstacart`)**:
  - **Header**: Back button returning to the main grocery list, screen title with Instacart carrot badge, and dynamic selection pill counter (e.g., `5 selected`).
  - **Quick-Add Bar**: Single-line text input allowing users to add last-minute items to the order. Items added through this input are immediately saved to the household's **General List** in PostgreSQL, pre-selected with a checkmark, and displayed in the checklist.
  - **Items Checklist**: Renders all open (unpurchased) items belonging to the household across all stores. Each item card displays:
    - Custom orange checkbox (toggled via card click or checkbox tap).
    - Optional quantity prefix (highlighted in orange).
    - Item name.
    - Store origin badge (e.g., `📍 Costco`, `📍 Patel Brothers`, `📍 General List`).
  - **Batch Controls**: Quick "Select All" and "Clear All" buttons to manipulate selection state in bulk.
  - **Sticky Bottom Action Bar (`#instacartBottomBar`)**: Fixed at the bottom with safe-area padding for mobile viewports, containing the vibrant primary action button: `Create Instacart Cart (N items)` with loading indicator during generation.

---

## 4. API & Backend Specifications

### 4.1. `POST /api/integrations/instacart/cart`
Creates a shoppable Instacart cart link from a list of household grocery items.

#### Authentication
Requires standard session user authentication (`@require_user`).

#### Request Payload
```json
{
  "items": [
    { "id": 101, "name": "Organic Whole Milk", "quantity": "1 gallon" },
    { "id": 102, "name": "Brown Eggs", "quantity": "1 dozen" },
    { "id": 103, "name": "Bananas", "quantity": "" }
  ],
  "title": "The Smith Family Grocery Order"
}
```

#### Processing Logic
1. Sanitizes ingredients into formatted lines: `"{quantity} {name}".strip()`.
2. Validates that at least one valid item is provided.
3. Checks for `INSTACART_API_KEY` in environment variables:
   - **When set**: Makes a POST request to `https://connect.instacart.com/v2/partners/lists` with the payload `{"title": title, "ingredients": ingredients, "partner_id": partner_id}` and `Authorization: Bearer <key>`.
   - **When unset**: Automatically falls back to the universal Instacart partner landing page format:
     `https://www.instacart.com/store/partner_cart?title={encoded_title}&partner_id={partner_id}&items={encoded_items}`.
4. Returns the verified cart URL and tracking metadata.

#### Response Payload (200 OK)
```json
{
  "ok": true,
  "url": "https://www.instacart.com/store/partner_cart?title=The+Smith+Family+Grocery+Order&partner_id=listmate&items=1+gallon+Organic+Whole+Milk%2C1+dozen+Brown+Eggs%2CBananas",
  "items_count": 3,
  "item_ids": [101, 102, 103]
}
```

---

### 4.2. `POST /api/integrations/instacart/complete`
Reconciles an Instacart order after user confirmation upon returning to the app.

#### Authentication
Requires standard session user authentication (`@require_user`).

#### Request Payload
```json
{
  "item_ids": [101, 102, 103]
}
```

#### Processing Logic
1. **Find or Create Instacart Store**: Queries `stores` for a store with `LOWER(TRIM(name)) = 'instacart'` for the current `household_id`. If none exists, creates one dynamically:
   ```sql
   INSERT INTO stores (name, household_id) VALUES ('Instacart', %s) RETURNING id, name
   ```
2. **Retrieve Open Items**: Filters `list_items` matching the requested IDs where `household_id = %s AND purchased = FALSE`.
3. **Batch Mark as Purchased**: Updates matching items to `purchased = TRUE`, recording the user display name in `purchased_by` and setting `purchased_at = NOW()`.
4. **Update Purchase Statistics**: For each purchased item, upserts into `item_purchase_stats`:
   ```sql
   INSERT INTO item_purchase_stats (household_id, name, category, total_purchases, last_purchased)
   VALUES (%s, %s, %s, 1, NOW())
   ON CONFLICT (household_id, name)
   DO UPDATE SET total_purchases = item_purchase_stats.total_purchases + 1, last_purchased = NOW()
   ```
5. **Record Store Visit**: Checks if a visit for the Instacart store exists for today (`visit_date = CURRENT_DATE`). If so, increments `items_count`; otherwise, inserts a new visit record.
6. **Clear Store Visit Planning**: Clears `planned_visit_date`, `planned_visit_by`, and `visit_notified_users` for the Instacart store.

#### Response Payload (200 OK)
```json
{
  "ok": true,
  "completed_count": 3,
  "store_id": 42,
  "store_name": "Instacart"
}
```

---

## 5. State Management & Lifecycle Architecture

### 5.1. Client-Side State (`localStorage`)
The integration uses a lightweight persistence key in the browser/app storage:
- **Key**: `listmate_pending_instacart`
- **Schema**:
  ```json
  {
    "item_ids": [101, 102, 103],
    "launched_at": 1726428900000,
    "timestamp": 1726428900000,
    "dismissed_modal": false
  }
  ```

### 5.2. Return Detection Triggers
The client registers three lifecycle listeners:
1. `window.addEventListener('focus', checkInstacartReturn)`
2. `document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') checkInstacartReturn(); })`
3. Capacitor native app state:
   ```javascript
   if (window.Capacitor?.Plugins?.App) {
     window.Capacitor.Plugins.App.addListener('appStateChange', ({ isActive }) => {
       if (isActive) checkInstacartReturn();
     });
   }
   ```

### 5.3. Guardrails & Expiration
- **Minimum Transition Buffer**: Ignores return events triggered within 4 seconds of cart launch (`Date.now() - launched_at < 4000`) to prevent immediate popups when switching windows.
- **TTL Expiration**: Pending records older than 24 hours are automatically purged to prevent stale prompts.
- **Already-Purchased Safeguard**: Before presenting the "Welcome Back" modal, the app filters the saved `item_ids` against the live in-memory `list`. If all items were already checked off manually or removed, the pending state is automatically cleared.

---

## 6. Modals & User Feedback Components

| Component | Trigger | Purpose & Actions |
|---|---|---|
| **Cart Ready Modal (`#instacartReadyModal`)** | API returns cart URL | Confirms items prepared. Primary action: "Open Instacart Cart" (launches URL and sets pending state). Secondary: "Cancel". |
| **Welcome Back Modal (`#instacartWelcomeBackModal`)** | Returning to app with pending items | Asks: *"Did you place your Instacart order?"* with dynamic item count. Actions:<br/>- **✅ Yes, Mark as Purchased** (calls `/complete`)<br/>- **🛒 Start New Order** (resets and re-opens)<br/>- **Keep on List** (dismisses modal, sets `dismissed_modal=true`) |
| **Pending Banner (`#instacartPendingBanner`)** | `dismissed_modal=true` with open items | Rendered above the grocery list on `#screenHome`. Displays: *"Instacart Order Pending — N items sent to Instacart cart"*. Includes quick "Mark Done" and "Dismiss" buttons. |

---

## 7. Environment Variables & Configuration

Declared in `.env.example`:

| Variable | Type | Default | Description |
|---|---|---|---|
| `INSTACART_API_KEY` | Secret String | *(None)* | Optional Bearer token for official Instacart Connect Developer Platform API. |
| `INSTACART_PARTNER_ID` | String | `listmate` | Partner / affiliate identifier for shoppable links and commission tracking. |

---

## 8. Error Handling & Edge Cases

1. **Network Failure during Cart Creation**: The submit button reverts to its enabled state, restoring its original label, and displays an informative toast (`Network error creating cart`).
2. **Items Checked Off Prior to Instacart Completion**: If family members in the same household checked off items while the user was in Instacart, `/api/integrations/instacart/complete` gracefully handles the discrepancy by only updating items that remain `purchased = FALSE`.
3. **App Killed / Browser Tab Closed**: State persists in `localStorage`. When the user re-launches ListMate days later or switches tabs, the expiration check safely purges stale orders (>24 hours) or prompts the user if within the active window.
4. **Offline Mode**: If the user is offline when returning, the pending banner remains visible so they can mark items complete as soon as connectivity resumes.

---

## 9. Security & Compliance

- **No User Credentials Shared**: ListMate never requests, stores, or handles Instacart account credentials, passwords, or payment cards. All authentication and payment occurs entirely within Instacart's secure domain.
- **Household Scoping**: All database queries strictly scope item updates and store creation to `household_id = _hh()`, preventing cross-household data leakage.
- **Parametric SQL**: All PostgreSQL statements use parameter substitution (`%s` / `?`) to prevent SQL injection vulnerabilities.

---

## 10. Future Enhancements & Roadmap

1. **Store-Specific Instacart Filtering**: Allow filtering the Instacart selection screen to only show items belonging to stores with Instacart availability (e.g., Aldi, Costco, Sprouts).
2. **Meal Planner Direct Handoff**: Add an "Order Recipe via Instacart" button directly from the Recipe Detail screen to push all recipe ingredients to an Instacart cart in one click.
3. **Affiliate Attribution**: Monetize cart checkouts via the Instacart Developer Platform affiliate commission program using `INSTACART_PARTNER_ID`.
