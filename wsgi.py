#!/usr/bin/env python3
"""Gunicorn entrypoint."""
from app import app

# One-shot: remove venkat.santhanam@gmail.com from household
# Remove this block after deploy succeeds
import os
if os.environ.get("DATABASE_URL", "").startswith("postgres"):
    import psycopg2
    try:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        conn.autocommit = True
        cur = conn.cursor()
        email = "venkat.santhanam@gmail.com"
        cur.execute("SELECT id, household_id FROM auth_users WHERE LOWER(email) = LOWER(%s)", (email,))
        row = cur.fetchone()
        if row and row[1]:
            cur.execute("UPDATE auth_users SET household_id = NULL WHERE id = %s", (row[0],))
            cur.execute("DELETE FROM invites WHERE LOWER(email) = LOWER(%s)", (email,))
            print(f"WSGI HOOK: removed {email} (id={row[0]}) from household {row[1]}")
        else:
            print(f"WSGI HOOK: {email} not found or no household")
        conn.close()
    except Exception as e:
        print(f"WSGI HOOK ERROR: {e}")
