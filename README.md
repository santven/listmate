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
| Database | PostgreSQL |
| Auth | Google OAuth 2.0 |
| Frontend | Vanilla JS, service worker PWA |

## Local Development

```bash
pip install -r requirements.txt
python3 -m flask run -p 5003
```

## Deployment

```bash
DATABASE_URL=postgres://... gunicorn wsgi:app
```

## Project Structure

```
listmate/
├── app.py              # Flask application
├── db_pg.py            # PostgreSQL database module
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

## Background Jobs
Listmate uses a single consolidated cron script `scripts/cron_daily.py` designed to run daily (e.g., at 8 AM). 

It handles multiple automated workflows while ensuring a user receives **at most one combined email** per day:
- **Trial Expirations**: Reminds users 3 days before and on the day their 30-day trial ends.
- **Activation**: Engages users who signed up 3 days ago but haven't added any items to their list.
- **Re-engagement**: Re-engages users who haven't added an item in 14 days.
