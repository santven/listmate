#!/usr/bin/env python3
"""Grocery DB — SQLite backend. Used when DATABASE_URL is not set."""
import os, sqlite3

DB_PATH = os.environ.get("DB_PATH", "listmate.db")


def get_db():
    """Return a sqlite3 connection (compatible with db_pg.get_db API)."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def close_db(conn):
    if conn: conn.close()


def _add_column_if_missing(db, table, column, coldef):
    """Add a column if it doesn't exist (SQLite doesn't support IF NOT EXISTS for ALTER)."""
    cols = [r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coldef}")
        return True
    return False


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")

    # Create legacy tables if they don't exist
    db.executescript("""
        CREATE TABLE IF NOT EXISTS stores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS store_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            UNIQUE(store_id, name COLLATE NOCASE),
            FOREIGN KEY (store_id) REFERENCES stores(id)
        );
        CREATE TABLE IF NOT EXISTS list_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            added_by TEXT NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            purchased INTEGER DEFAULT 0,
            purchased_by TEXT,
            purchased_at TIMESTAMP,
            FOREIGN KEY (store_id) REFERENCES stores(id)
        );
    """)

    # Migrate: add household_id columns
    for tbl in ("stores", "store_items", "list_items"):
        _add_column_if_missing(db, tbl, "household_id", "INTEGER NOT NULL DEFAULT 1")

    # Migrate: add category column
    for tbl in ("store_items", "list_items"):
        _add_column_if_missing(db, tbl, "category", "TEXT NOT NULL DEFAULT ''")

    # Recreate indexes (add if missing)
    try:
        db.execute("CREATE INDEX IF NOT EXISTS idx_list_household ON list_items(household_id, purchased)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_store_household ON stores(household_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_sitems_store ON store_items(store_id)")
    except Exception:
        pass

    # Seed default stores for household 1 (Raghav) — no-op if already exist
    defaults = ["Costco", "Whole Foods", "Valli", "Patel / IndiaCo", "Jewel"]
    for s in defaults:
        db.execute("INSERT OR IGNORE INTO stores (household_id, name) VALUES (1, ?)", (s,))

    # Drop the UNIQUE constraint on store name alone (since we now have household_id)
    # SQLite doesn't support ALTER DROP CONSTRAINT, so we just create the replacement unique index
    db.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_store_hh_name ON stores(household_id, name COLLATE NOCASE)
    """)

    db.commit()

    # Verify
    stores = db.execute("SELECT household_id, COUNT(*) FROM stores GROUP BY household_id").fetchall()
    items = db.execute("SELECT COUNT(*) FROM list_items").fetchone()[0]
    for s in stores:
        names = [r["name"] for r in db.execute("SELECT name FROM stores WHERE household_id = ?", (s["household_id"],)).fetchall()]
        print(f"  household {s['household_id']}: {s[1]} stores → {names}")
    print(f"  {items} list items total")
    print(f"✅ Grocery DB ready")

    db.close()


if __name__ == "__main__":
    init_db()
