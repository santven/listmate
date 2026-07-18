# Listmate 🛒

Store-specific grocery list for households. Know what to buy at every store.

**Built for Indian-American households** — understands daal, roti, and paneer as well as bread and milk.

## Features

- 🏪 **Store-organized lists** — Costco, Whole Foods, Patel Bros, Jewel... each has its own catalog
- 🏷️ **Auto-categorization** — 500+ keywords across 12 categories (Dairy, Produce, Bakery, Pantry, Indian Grocery...)
- 💡 **Purchase pattern suggestions** — wiggle reminders for items you buy regularly
- 👨‍👩‍👧‍👦 **Household sharing** — invite family members, everyone sees the same list
- 📝 **Visit tracking** — knows when you last shopped at each store
- 🔒 **Google Sign-In** — no passwords to remember

## Tech Stack

| Layer | Tech |
|---|---|
| Backend | Python 3 + Flask |
| Database | SQLite (local) / PostgreSQL (production) |
| Auth | Google OAuth 2.0 |
| Frontend | Vanilla JS, service worker PWA |

## Local Development

```bash
pip install -r requirements.txt
python3 -m flask run -p 5003
```

## Deployment

The app auto-detects `DATABASE_URL` environment variable:
- **Not set** → uses local SQLite (`listmate.db`)
- **Set** → uses PostgreSQL with connection pooling

```bash
DATABASE_URL=postgres://... gunicorn wsgi:app
```

## Migration from SQLite

```bash
DATABASE_URL=postgres://... python3 migrate_to_pg.py
```

## Project Structure

```
listmate/
├── app.py              # Flask application
├── db.py               # SQLite database module
├── db_pg.py            # PostgreSQL database module (cloud)
├── migrate_to_pg.py    # SQLite → PG migration script
├── categorize.py       # Auto-categorizer (500+ keywords)
├── wsgi.py             # Gunicorn entrypoint
├── shared/
│   └── auth.py         # Google SSO + household management
├── static/
│   ├── index.html      # Main grocery list UI
│   ├── login.html      # Google Sign-In page
│   ├── signup.html     # Household signup
│   ├── settings.html   # User settings
│   ├── sw.js           # Service worker (PWA)
│   └── manifest.json   # PWA manifest
└── BACKLOG.md          # Go-to-market sprint plan
```
