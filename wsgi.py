#!/usr/bin/env python3
"""Gunicorn entrypoint."""
from app import app

# One-shot: nuke preeven.raghav@gmail.com from household 1
import os
if os.environ.get("DATABASE_URL", "").startswith("postgres"):
    import psycopg2
    try:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        conn.autocommit = True
        cur = conn.cursor()
        
        email = "preeven.raghav@gmail.com"
        
        # 1. Find ALL auth_users rows for this email
        cur.execute("SELECT id, household_id, google_id, name FROM auth_users WHERE LOWER(email) = LOWER(%s)", (email,))
        rows = cur.fetchall()
        for r in rows:
            print(f"auth_user: id={r[0]} hh={r[1]} google_id={'SET' if r[2] else 'none'} name={r[3]}")
        
        # 2. Find any invites
        cur.execute("SELECT id, email, household_id FROM invites WHERE LOWER(email) = LOWER(%s)", (email,))
        inv = cur.fetchall()
        for i in inv:
            print(f"invite: id={i[0]} email={i[1]} hh={i[2]}")
        
        # 3. Find any tokens/sessions (if we have a sessions table)
        cur.execute("""SELECT table_name FROM information_schema.tables WHERE table_schema='public'""")
        tables = [t[0] for t in cur.fetchall()]
        print(f"All tables: {tables}")
        
        # 4. Nuke all references
        cur.execute("DELETE FROM invites WHERE LOWER(email) = LOWER(%s)", (email,))
        print(f"Deleted invites: {cur.rowcount}")
        
        cur.execute("DELETE FROM auth_users WHERE LOWER(email) = LOWER(%s)", (email,))
        print(f"Deleted auth_users: {cur.rowcount}")
        
        # Verify
        cur.execute("SELECT count(*) FROM auth_users WHERE LOWER(email) = LOWER(%s)", (email,))
        remaining_users = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM invites WHERE LOWER(email) = LOWER(%s)", (email,))
        remaining_invites = cur.fetchone()[0]
        
        print(f"After cleanup — auth_users: {remaining_users}, invites: {remaining_invites}")
        
        cur.close()
        conn.close()
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
