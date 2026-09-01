# Feature Specification: Empowering & Inspirational Greetings (Issue #386)

**Issue**: [#386](https://github.com/santven/listmate/issues/386)  
**Linked Customer Feedback**: App Feedback #14 (`Inspirational Notification Greetings`)  
**Status**: In Design Review  
**Target Milestone**: v1.x (Staging)

---

## 1. Executive Summary & Objective

Grocery shopping, pantry management, and meal planning are recurring household chores that can often feel stressful, tedious, and purely transactional. 

Customer feedback #14 highlighted an emotional insight:
> *"Try generating empowering messages in the notifications, app landing page. Something that can make the reader feel good when the app greets them. Someone at Starbucks wrote 'stay blessed' on a cup and that was nice to read on a particular day."*

The goal of this feature is to introduce moments of unexpected delight, emotional warmth, and positive encouragement across the ListMate experience without adding cognitive clutter, latency, or intrusive UI noise.

---

## 2. Multi-Disciplinary Architecture & Personas

### 2.1 Product Manager (PM) Lens
* **User Value**: Transforms a chore app into an empathetic household companion. Validates the invisible labor of grocery shopping and home care.
* **MVP Scope Discipline**: Zero reliance on runtime LLM generation for quotes (which adds latency, cost, and risk of hallucinations). Use a rich, curated static dataset of 60+ high-quality quotes and micro-affirmations.
* **User Control**: Includes a discreet setting in User Preferences (`[x] Show daily uplifting quotes`) and a clean dismiss action (`✕`) on the in-app card.

### 2.2 Technical Architect Lens
* **Performance**: 100% client-side resolution for the web/mobile app using deterministic date-hashing. Zero additional database queries or API latency during initial bootstrap.
* **Timezone Accuracy**: Evaluates the user's local device timezone (`new Date()`) for time-of-day greetings (Morning, Afternoon, Evening, Weekend) rather than server UTC time.
* **Notification Integration**: Extends `scripts/cron_daily.py` to optionally append a warm closing sign-off to aggregated daily emails.

### 2.3 Quality Assurance (QA) Lens
* **Tone-Safety Guardrail**: Inspirational greetings must **NEVER** be displayed during error states (e.g. 500 server errors, network offline banners, expired subscriptions, or payment failures).
* **Flicker-Free UX**: The daily quote must remain stable across page reloads and route navigations throughout the calendar day (using a deterministic hash of `YYYY-MM-DD + household_id`).
* **Visual Integrity**: Clean line-height, constrained width (max 65–75ch), and strict WCAG AA contrast against the background canvas.

---

## 3. UX & Visual Design Specification

### 3.1 App Dashboard Placement
* **Position**: Positioned subtly directly beneath the main greeting header / store selector and above the store item list.
* **Layout**:
  * Clean, compact card with soft rounded corners (`rounded-xl`), subtle border (`border border-amber-200/50` or `border-emerald-200/50` in light mode), and warm neutral background (`bg-amber-50/40` or `bg-emerald-50/30`).
  * Left icon: Minimalist Sparkle or Heart icon (`lucide-react` `Sparkles` or `Heart` with soft warm accent).
  * Typography: Displayed in refined italicized body typography with high legibility.
  * Right action: Subtle dismiss icon (`X`) allowing the user to collapse the quote for the remainder of the session.

```
+-----------------------------------------------------------------------+
|  ✨  "Every item checked off is an act of care for your home."     ✕  |
+-----------------------------------------------------------------------+
```

### 3.2 Time-of-Day Dynamic Salutations
In addition to the daily quote, the dashboard greeting adapts to the user's local time:
* **05:00 – 11:59**: `"Good morning, [Name] ☕"`
* **12:00 – 16:59**: `"Good afternoon, [Name] ☀️"`
* **17:00 – 21:59**: `"Good evening, [Name] 🌙"`
* **22:00 – 04:59**: `"Rest easy, [Name] ✨"`
* **Saturday & Sunday**: `"Happy Weekend, [Name] 🌿"`

---

## 4. Curated Quote Dataset & Thematic Categories

The dataset is organized into 4 distinct thematic buckets:

### Category A: The "Act of Service" (Nourishment & Household Care)
1. *"Every item checked off is an act of care for your household."*
2. *"Stocking the pantry is the first step to gathering around the table."*
3. *"Here’s to the everyday magic of turning groceries into comforting meals."*
4. *"Taking care of the essentials today brings peace of mind tomorrow."*
5. *"Nourishing yourself and your loved ones is meaningful work."*
6. *"A well-stocked kitchen is the heart of a happy home."*
7. *"Little errands add up to big comfort for the people you love."*
8. *"Great meals and warm memories always begin with a simple list."*

### Category B: Organization, Clarity & Cognitive Relief
9. *"A clear list is a clear mind. You've got this."*
10. *"Your brain is for having ideas, not holding grocery items. We've got your list."*
11. *"One list, one trip, zero stress. Let's make it effortless."*
12. *"Order in your pantry creates calm in your day."*
13. *"Cross them off one by one. Progress is progress."*
14. *"Simplicity is the ultimate efficiency. Shop smart today."*
15. *"Checked off and out of mind. Enjoy the rest of your day."*

### Category C: Culinary & Food Appreciation (Classic Quotes)
16. *"People who love to eat are always the best people." — Julia Child*
17. *"Good food is the foundation of genuine happiness." — Auguste Escoffier*
18. *"First we eat, then we do everything else." — M.F.K. Fisher*
19. *"Cooking is love made edible."*
20. *"The secret ingredient is always care."*
21. *"Pull up a chair. Take a taste. Come join us. Life is so endlessly delicious." — Ruth Reichl*
22. *"Laughter is brightest where food is best." — Irish Proverb*

### Category D: Contextual & Micro-Affirmations
23. *"Weekend restock mode: Activated. Treat yourself to something delicious."*
24. *"Fresh start, fresh produce, great energy for the week ahead."*
25. *"Take a deep breath in the grocery aisle. You are doing great."*
26. *"May your shopping trip be quick and your produce perfectly ripe."*
27. *"Remember to grab a little treat for yourself today—you earned it."*
28. *"Clear lists make smooth grocery runs. Let's get it done!"*

---

## 5. Technical Implementation Details

### 5.1 Deterministic Date Rotation Algorithm (Frontend)
To ensure the quote is consistent throughout a user's day:
```typescript
export function getDailyGreeting(quotes: string[], seedDate: Date = new Date()): string {
  const dateStr = `${seedDate.getFullYear()}-${seedDate.getMonth() + 1}-${seedDate.getDate()}`;
  let hash = 0;
  for (let i = 0; i < dateStr.length; i++) {
    hash = (hash << 5) - hash + dateStr.charCodeAt(i);
    hash |= 0;
  }
  const index = Math.abs(hash) % quotes.length;
  return quotes[index];
}
```

### 5.2 Daily Cron Notification Integration (`scripts/cron_daily.py`)
In aggregate email digests:
* When a daily summary or reminder is sent, the footer can optionally include a small warm sign-off:
  ```html
  <p style="margin-top: 24px; font-style: italic; color: #6b7280; font-size: 13px; text-align: center;">
    "{{ daily_affirmation }}"
  </p>
  ```

---

## 6. Open Discussion Points for User Review
1. **Banner Visibility**: Should the daily inspirational card be visible by default on every app open, or should it automatically collapse once the user starts checking off items in a store?
2. **Custom Quotes**: Would we ever want households to add their own private family mantras or reminder notes to their quote rotation?
3. **Notification Tone**: Should we include these quotes in daily notification emails, or keep them strictly within the in-app dashboard?
