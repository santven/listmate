# Issue: Streamlining & Information Architecture Refactor for Settings Screen

**Status:** Backlog / Prioritized Architecture Enhancement  
**Target File:** `static/settings.html` (~3,700 lines)  
**Author:** ListMate Product & Architecture Team  
**Date:** October 2026  

---

## 1. Problem Statement

As ListMate expanded from a single store-specific grocery list into an all-in-one kitchen operating system (encompassing **Grocery Planning**, **Still Good** fridge waste tracking, and **Nourish** AI nutrition tracking, along with granular **Email Preferences**, **Household Invites**, and **Billing**), [`static/settings.html`](static/settings.html) has accumulated significant structural length (~3,700 lines).

### Key Pain Points:
1. **Endless Linear Scroll ("The Infinite Settings Wall"):**
   Users must scroll past multiple screen-heights of configuration cards (User Profile, Household Members, Nourish Goals, Still Good Snooze cadences, Push Notifications, Granular Email Preferences, Dietary Restrictions, Location, App Updates, and Legal/Account Deletion) to reach desired actions.
2. **Cognitive Overload:**
   Infrequent actions (e.g. exporting household data, deleting accounts, inspecting store catalogs) compete visually with high-frequency actions (e.g. toggling push reminders, managing household members, or adjusting Nourish goals).
3. **Redundant Suite Management:**
   Features like Nourish and Still Good have settings scattered between in-screen menus, top modals, and the global settings page.

---

## 2. Proposed Solution: Grouped Hub & Progressive Disclosure

Instead of an unbroken vertical stack of 12+ full-width cards, transition `settings.html` to a **Categorized Hub Architecture** with progressive disclosure (collapsible accordions or a clean tabbed/hub layout).

```
┌──────────────────────────────────────────────┐
│  ⚙️ Settings                                  │
│  Santhanam Family (Household #101)           │
├──────────────────────────────────────────────┤
│                                              │
│  👤 Account & Profile             [ > ]      │
│     venkat@... · Family Owner                │
│                                              │
│  👨‍👩‍👧 Household & Members          [ > ]      │
│     2 Members · Invite Partner               │
│                                              │
│  🥗 Nourish Nutrition Preferences  [ > ]      │
│     Daily Goals, AI Limits & Sharing         │
│                                              │
│  🧊 Still Good Food Waste          [ > ]      │
│     Snooze Cadence & Reminders               │
│                                              │
│  🔔 Notifications & Email Prefs    [ > ]      │
│     Push Alerts, Granular Categories         │
│                                              │
│  💳 Subscription & Billing         [ > ]      │
│     Pro Lifetime / Annual                    │
│                                              │
│  🔒 Privacy, Data & Legal          [ > ]      │
│     Export Data, Terms, Logout               │
│                                              │
└──────────────────────────────────────────────┘
```

---

## 3. Recommended Phased Implementation

### Phase 1: Accordion / Categorized Grouping (Quickest Win)
- Group the existing cards into 5 collapsible category accordions:
  1. **Account & Household** (User Profile, Household Members, Add Partner)
  2. **App Suites** (Nourish Goals, Still Good Preferences, Dietary Restrictions)
  3. **Alerts & Communications** (Push Notifications, Granular Email Preferences)
  4. **Billing & Plan** (Subscription Status, Upgrade/Restore)
  5. **Data & Privacy** (Export Grocery Data, Privacy Policy, Logout, Delete Account)
- Keep state in URL hash or `sessionStorage` (e.g. `settings.html#nourish` auto-expands the Nourish group).

### Phase 2: Componentization & Modular CSS/JS
- Extract inline scripts into modular helper components (e.g. `settings_members.js`, `settings_billing.js`, `settings_email_prefs.js`).
- Reduce DOM weight and initial parse time for low-end mobile devices.

---

## 4. Acceptance Criteria
- [ ] First viewport of `settings.html` displays all major setting categories without requiring vertical scroll on standard mobile screens (375px–430px).
- [ ] Search or 1-tap navigation directly jumps to deep links (e.g. `settings.html?tab=email_preferences` or `settings.html?tab=household`).
- [ ] No regression in form submissions, member invites, RevenueCat billing restore, or email preference HMAC generation.
