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

