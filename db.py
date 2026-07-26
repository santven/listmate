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
        CREATE TABLE IF NOT EXISTS recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            household_id INTEGER NOT NULL DEFAULT 1,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            prep_time TEXT DEFAULT '',
            cook_time TEXT DEFAULT '',
            servings TEXT DEFAULT '',
            cuisine TEXT DEFAULT '',
            dietary_tags TEXT DEFAULT '',
            instructions TEXT DEFAULT '',
            ingredients TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        CREATE TABLE IF NOT EXISTS store_visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            household_id INTEGER NOT NULL DEFAULT 1,
            visit_date TEXT NOT NULL,
            items_count INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (store_id) REFERENCES stores(id)
        );
        CREATE TABLE IF NOT EXISTS recipe_generations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            household_id INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS store_enrich_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            household_id INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP
        );
    """)

    # Migrate: add household_id columns
    for tbl in ("stores", "store_items", "list_items"):
        _add_column_if_missing(db, tbl, "household_id", "INTEGER NOT NULL DEFAULT 1")

    _add_column_if_missing(db, "stores", "category_order", "TEXT DEFAULT ''")
    _add_column_if_missing(db, "stores", "cuisine", "TEXT DEFAULT ''")
    _add_column_if_missing(db, "stores", "auto_populated", "INTEGER DEFAULT 0")
    # Migrate: add category column
    for tbl in ("store_items", "list_items"):
        _add_column_if_missing(db, tbl, "category", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(db, "list_items", "quantity", "TEXT DEFAULT ''")
    _add_column_if_missing(db, "list_items", "recipe_tag", "TEXT DEFAULT ''")

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

    
    # Seed default smart aisle category orders
    default_aisle_patterns = [
        ("%patel%", "Produce,Spices & Seasonings,Legumes & Grains,Indian Specialties,Nuts & Seeds,Dips & Spreads,Canned & Jarred,Snacks & Sweets,Beverages,Dairy,Frozen,Household"),
        ("%indiaco%", "Produce,Spices & Seasonings,Legumes & Grains,Indian Specialties,Nuts & Seeds,Dips & Spreads,Canned & Jarred,Snacks & Sweets,Beverages,Dairy,Frozen,Household"),
        ("%indian%", "Produce,Spices & Seasonings,Legumes & Grains,Indian Specialties,Nuts & Seeds,Dips & Spreads,Canned & Jarred,Snacks & Sweets,Beverages,Dairy,Frozen,Household"),
        ("%costco%", "Produce,Bakery,Deli,Meat & Seafood,Pantry,Snacks & Sweets,Beverages,Frozen,Household,Dairy"),
        ("%whole foods%", "Produce,Bakery,Meat & Seafood,Deli,Pantry,Canned & Jarred,Dairy,Frozen,Household"),
        ("%jewel%", "Produce,Bakery,Meat & Seafood,Deli,Pantry,Canned & Jarred,Dairy,Frozen,Household"),
        ("%valli%", "Produce,Bakery,Meat & Seafood,Deli,Pantry,Canned & Jarred,Dairy,Frozen,Household")
    ]
    for pattern, order in default_aisle_patterns:
        try: db.execute("UPDATE stores SET category_order = ? WHERE LOWER(name) LIKE ? AND (category_order IS NULL OR category_order = '' OR category_order NOT LIKE '%Spices%')", (order, pattern))
        except Exception: pass
    try: db.execute("UPDATE stores SET category_order = 'Produce,Bakery,Meat & Seafood,Deli,Spices & Seasonings,Legumes & Grains,Pantry,Canned & Jarred,Dips & Spreads,Nuts & Seeds,Snacks & Sweets,Beverages,Dairy,Frozen,Household' WHERE (category_order IS NULL OR category_order = '')")
    except Exception: pass

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
