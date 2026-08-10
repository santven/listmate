# ListMate Database Indexing Strategy

As ListMate's database grows over time, maintaining optimal query performance is critical, especially with the introduction of historical tracking (store visits) and AI-driven analytics.

## Current State of the Database

Our database schema currently implements a solid baseline of indexes covering the most frequent transactional operations (CRUD). The following indexes are already in place and actively optimizing our app:

*   **`stores`**: `(household_id)` and a unique constraint on `(household_id, name)`. This makes listing a household's stores and preventing duplicate store names very fast.
*   **`store_items`**: `(store_id, household_id)`, `(LOWER(name))`, and `(household_id, store_id, name)`. This allows instant lookups when checking if an item already exists in a store's master catalog during typing.
*   **`list_items`**: `(store_id, household_id, purchased)`, `(LOWER(name))`, and `(household_id)`. This heavily optimizes loading a specific store's active list and checking item existence.
*   **`store_visits`**: `(store_id, household_id, visit_date)`. This optimizes looking up the history for a specific store.
*   **`recipes` & `recipe_generations`**: Indexed by `(household_id)` and `(household_id, created_at)` to optimize pagination and rate limiting for Chef AI.
*   **`item_purchase_stats`**: Unique constraint on `(household_id, name)` to ensure accurate upserts (inserts or updates).

## Recommended Future Indexes (Growth Optimization)

With the recent additions of **Analytics** and **AI Insights**, we have introduced new queries that aggregate data across time and across all stores for a household. As users build up months or years of shopping history, these specific queries will begin to slow down.

We recommend adding the following indexes in a future database migration to future-proof the application:

### 1. `store_visits (household_id, visit_date)`
*   **The Query:** `SELECT ... FROM store_visits WHERE household_id = ? AND visit_date >= CURRENT_DATE - INTERVAL '90 days'`
*   **Why we need it:** The existing index `(store_id, household_id, visit_date)` cannot be used efficiently because `store_id` is omitted in this query. Adding this new index will prevent full table scans when generating the household's 90-day trip frequency charts.

### 2. `item_purchase_stats (household_id, total_purchases DESC)`
*   **The Query:** `SELECT ... FROM item_purchase_stats WHERE household_id = ? ORDER BY total_purchases DESC LIMIT 10`
*   **Why we need it:** Currently, Postgres uses the unique index to find all items for the household, but then it must perform an **in-memory sort** of all those items to find the top 10. By including `total_purchases DESC` in a compound index, Postgres can retrieve the top 10 items instantly without sorting.

### 3. `list_items (household_id, purchased)`
*   **The Query:** `SELECT ... FROM list_items l WHERE l.household_id = ? AND l.purchased = FALSE`
*   **Why we need it:** When the app loads, it fetches all unpurchased items across all stores. Over time, the `list_items` table will become dominated by historical `purchased = TRUE` items (the "graveyard"). We currently only have an index on `(household_id)`. Upgrading this to `(household_id, purchased)` allows Postgres to entirely skip the thousands of purchased items when loading the active lists.

### 4. `item_purchase_stats (household_id, category)`
*   **The Query:** `SELECT category, SUM(total_purchases) FROM item_purchase_stats WHERE household_id = ? GROUP BY category`
*   **Why we need it:** This powers the "Top Categories" pie chart in Analytics. This index pre-sorts the data by category for a given household, dramatically speeding up the `GROUP BY` aggregation step.
