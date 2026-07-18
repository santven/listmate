#!/usr/bin/env python3
"""One-shot migration: SQLite → PostgreSQL.
Reads the local SQLite database and writes all data to a PostgreSQL instance.
USAGE: DATABASE_URL=postgres://... python3 migrate_to_pg.py

Safe to run multiple times — uses INSERT ... ON CONFLICT to skip duplicates.
"""

import os
import sqlite3
import sys

try:
    import psycopg2
    from psycopg2 import extras
except ImportError:
    print("Install psycopg2: pip install psycopg2-binary")
    sys.exit(1)

SQLITE_PATH = os.environ.get("SQLITE_PATH", "listmate.db")
BATCH_SIZE = 500


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: set DATABASE_URL environment variable")
        sys.exit(1)

    print(f"📦 Source: {SQLITE_PATH}")
    print(f"🎯 Target: {url[:url.index('@')]}@***")

    # Connect to both
    sq = sqlite3.connect(SQLITE_PATH)
    sq.row_factory = sqlite3.Row

    pg = psycopg2.connect(url)
    pg.autocommit = False

    # Create schema
    from db_pg import SCHEMA_SQL, init_db
    init_db()

    # ── Migrate stores ──
    stores = sq.execute("SELECT * FROM stores").fetchall()
    cur = pg.cursor()
    for s in stores:
        cur.execute(
            "INSERT INTO stores (id, name, household_id, created_at) VALUES (%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name",
            (s["id"], s["name"], s.get("household_id", 1), s["created_at"])
        )
    pg.commit()
    print(f"  ✅ Stores: {len(stores)} rows")

    # ── Migrate store_items ──
    items = sq.execute("SELECT * FROM store_items").fetchall()
    for i, s in enumerate(items):
        cur.execute(
            "INSERT INTO store_items (id, store_id, name, category, household_id) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, category=EXCLUDED.category",
            (s["id"], s["store_id"], s["name"], s.get("category", ""), s.get("household_id", 1))
        )
        if (i + 1) % BATCH_SIZE == 0:
            pg.commit()
    pg.commit()
    print(f"  ✅ Store items: {len(items)} rows")

    # ── Migrate list_items ──
    entries = sq.execute("SELECT * FROM list_items").fetchall()
    for i, e in enumerate(entries):
        cur.execute(
            """INSERT INTO list_items (id, store_id, name, category, added_by, added_at, purchased, purchased_by, purchased_at, household_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, category=EXCLUDED.category, purchased=EXCLUDED.purchased""",
            (e["id"], e["store_id"], e["name"], e.get("category", ""),
             e.get("added_by", ""), e["added_at"],
             bool(e["purchased"]),
             e.get("purchased_by"), e.get("purchased_at"),
             e.get("household_id", 1))
        )
        if (i + 1) % BATCH_SIZE == 0:
            pg.commit()
    pg.commit()
    print(f"  ✅ List items: {len(entries)} rows")

    # ── Migrate store_visits ──
    visits = sq.execute("SELECT * FROM store_visits").fetchall()
    for v in visits:
        cur.execute(
            "INSERT INTO store_visits (id, store_id, household_id, visit_date, items_count, created_at) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
            (v["id"], v["store_id"], v.get("household_id", 1), v["visit_date"], v["items_count"], v["created_at"])
        )
    pg.commit()
    print(f"  ✅ Store visits: {len(visits)} rows")

    # ── Verify ──
    cur.execute("SELECT COUNT(*) as cnt FROM stores")
    pg_stores = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) as cnt FROM list_items")
    pg_items = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) as cnt FROM store_visits")
    pg_visits = cur.fetchone()["cnt"]

    print(f"\n  Verifying:")
    print(f"    Stores:      SQLite={len(stores)}  Postgres={pg_stores}  {'✅' if len(stores)==pg_stores else '❌'}")
    print(f"    List items:  SQLite={len(entries)}  Postgres={pg_items}  {'✅' if len(entries)==pg_items else '❌'}")
    print(f"    Visits:      SQLite={len(visits)}  Postgres={pg_visits}  {'✅' if len(visits)==pg_visits else '❌'}")

    cur.close()
    pg.close()
    sq.close()
    print("\n🎉 Migration complete.")


if __name__ == "__main__":
    main()
