# Project Rules & Custom Instructions

## 0. Development Server & Git Workflow Standards
- **No Local or Dev Server Maintenance**: Do NOT spend tokens or effort attempting to fix, start, or configure the local dev server. The user does not use the local or dev server at all.
- **Explorative Inquiries First**: Do NOT jump to writing code unnecessarily. Most questions are explorative, feasibility analysis, and level of effort (LOE) determination. Provide analysis and answer conceptually before making any code modifications.
- **GitHub-Only Changes**: Any changes must be executed strictly via GitHub:
  1. Always create a GitHub issue first in `santven/listmate` to link the work.
  2. Always create a dedicated branch off `staging` to work on.
  3. Always open a Pull Request (PR) to track the work and link the branch and issue.
  4. Merge the PR into `staging` upon verification.

## 1. GitHub Issue & Branching Workflow
- **Issue First**: Always create an issue in the GitHub project (`santven/listmate`) before beginning work on any new feature, or link work to an existing issue.
- **Branching Strategy**: Always create feature branches from `staging` (e.g. `feat/<issue-number>-<short-description>`).
- **Merging Permissions**:
  - **Staging Branch**: The AI Agent has explicit permission to create Pull Requests and merge feature branches into `staging`.
  - **Main Branch (Production)**: The AI Agent is **STRICTLY FORBIDDEN** from auto-merging into `main`. Merges to `main` must either be done manually by the user or triggered when the user explicitly instructs "merge to main" or gives a "GO".

## 2. Release Management Guidelines
When creating or generating release notes for ListMate:

1. **Dual Release Notes Format**: Always create two formatted sections within the release notes:
   - **GitHub Release Notes**: Comprehensive technical breakdown including PR links, architectural changes, database fixes, and feature summaries.
   - **Google Play Store / App Store "What's New"**: A concise, copy-pasteable bulleted summary optimized for mobile store listings (under 500 characters).

2. **Storage Location**: Store both sections directly inside the GitHub Release body on GitHub (`https://github.com/santven/listmate/releases`).

## 3. Database Architecture (PostgreSQL Only)
- **Strict PostgreSQL Standard**: ListMate uses PostgreSQL exclusively for all environments (local, staging, and production).
- **No SQLite**: SQLite logic, fallback branches, or `sqlite3` imports are **STRICTLY FORBIDDEN**. All database interactions must use `db_pg.py` / PostgreSQL connection pooling and SQL syntax (e.g. `RETURNING id`, `NOW()`, `BOOLEAN`, `%s` placeholders, `ILIKE` / `LOWER()`).


## 4. Daily Cron & Notification Aggregation
- **Unified Daily Cron**: All recurring daily checks (e.g. expirations, onboarding, re-engagement) must be consolidated inside `scripts/cron_daily.py`. Do NOT create separate cron scripts.
- **Single Email Rule**: If a user is eligible for multiple notices on the same day, `cron_daily.py` must aggregate these events into a single dictionary per email address, and send ONE combined email (via `send_combined_notice` or by prioritizing the most critical alert) to avoid spamming the user.


### Branch Management & Production Safety
*   **CRITICAL:** The `main` branch is treated as production-ready (in app review/release stage). 
*   **NEVER** merge the entire `staging` branch into `main` via PRs or direct merges unless explicitly commanded by the user with "merge staging into main".
*   **NEVER OVERWRITE capacitor.config.json**: The `capacitor.config.json` on `main` must **ALWAYS** point to `https://grocerlist.app`. Under no circumstances should `capacitor.config.json` containing the staging URL ever be merged or committed to `main`. `.gitattributes` enforces `merge=ours`, and `.git/hooks/pre-push` actively blocks pushes with staging capacitor configurations.
*   To push a specific feature or bug fix to `main`, **ONLY** cherry-pick the specific commits, or apply the specific file changes as a targeted commit directly to `main`. Do not pull in unrelated changes sitting in `staging` (like experimental features or geolocation).

### Hard Guardrails for Main Branch Pushes
*   **Git Pre-push Hook Installed**: A local `.git/hooks/pre-push` script has been permanently installed in this repository to physically reject **any** push to the `main` branch.
*   **Bypassing the Guardrail**: You cannot push to `main` by accident. If and ONLY IF the user grants explicit permission to push to main, you must prepend the `EXPLICIT_MAIN_PUSH=1` environment variable to your command (e.g., `EXPLICIT_MAIN_PUSH=1 git push origin main`). Do not use this variable unless the user explicitly requested a push to main in the immediate conversation.

## 5. Automated Feedback Resolution & Loop-Closure Procedure
When the user states that a customer feedback/request is fixed and commands you to "do the automated process" or close the loop, you MUST execute the following pipeline in sequence:

> **IMPORTANT - PRODUCTION TARGETING**: If the user asks to run this on **Production**, do NOT run it against the default development database. You must temporarily connect to the production database by accessing the `PROD_DATABASE_URL` environment variable configured in `.env`.
> *(For security reasons, the raw production database URL is securely stored in `.env` and `.env.example` as a template, and MUST NOT be committed to git).*

