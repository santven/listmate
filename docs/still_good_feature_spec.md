# Feature Specification: "Still Good" — Leftover & Freezer Meal Tracker (Issue #592)

**Issue**: [#592](https://github.com/santven/listmate/issues/592)  
**Status**: Shipped to Staging (PR #593)  
**Target Milestone**: v1.8.x (Staging)

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
* **Home Screen Hook**: The Recipe Planner button on the primary grocery list screen—which had low daily engagement—is replaced by the high-frequency hook **`🍲 Still Good`**.
* **Hamburger Menu Retention**: To ensure existing users can always access both tools, the hamburger drawer includes:
  - `📋 Grocery List`
  - `🍲 Still Good`
  - `🍳 Recipe Planner`
  - `🗓️ Store Visits`
  - `📊 Analytics`
* **Deep Linking**: Direct URL routing via query parameter: `/?screen=stillGood` (also supporting `?screen=still_good`).

---

## 3. UI/UX Specification

### 3.1 Thoughtful Kitchen Celebration Banner
Mounted at the top of the Still Good screen, this card cyclically displays four positive milestones:
1. `✨ 5 meals put to good use`
2. `🏆 5 kitchen wins this month`
3. `💵 $40 kept in your pocket`
4. `🌿 Thoughtful Kitchen: 5 meals enjoyed`

* **Cadence**: Automatically transitions every 5 seconds with a gentle fade animation, or updates immediately when tapped.
* **Progress Dots**: Four dot indicators illustrate rotation sequence.
* **Zero State**: Displays encouraging welcome guidance when a household begins logging meals.

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
* `❄️ Freeze` (On fridge cards): Moves expiring fridge items to the freezer, extending expiration to 60 days.
* `💧 Thaw` (On freezer cards): Toggles the thawing indicator for evening dinner planning.
* `🧊 Move to Fridge` (On thawing freezer cards): Completes defrost transfer into the active fridge queue.
* `🗑` (Trash icon): Discards or removes the item.

### 3.5 Quick Add Bottom Sheet
Accessible via the `+ Add Item` header button:
* **Food Name**: Input with examples (`"Chicken Tikka"`, `"Veggie Biryani"`, `"Sunday Chili"`).
* **Storage Location Toggle**: `[ 🧊 Refrigerator ]` vs. `[ ❄️ Freezer ]`.
* **Food Category Badges**:
  - `🍳 Home Meal` (Default target: +4 days)
  - `🥡 Restaurant Leftover` (Default target: +3 days)
  - `🍲 Sunday Batch Cook` (Default target: +60 days for freezer / +5 days for fridge)
* **Portions / Boxes Stepper**: Counter stepper (`[-] 1 portion / box [+]`).
* **Target Consume-By Date**: HTML5 date input with one-tap quick jump buttons (`+3 days`, `+5 days`, `+1 month`, `+2 months`).
* **Notes**: Optional memo (e.g. `"Mild spice"`, `"Box 2 of 4"`).

### 3.6 Kitchen Wins Modal
Accessible via `🏆 Wins`:
* Displays month-to-date kitchen wins and calculated dollar savings.
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
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_still_good_hh_status ON still_good_items(household_id, status);
CREATE INDEX IF NOT EXISTS idx_still_good_hh_loc ON still_good_items(household_id, location);
```

### 4.2 REST API Specification

| Endpoint | Method | Description |
|---|---|---|
| `/api/still-good` | `GET` | Returns active items filtered by location/status along with household stats, AI tips, and cycling celebration messages. |
| `/api/still-good` | `POST` | Creates a new leftover or batch-cooked meal item with app-recommended or custom nudge shelf-life. |
| `/api/still-good/<id>/action` | `POST` | Executes state transition: `consume`, `discard`, `move` (fridge ↔ freezer), or `thaw`. |
| `/api/still-good/<id>` | `PUT` | Updates item metadata (name, portions, target date, notes). |
| `/api/still-good/<id>` | `DELETE` | Permanently deletes an item record. |

---

## 4.3 App-Based Shelf-Life Recommendation Engine (Issues #595, #597, #599)

**Issues**: [#595](https://github.com/santven/listmate/issues/595), [#597](https://github.com/santven/listmate/issues/597), [#599](https://github.com/santven/listmate/issues/599)  
**Goal**: Remove manual date picking and nudge decision friction; let the app and AI determine safe shelf-life automatically without burdening users with behind-the-scenes mechanics.

### Automated Decision Matrix
Users should never have to manually consult a calendar or guess when an app should nudge them. The app immediately presents the intelligent, conservative shelf-life based on storage location and meal type:
* **🥡 Restaurant Takeout (Fridge)**: **24 hours / Tomorrow** (*"Restaurant takeout degrades quickly in the fridge; seafood/dressed salads strictly 1 day"*).
* **🍳 Home-Cooked Leftovers (Fridge)**: **3 days** (*"USDA standard safe window for home-cooked meals"*).
* **🍲 Batch Cook (Fridge)**: **4–5 days** (*"Hearty stews, soups, or batch cooks in fridge"*).
* **🥡 Restaurant Takeout (Freezer)**: **~30 days / 1 month** (*"Conservative window: whether chef-boxed untouched or leftover from a meal, takeout experiences faster quality degradation, sauce breakdown, and freezer burn than home batch meals"*).
* **❄️ Home Meals / Batch Cook (Freezer)**: **~60 days / 2 months** (*"Freezing pauses spoilage; best within 2 months for peak flavor"*).

The Add Item modal displays this recommendation directly and cleanly—without any distracting mentions of background AI processing or manual nudge buttons.

---

## 4.4 Midnight GMT Batch AI Estimator (`still_good_ai.py` & `scripts/cron_hourly.py`)

To further personalize shelf-life without incurring token bloat or user latency, Still Good uses an asynchronous daily batch AI process triggered from the hourly cron engine.

### Operational Characteristics
* **Schedule**: Runs from `scripts/cron_hourly.py` specifically when `now_utc.hour == 0` (12:00 AM / midnight GMT), rather than `cron_daily.py` (which runs at 8:00 AM GMT / 3:00 AM Central).
* **Token Efficiency**: Aggregates all unestimated active items (`ai_estimated = FALSE`) across households into a **single batch JSON prompt** sent to Gemini Flash.
* **Idempotency & One-Time Enhancement**: Sets `ai_estimated = TRUE`, `ai_estimated_at = NOW()`, `shelf_life_days`, and `ai_tip`. Each item is evaluated exactly once in its lifetime, conserving LLM tokens.
* **Unconstrained Conservative Prompting**: The AI is instructed to be strictly conservative based on food safety principles (prioritizing food safety over shelf extension), but is not bound by prescriptive hardcoded day caps. The model decides the appropriate safe cap and nudge window using its culinary and microbiological knowledge.
* **Graceful Heuristic Fallback**: If no Gemini key is configured or API limits are reached, the system falls back to conservative culinary heuristics (e.g. 1 day for fridge takeout, 30 days for freezer takeout, 3 days for fridge home cooked, 60 days for freezer batch cooks) without breaking.
* **CLI Execution**: Can be run ad-hoc via `python3 scripts/cron_hourly.py --still-good-ai` or `python3 scripts/cron_hourly.py --force`.

---

## 4.5 Household Daily Motivation & 7-Day Savings Engine (Issue #601)

**Issue**: [#601](https://github.com/santven/listmate/issues/601)  
**Goal**: Replace intrusive 5-second carousel banners with a calm, authentic daily household motivation card, and ground dollar savings directly in the household's actual 7-day activity.

### Operational Principles
1. **Daily Calendar Rotation (No Carousels)**:
   - Rather than cycling every 5 seconds with pagination dots and transition flicker, the motivation banner displays a single steady highlight for the day.
   - Rotates deterministically based on day of year (`dayOfYear % messages.length`) so each day brings a fresh household thought.
   - Tapping the banner opens the **🏆 Thoughtful Kitchen Wins** modal for on-demand details.
2. **Dynamic 7-Day Household Savings**:
   - Calculates exact household dollars saved over the trailing 7 days: `COUNT(*) FILTER (WHERE status = 'consumed' AND consumed_at >= (NOW() - INTERVAL '7 days')) * $8`.
   - **Zero-Waste Motivation Pruning**: If the household has **$0 saved in the last 7 days**, the dollar savings message is omitted completely from the rotation, gracefully switching between the other thoughtful kitchen motivations (e.g. tracking batch cooks, meals enjoyed).
   - Once a household consumes an item, the `"💵 $X saved in the last 7 days"` message dynamically enters the rotation.

---

## 4.6 Resilience & Frontend Bug Fixes (Issue #597)
1. **Thawing Alert Bar Initial State**: Corrected an inline CSS cascade issue (`style="display:none; ... display:flex;"`) where `display:flex` erroneously overrode `display:none` on initial page load, causing a phantom "1 freezer meal thawing for dinner" bar before items were loaded.
2. **Resilient Endpoint Queries**: Wrapped `/api/still-good` in robust try/except blocks and added automatic fallback queries to ensure the endpoint succeeds even if new optional columns are temporarily absent during database deployment cycles.
3. **Household Resolution Fallback**: Enforces safe household fallback to the authenticated user's record or household 1 so items are never hidden due to missing session keys.

---

## 4.7 Vacation Mode Drawer & 1-Click Batch Freeze (Issue #603)

**Issue**: [#603](https://github.com/santven/listmate/issues/603)  
**Goal**: Allow households leaving town or going on vacation to quickly review perishable fridge leftovers before departure, discard unwanted meals, leave non-perishables, or move all active leftovers to the freezer in one click with automatically updated safe freezer nudges.

### Features
1. **Header Action**: `✈️ Vacation` button positioned prominently in the Still Good top navigation bar.
2. **Bottom Drawer Modal**:
   - Opens `stillGoodVacationModal` with clear instructions & reminders: *"Perishable leftovers won't keep while you're away. Review your fridge items below: Freeze meals to safely preserve them (nudges update automatically), Discard leftovers you won't eat, or leave items in the fridge as is."*
   - Displays all active refrigerator items with current portions, categories, and freshness/urgency badges.
   - Individual item actions:
     - `🗑 Discard`: Removes/discards perishable items that the user chooses not to keep.
     - `❄️ Freeze`: Individually moves an item to the freezer.
3. **1-Click Bulk Freezer Transfer**:
   - `❄️ Move All (<count>) to Freezer & Update Nudges`: Sends `POST /api/still-good/vacation-freeze` which transitions all active fridge items into the freezer simultaneously.
   - **Automatic Conservative Nudges**: Sets safe freezer target dates (+30 days for restaurant takeout, +60 days for home-cooked meals/batch cooks).
   - Instant UI feedback with confetti celebration, toast notification, and automatic redirection to the `❄️ Freezer` tab.
4. **Flexible Exit**: Users can also choose to leave remaining items in the fridge and simply close the drawer.

---

## 5. Future Roadmap & Iterations

1. **Push Notifications**:
   - Timezone-aware 11:30 AM reminder: *"You have Chicken Tikka in the fridge ready for lunch!"*
   - Evening dinner thaw reminder for freezer items flagged for today.
2. **Inventory to Grocery List Restock**:
   - When the final box of a Sunday batch cook is consumed, prompt: *"Enjoyed your last box of Lentil Soup? Add ingredients to your grocery list for Sunday."*
3. **Household Push Alerts**:
   - When a family member marks takeout leftovers as eaten or thawing, optionally inform the household so nobody double-cooks.
