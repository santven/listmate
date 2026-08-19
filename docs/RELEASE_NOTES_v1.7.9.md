# ListMate v1.7.9 Release Notes

## 📋 GitHub Release Notes

### 🌟 Overview
ListMate v1.7.9 introduces an interactive, non-intrusive Guided Feature Discovery system designed to smoothly onboard new and existing household members. Rather than disruptive full-screen modal takeovers, elegant pulsating amber halos spotlight key features directly on the live interface, opening informative bottom-sheet explanation drawers on demand.

### 🚀 Key Features & Architectural Enhancements

#### 1. Interactive Discovery Halos (#310)
- **Non-Intrusive Spotlight Engine**: Utilizes a lightweight CSS pulse halo (`@keyframes listmateAmberPulse`) that points users to key interactive elements without interrupting normal grocery shopping workflows.
- **On-Demand Bottom Sheet Drawers**: Tapping any spotlighted element smoothly opens a slide-up drawer explaining the feature's core value with crisp, actionable verbiage and clean dismissal.
- **Smart Sequence & Completion Tracking**: Automatically progresses through tour touchpoints:
  1. `invite`: Adding & inviting household members for real-time multi-user synchronization.
  2. `stores_vs_general`: Clarifying the General List as a flexible catch-all notepad for items before assigning them to stores.
  3. `store_specific`: Creating new store lists or exploring store-specific master catalogs.
  4. `quick_add`: Rapid item entry with smart routing and store memory.
  5. `shopping_list_view`: In-store shopping mode with aisle checklists, out-of-stock moving (`⇄`), and item clearing (`✕`).
  6. `move_items`: Cross-store aisle reassignment.
  7. `switch_household`: Multi-household switching (dynamically displayed for users belonging to multiple households).
- **Settings Toggle & Synchronization**: Full toggle control in Settings (`/settings`) allowing users to pause spotlights or reset all tips anytime. Automatically toggles OFF with a green completion indicator once all tips are completed.

#### 2. Marketing & Onboarding Optimizations (#314)
- Default marketing and tips opt-in set to enabled for US registrations to improve onboarding engagement.

---

## 📱 Google Play Store / App Store "What's New"

```text
- 💡 Interactive Feature Discovery: Learn key features like aisle sorting, smart routing, and catch-all lists with subtle spotlight guides.
- 📋 General List vs. Store Catalogs: Easily organize items across stores or keep them in your catch-all list.
- 🛒 In-Store Shopping Mode: Check off items in real time, move out-of-stock items, or clear with one tap.
- ⚡ Quick Add: Instantly add groceries with smart store memory.
```
