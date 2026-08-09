# Project Rules & Custom Instructions

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
*   To push a specific feature or bug fix to `main`, **ONLY** cherry-pick the specific commits, or apply the specific file changes as a targeted commit directly to `main`. Do not pull in unrelated changes sitting in `staging` (like experimental features or geolocation).

### Hard Guardrails for Main Branch Pushes
*   **Git Pre-push Hook Installed**: A local `.git/hooks/pre-push` script has been permanently installed in this repository to physically reject **any** push to the `main` branch.
*   **Bypassing the Guardrail**: You cannot push to `main` by accident. If and ONLY IF the user grants explicit permission to push to main, you must prepend the `EXPLICIT_MAIN_PUSH=1` environment variable to your command (e.g., `EXPLICIT_MAIN_PUSH=1 git push origin main`). Do not use this variable unless the user explicitly requested a push to main in the immediate conversation.
