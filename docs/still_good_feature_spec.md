# Feature Specification: "Still Good" — Leftover & Freezer Meal Tracker (Issue #592)

**Issue**: [#592](https://github.com/santven/listmate/issues/592)  
**Status**: Merged to `main` (Production Release)  
**Target Milestone**: v1.8.x

---

## 1. Executive Summary & Problem Space

Households routinely experience food waste and friction around prepared food management across three major everyday situations:

1. **Restaurant Takeout Leftovers**: People dine out or order takeout and bring home leftovers with good intentions. Without a visual reminder, the container sits behind other groceries and quietly moves from restaurant to fridge to trash.
2. **Daily Meal Leftovers**: Home-cooked lunch and dinner meals packed into containers for the next day get lost behind fresh items and are forgotten until they spoil.
3. **Sunday Batch / Mass Cooking Fatigue**: Households dedicate Sunday afternoons to batch-cooking multiple portions/boxes of curries, soups, or grains and store them in the freezer. After 2 to 3 days, palate fatigue sets in. The remaining boxes get pushed deeper into the freezer and forgotten for months. While food in the freezer does not spoil quickly, it loses quality and takes up valuable space without being consumed in a reasonable timeframe.

### The Emotional Tone & Psychology: "Thoughtful Kitchen"
Prior waste-tracking paradigms frequently invoke guilt or negative phrasing such as *"saved from trash"*, which inadvertently makes users feel like their stomachs are being treated as garbage bins. 

**Still Good** reframes the experience into positive reinforcement, mindfulness, and tangible household wins:
* **Purpose**: *"Meals put to good use"*
* **Achievement**: *"Kitchen wins this month"*
* **Financial Reward**: *"$40 kept in your pocket"* (estimating ~$8 saved per meal enjoyed rather than discarded)
* **Mindfulness**: *"Thoughtful Kitchen: Meals enjoyed"*

---

## 2. Information Architecture & Navigation

ListMate does not use bottom tabs; key feature destinations (Store Visits, Recipe Planner, Analytics) function as dedicated full screens.

### 2.1 Navigation Hooks
* **Home Screen Hook**: Positioned directly above the primary Quick-Add box on the grocery list screen, the **`🍲 Still Good`** button provides high-frequency access without cluttering the screen.
* **Hamburger Menu Retention**: To ensure existing users can always access all tools, the hamburger drawer (☰) includes:
  - `📋 Grocery List`
  - `🍲 Still Good`
  - `🍳 Recipe Planner`
  - `🗓️ Store Visits`
  - `📊 Analytics`
* **Deep Linking**: Direct URL routing via query parameter: `/?screen=stillGood` (also supporting `?screen=still_good`).

---

## 3. UI/UX Specification

### 3.1 Thoughtful Kitchen Motivation Banner
Mounted at the top of the Still Good screen, this card displays daily household motivation and trailing 7-day savings.

* **Daily Deterministic Rotation**: Rotates by day of year (`dayOfYear % messages.length`) to provide a fresh thought daily without distracting auto-cycling carousel carousels.
* **Trailing 7-Day Savings**: Displays calculated 7-day savings (`$8 * meals enjoyed in past 7 days`). If $0 is saved in the past 7 days, this message is cleanly omitted from the rotation until meals are logged as enjoyed.
* **On-Demand Kitchen Wins**: Tapping the banner immediately opens the **🏆 Thoughtful Kitchen Wins** modal.

### 3.2 Dual-Storage Tabs: Refrigerator vs. Freezer
* **`🧊 Refrigerator (<count>)`**: Focused on immediate leftovers with 3–4 day target shelf lives.
* **`❄️ Freezer (<count>)`**: Focused on mass-cooked boxes, frozen staples, and meals preserved for 30–90 days.

### 3.3 Thawing Alert Bar
When freezer items are marked as **Thawing**, a prominent soft-blue alert bar informs household members:
> `💧 1 freezer meal thawing for dinner`
This helps avoid redundant cooking when a frozen meal is already prepped to eat.

### 3.4 Multi-Modal Interaction: Swiping & Tap-Accessible Controls
The card interface supports dual interaction paradigms with zero Capacitor plugins or native iOS/Android bridge overhead:

#### Native Web Touch Gestures
* **Swipe Right (→ Green Reveal)**: Passing the 85px threshold triggers the **Enjoyed** action, firing a joyful micro-confetti burst (`canvas-confetti`) and immediately incrementing the household's monthly kitchen win count.
* **Swipe Left (← Red Reveal)**: Passing the -85px threshold marks the item as **Discarded**.

#### Desktop & Accessibility Direct Buttons
On desktop or for users who prefer direct tapping:
* `✓ Enjoyed` (Green button): One-tap consume with celebration toast.
* `✏️ Edit` (Pencil button): Opens the Add/Edit bottom sheet pre-populated with item data for easy updates.
* `❄️ Freeze` (On fridge cards): Moves expiring fridge items to the freezer, extending expiration to 60 days.
* `💧 Thaw` (On freezer cards): Toggles the thawing indicator for evening dinner planning.
* `🧊 Move to Fridge` (On thawing freezer cards): Completes defrost transfer into the active fridge queue.
* `🗑` (Trash icon): Discards or removes the item.

### 3.5 Quick Add / Edit Bottom Sheet
Accessible via the `+ Add Item` header button or card pencil edit icon:
* **Food Name**: Input with placeholder and dynamic fallback (`"[Day of Week] Leftovers"` if left blank).
* **Storage Location Toggle**: `[ 🧊 Refrigerator ]` vs. `[ ❄️ Freezer ]`.
* **Food Category Badges**:
  - `🍳 Home Meal` (Default target: +3 days)
  - `🥡 Restaurant Leftover` (Default target: +24h fridge / +30d freezer)
  - `🍲 Sunday Batch Cook` (Default target: +60 days for freezer / +4–5 days for fridge)
* **Portions / Boxes Stepper**: Counter stepper (`[-] 1 portion / box [+]`).
* **Target Consume-By Date**: HTML5 date input with one-tap quick jump buttons (`+3 days`, `+5 days`, `+1 month`, `+2 months`).
* **Notes**: Optional memo (e.g. `"Mild spice"`, `"Box 2 of 4"`).

### 3.6 Kitchen Wins Modal
Accessible via `🏆 Wins` or tapping the motivation banner:
* Displays month-to-date kitchen wins and calculated 7-day dollar savings.
* Provides encouraging education on household impact.

---

## 4. Technical Architecture & Database Design

### 4.1 PostgreSQL Schema (`still_good_items`)
```sql
CREATE TABLE IF NOT EXISTS still_good_items (
    id SERIAL PRIMARY KEY,
    household_id INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT 'fridge',    -- 'fridge' or 'freezer'
    item_type TEXT NOT NULL DEFAULT 'home_cooked', -- 'restaurant', 'home_cooked', 'batch_cook', 'other'
    servings INTEGER NOT NULL DEFAULT 1,
    date_added DATE NOT NULL DEFAULT CURRENT_DATE,
    consume_by DATE,
    status TEXT NOT NULL DEFAULT 'active',      -- 'active', 'consumed', 'discarded'
    consumed_at TIMESTAMP,
    discarded_at TIMESTAMP,
    thawing BOOLEAN NOT NULL DEFAULT FALSE,
    notes TEXT DEFAULT '',
    ai_estimated BOOLEAN NOT NULL DEFAULT FALSE,
    ai_estimated_at TIMESTAMP,
    shelf_life_days INTEGER,
    ai_tip TEXT DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_still_good_hh_status ON still_good_items(household_id, status);
CREATE INDEX IF NOT EXISTS idx_still_good_hh_loc ON still_good_items(household_id, location);
CREATE INDEX IF NOT EXISTS idx_still_good_ai_pending ON still_good_items(status, ai_estimated);
```

### 4.2 REST API Specification & Paywall Security

All Still Good endpoints are protected by `@require_user` and enforce household subscription verification (`_can_household_access_still_good`):

| Endpoint | Method | Paywall Gated | Description |
|---|---|:---:|---|
| `/api/still-good` | `GET` | Yes (403 for expired/free) | Returns active items filtered by location/status along with household stats, AI tips, and messages. |
| `/api/still-good` | `POST` | Yes (403 for expired/free) | Creates a new leftover or batch-cooked meal item with validated dates. |
| `/api/still-good/<id>/action` | `POST` | Yes (403 for expired/free) | Executes state transition: `consume`, `discard`, `move` (fridge ↔ freezer), or `thaw`. |
| `/api/still-good/<id>` | `PUT` | Yes (403 for expired/free) | Updates item metadata (name, portions, validated target date, notes). |
| `/api/still-good/<id>` | `DELETE` | Yes (403 for expired/free) | Permanently deletes an item record. |
| `/api/still-good/vacation-freeze` | `POST` | Yes (403 for expired/free) | Batch-moves all active fridge items to freezer with safe conservative target dates. |

---

## 4.3 Subscription Access Control & Paywall Architecture

### Eligibility Rules
Still Good is an exclusive Pro feature available to:
1. **Premium Active / Canceled Households**: Users on active paid subscriptions or during the paid period after cancellation (`subscription_status = 'premium'` or `'active'`).
2. **Active Pro Trial Households**: Users in an ongoing Pro trial (`subscription_status = 'trial'` and `trial_ends_at >= NOW()`).

### Ineligible Users
* **Expired Households**: Trial or subscription has ended (`subscription_status = 'expired'` or expired trial timestamp).
* **Free / Legacy Unsubscribed Households**: Users without an active subscription.

### Enforcement Mechanism
* **Backend**: `_can_household_access_still_good(db, hhid)` returns `False` for expired and free accounts, aborting requests with HTTP `403 Forbidden` (`{"error": "premium_required", "message": "Still Good is a Pro feature..."}`).
* **Frontend UI Gating**:
  - `canAccessStillGood()` helper checks `window.currentCfg.subscription_status` and active trial date.
  - Tapping `#btnOpenStillGood` or the menu link `#menuStillGoodLink` displays the paywall upgrade modal (`showPremiumModal('Still Good')`) for ineligible users instead of loading the screen.
  - Feature discovery halos are suppressed for expired households.

---

## 4.4 App-Based Shelf-Life Recommendation Engine

**Goal**: Remove manual date picking and nudge decision friction; let the app and AI determine safe shelf-life automatically without burdening users with behind-the-scenes mechanics.

### Automated Decision Matrix
Users should never have to manually consult a calendar or guess when an app should nudge them. The app immediately presents the intelligent, conservative shelf-life based on storage location and meal type:
* **🥡 Restaurant Takeout (Fridge)**: **24 hours / Tomorrow** (*"Takeout degrades rapidly; seafood/dressed salads strictly 1 day"*).
* **🍳 Home-Cooked Leftovers (Fridge)**: **3 days** (*"USDA standard safe window for home-cooked meals"*).
* **🍲 Batch Cook (Fridge)**: **4–5 days** (*"Hearty stews, soups, or batch cooks in fridge"*).
* **🥡 Restaurant Takeout (Freezer)**: **~30 days / 1 month** (*"Conservative window: experiences faster quality degradation, sauce breakdown, and freezer burn than home batch meals"*).
* **❄️ Home Meals / Batch Cook (Freezer)**: **~60 days / 2 months** (*"Freezing pauses spoilage; best within 2 months for peak flavor"*).

---

## 4.5 Midnight GMT Batch AI Estimator (`still_good_ai.py` & `scripts/cron_hourly.py`)

To further personalize shelf-life without incurring token bloat or user latency, Still Good uses an asynchronous daily batch AI process triggered from the hourly cron engine.

### Operational Characteristics
* **Schedule**: Runs from `scripts/cron_hourly.py` specifically when `now_utc.hour == 0` (12:00 AM / midnight GMT), rather than `cron_daily.py`.
* **Token Efficiency**: Aggregates all unestimated active items (`ai_estimated = FALSE`) across households into a **single batch JSON prompt** sent to Gemini Flash.
* **Idempotency & One-Time Enhancement**: Sets `ai_estimated = TRUE`, `ai_estimated_at = NOW()`, `shelf_life_days`, and `ai_tip`. Each item is evaluated exactly once in its lifetime, conserving LLM tokens.
* **Conservative Food Safety Analysis**: Considers microbial growth, water activity, dish composition, and storage temperature to compute a conservative shelf life.
* **Graceful Heuristic Fallback**: If no API key is configured or API limits are reached, the system falls back to conservative culinary heuristics without error.
* **CLI Execution**: Can be run ad-hoc via `python3 scripts/cron_hourly.py --still-good-ai` or `python3 scripts/cron_hourly.py --force`.

---

## 4.6 Launch Halo, Dismissal Persistence & Dynamic Defaults

1. **One-Time Feature Launch Halo**:
   - The `#btnOpenStillGood` button displays a pulsating golden halo for eligible users to announce the new feature.
   - Upon first tap/click, the halo is permanently dismissed and persisted in `localStorage` (`listmate_dismissed_halo_still_good = 'true'`), preventing annoying recurring pulses.
2. **Dynamic Day-of-Week Leftovers Default**:
   - When a user adds an item without typing a name, the app automatically assigns a contextual name: `"[Day of Week] Leftovers"` (e.g. *"Thursday Leftovers"* or *"Monday Leftovers"*).
3. **Pencil Icon Edit Mode**:
   - Cards display a dedicated pencil icon button that opens the bottom sheet with pre-populated values, allowing quick corrections to portions, name, or consume-by dates.
4. **Backend Date Validation**:
   - Endpoints validate incoming `consume_by` and `date_added` strings against ISO `YYYY-MM-DD` formatting, rejecting invalid dates with HTTP 400.

---

## 4.7 Vacation Mode Drawer & 1-Click Batch Freeze (Issue #603)

**Goal**: Allow households leaving town to review perishable fridge leftovers before departure, discard unwanted meals, or freeze all active leftovers in one click with automatically updated safe freezer nudges.

### Features
1. **Header Action**: `✈️ Vacation` button positioned in the Still Good top navigation bar.
2. **Bottom Drawer Modal**:
   - Displays all active refrigerator items with current portions, categories, and freshness badges.
   - Individual item actions: `🗑 Discard` and `❄️ Freeze`.
3. **1-Click Bulk Freezer Transfer**:
   - `❄️ Move All (<count>) to Freezer & Update Nudges`: Sends `POST /api/still-good/vacation-freeze` which transitions all active fridge items into the freezer simultaneously.
   - Automatically sets conservative freezer target dates (+30 days for restaurant takeout, +60 days for home-cooked meals/batch cooks).
   - Instant UI feedback with confetti celebration, toast notification, and automatic redirection to the `❄️ Freezer` tab.

---

## 4.8 Interactive Feature Discovery Tips & Guided Walkthrough (Issue #605)

**Goal**: Guide new and returning household members through an interactive, multi-step feature discovery tour highlighting Still Good, how it operates, and how to track meals in seconds.

### Guided Steps & Interactive Halos
1. **Step 1: Main Screen Entry (`#btnOpenStillGood`)**: Golden discovery halo with introduction drawer.
2. **Step 2: Add Item Action (`#btnStillGoodAddItem`)**: Halo on header `+ Add Item` button.
3. **Step 3: Food Name Input (`#sgInputName`)**: Floating in-modal tip card auto-focusing the food name input.
4. **Step 4: Save & Track (`#btnSaveStillGood`)**: Floating tip card guiding the user to save and track their dish.
5. **Replayability**: Accessible anytime via `💡 Tips` in the header or `?tour=still_good` in the URL.

---

## 4.9 Announcement Email Engine & Lifecycle Retargeting (`scripts/send_still_good_announcement_email.py`)

A multi-segment announcement email campaign was created to introduce Still Good across all household lifecycle stages.

### Campaign Segments
1. **Premium & Active Households** (`static/preview_still_good_premium_active.html`):
   - **Tone**: Exciting feature upgrade celebration.
   - **Visual Guidance**: High-fidelity in-app home screen mockup showing the exact placement of the `🍲 Still Good` button directly above the Quick-Add box.
   - **CTA**: Direct deep-link button (`Open Still Good in ListMate`).
2. **Active Trial Households** (`static/preview_still_good_trial.html`):
   - **Tone**: Feature announcement highlighting Pro value.
   - **CTA**: "Upgrade to Pro" button alongside the visual app mockup.
3. **Expired Households** (`static/preview_still_good_expired.html`):
   - **Tone**: Win-back feature announcement.
   - **Incentive**: **15-day Pro trial extension** generated via `claim_trial_extension(hhid, uid, '15d')` with automatic login deep-link (`BASE_URL/open?token=...`).
   - **CTA**: "Claim 15-Day Free Extension" and "Upgrade to Pro".

### Shared Campaign Elements & Copy Standards
* **Team Signature**: Signed respectfully as *"The ListMate Team"*.
* **Estimated Savings Phrasing**: Clarifies that savings are estimated over the trailing 7-day period rather than representing an all-time money-saved tracker.
* **Viral & Update Hooks**:
  - `📲 Share ListMate with Friends` button (`sms:...` / native share).
  - `⚡ Update to Latest Version` prompt with iOS App Store and Google Play badges/links.
* **Test & Dry-Run Modes**:
  - `python3 scripts/send_still_good_announcement_email.py --dry-run`
  - `python3 scripts/send_still_good_announcement_email.py --test-email you@example.com`

---

## 5. Future Roadmap & Iterations

1. **Push Notifications**:
   - Timezone-aware 11:30 AM reminder: *"You have Chicken Tikka in the fridge ready for lunch!"*
   - Evening dinner thaw reminder for freezer items flagged for today.
2. **Inventory to Grocery List Restock**:
   - When the final box of a Sunday batch cook is consumed, prompt: *"Enjoyed your last box of Lentil Soup? Add ingredients to your grocery list for Sunday."*
3. **Household Push Alerts**:
   - When a family member marks takeout leftovers as eaten or thawing, optionally inform the household so nobody double-cooks.