1. **Resolve Request & Dispatch Email**: Update the database `app_feedback` table (or use the `/api/admin/feedback/<id>/resolve` endpoint). Set `status = 'resolved'`, assign the `build_number`, and provide a `resolution_note`. This automatically triggers the SendGrid resolution email to the customer with a deep link to their request (`/requests/<id>`).
2. **Public Board & In-App Modal Prep**: Ensure `is_public = True` so the item appears in the "Shipped" section of the public roadmap. Ensure `acknowledged_at = NULL` in the DB so the celebratory modal ("Your Request is Live!") triggers on their next in-app page load/refresh.
3. **GitHub Issue & PR Closure**: Ensure the original GitHub issue is closed and the feature PR is merged into `staging`.
4. **Publish GitHub Release**: Create a new GitHub Release for the build, adhering strictly to the **Dual Release Notes Format** (Rule #2) containing both the technical GitHub notes and the "What's New" App Store notes.
5. **Production Push (Only if commanded)**: If the user explicitly asks to push this fix to `main`, follow the cherry-pick and `EXPLICIT_MAIN_PUSH=1` guidelines above.

## 6. Exhaustive Code Review & Defensive Programming Guardrails
To prevent regressions and edge-case bugs in production, all code modifications MUST adhere to this strict engineering checklist prior to committing:

### Python to PostgreSQL Boundary (The "Falsiness" Rule)
*   **Zero vs. None**: Python evaluates `0` as falsy (e.g., `if household_id:`). When handling numeric database IDs, **never rely on implicit falsiness**. If `0` is an invalid ID, you MUST explicitly catch it (e.g., `if user_id == 0: user_id = None`) before it reaches SQL logic to prevent Foreign Key constraint violations.
*   **Always Coerce Types Before SQL**: Ensure frontend string inputs (e.g., `'null'`, `''`, `'0'`) are cleanly cast to Python `int` or `None` before being passed as parameters to `db_pg.py`.

### Database Integrity (PostgreSQL)
*   **Foreign Keys & Cascades**: When inserting telemetry, logs, or dependent records, always verify that the parent record (e.g., `household_id`) exists or use `ON DELETE SET NULL` / `ON DELETE CASCADE` appropriately.
*   **Connection Leaks**: Ensure all database cursors and connections are properly closed or returned to the connection pool (via context managers like `with conn.cursor()`).

### Front-End & API Contract
*   **Race Conditions**: Never assume frontend state updates are synchronous. Use React functional state updates or debounce rapid interactions (like button clicks).
*   **Graceful Failures**: All API calls must have `.catch()` blocks or `try/except` wrappers. Never let an unhandled promise rejection crash the SPA.

### PostgreSQL Timezone Invariant & Notification Anti-Reentry Rule
*   **TIMESTAMP WITHOUT TIME ZONE Gotcha**: In ListMate, all `created_at` timestamp columns in PostgreSQL are `TIMESTAMP WITHOUT TIME ZONE` stored in UTC. In PostgreSQL, applying `AT TIME ZONE '<zone>'` directly to a `TIMESTAMP WITHOUT TIME ZONE` treats the timestamp as *already local* and converts it *to UTC* (e.g., UTC 20:00 becomes UTC 02:00 next day for US/Denver).
*   **The Mandatory UTC Cast**: You MUST **ALWAYS** explicitly cast the source column to UTC first: `(ts AT TIME ZONE 'UTC') AT TIME ZONE '<target_zone>'`. Never write `DATE(ts AT TIME ZONE '<zone>')` without the inner `'UTC'` cast.
*   **Mandatory Sliding Window Guard**: Any time-based deduplication in `push_notifications_log` or `email_events` MUST include a raw interval cooldown (e.g., `created_at >= NOW() - INTERVAL '20 hours'`) in addition to any local calendar date comparisons.
*   **Dual-Layer Notification Locking**: Where applicable, notifications MUST maintain entity-level locking (e.g. `trip_notified_at`, `stash_notified_at` on `list_items`) so that once an entity is prompted, the underlying entity records that it has been notified and can NEVER qualify for the same campaign twice in its lifetime.

## 7. The Clockwork Multi-Agent Execution Protocol
Whenever a feature is requested or an issue is investigated and fixed, the system executes like clockwork through this standardized lifecycle without needing repetitive prompting:

### Step 1: Product Reality & Skepticism Check (PM Agent)
* When a new feature is proposed, `listmate_pm` rigorously challenges whether it creates real customer value or introduces friction/anti-patterns for one-handed supermarket shoppers.
* Never act as a 'yes-man'. Always evaluate: Is this an anti-pattern? Does it fit in-aisle cognitive mode? Can it be solved 10x cheaper with zero LLM runtime overhead?

### Step 2: Issue Creation First (Release Agent)
* Before touching any code or creating branches, `listmate_release` creates an issue in `santven/listmate` via GitHub API to secure `#<issue-number>`.

### Step 3: Dedicated Branch Creation (Release Agent)
* `listmate_release` checks out latest `origin/staging` and creates:
  `git checkout -b <feat|fix>/<issue-number>-<short-description>`

### Step 4: Pre-Implementation Blast-Radius & Scoped Regression Plan (Architect + QA)
* `listmate_architect` traces the blast radius: which files, DB tables, and routes are touched.
* `listmate_qa` outputs the targeted regression checklist: the exact 2 to 4 tests or UI checks to run. Never run the entire test suite across unrelated domains.

### Step 5: Engineering Implementation (Backend / Frontend)
* `listmate_backend` and/or `listmate_frontend` implement the solution on the dedicated branch.

### Step 6: Two-Layer Pre-Merge Audit Gate (Architect + QA)
* `listmate_architect` reviews the diff from the inside out: checking N+1 queries, connection pool safety, `0` vs `None` falsiness, and `household_id` scoping.
* `listmate_qa` reviews from the outside in: running only the scoped regression checks and edge cases identified in Step 4.

### Step 7: PR & Staging Merge (Release Agent)
* `listmate_release` pushes the branch, opens the PR linking `Closes #<issue-number>`, and merges into `staging`.

### Step 8: Production Promotion (Release Agent)
* Only when the user explicitly commands "merge to main" or gives a "GO", `listmate_release` cherry-picks the verified commit(s) into `main` with `EXPLICIT_MAIN_PUSH=1` and drafts dual release notes.

