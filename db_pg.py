#!/usr/bin/env python3
"""PostgreSQL — connection pool (ThreadedConnectionPool) for Render/Neon."""

import os, re, psycopg2
from psycopg2 import pool as _pool

_pool_ctx = None

def _get_pool():
    global _pool_ctx
    if _pool_ctx is None:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL not set")
        # Neon free tier: keep min=1, max=4 connections
        _pool_ctx = _pool.ThreadedConnectionPool(1, 4, url)
    return _pool_ctx

def get_db():
    return PgConnection(_get_pool().getconn())

def close_db(conn):
    if conn:
        try: conn.close()
        except Exception: pass

class PgConnection:
    def __init__(self, conn):
        self._conn = conn
        self._cur = None
        self._last_rowcount = 0
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def execute(self, sql, params=None):
        sql = re.sub(r'\?', '%s', sql)
        if self._cur:
            try: self._cur.close()
            except Exception: pass
            self._cur = None

        try:
            self._cur = self._conn.cursor()
            if params: self._cur.execute(sql, params)
            else: self._cur.execute(sql)
            self._last_rowcount = self._cur.rowcount
            return self
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            # Connection dropped (e.g. SSL closed unexpectedly after idle timeout).
            # Discard dead connection, request a fresh one from the pool, and retry statement.
            try:
                _get_pool().putconn(self._conn, close=True)
            except Exception:
                pass
            self._conn = _get_pool().getconn()
            self._cur = self._conn.cursor()
            if params: self._cur.execute(sql, params)
            else: self._cur.execute(sql)
            self._last_rowcount = self._cur.rowcount
            return self

    def fetchall(self):
        if self._cur is None or self._cur.description is None: return []
        rows = self._cur.fetchall()
        return [dict(zip([d[0] for d in self._cur.description], r)) for r in rows]

    def fetchone(self):
        if self._cur is None or self._cur.description is None: return None
        row = self._cur.fetchone()
        if row is None: return None
        return dict(zip([d[0] for d in self._cur.description], row))

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._cur:
            try: self._cur.close()
            except Exception: pass
            self._cur = None
        if self._conn:
            is_broken = getattr(self._conn, 'closed', False) != 0
            if not is_broken:
                try:
                    self._conn.commit()
                except Exception:
                    is_broken = True
            try:
                _get_pool().putconn(self._conn, close=is_broken)
            except Exception:
                try: self._conn.close()
                except Exception: pass
            self._conn = None

    def commit(self):
        if self._conn and not getattr(self._conn, 'closed', False):
            self._conn.commit()

    def rollback(self):
        if self._conn and not getattr(self._conn, 'closed', False):
            self._conn.rollback()

    total_changes = property(lambda self: self._last_rowcount)

_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS stores (id SERIAL PRIMARY KEY, name TEXT NOT NULL, household_id INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMP NOT NULL DEFAULT NOW())",
    "CREATE TABLE IF NOT EXISTS store_items (id SERIAL PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), name TEXT NOT NULL, category TEXT NOT NULL DEFAULT '', household_id INTEGER NOT NULL DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS list_items (id SERIAL PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), name TEXT NOT NULL, category TEXT NOT NULL DEFAULT '', added_by TEXT NOT NULL DEFAULT '', added_at TIMESTAMP NOT NULL DEFAULT NOW(), purchased BOOLEAN NOT NULL DEFAULT FALSE, purchased_by TEXT, purchased_at TIMESTAMP, quantity TEXT DEFAULT '', household_id INTEGER NOT NULL DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS store_visits (id SERIAL PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), household_id INTEGER NOT NULL DEFAULT 1, visit_date DATE NOT NULL, items_count INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMP NOT NULL DEFAULT NOW())",
    "CREATE TABLE IF NOT EXISTS store_enrich_queue (id SERIAL PRIMARY KEY, store_id INTEGER NOT NULL, household_id INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'pending', created_at TIMESTAMP NOT NULL DEFAULT NOW(), processed_at TIMESTAMP)",
    "CREATE INDEX IF NOT EXISTS idx_si_store ON store_items(store_id, household_id)",
    "CREATE INDEX IF NOT EXISTS idx_si_name ON store_items(LOWER(name))",
    "CREATE INDEX IF NOT EXISTS idx_li_store ON list_items(store_id, household_id, purchased)",
    "CREATE INDEX IF NOT EXISTS idx_li_name ON list_items(LOWER(name))",
    "CREATE INDEX IF NOT EXISTS idx_li_user ON list_items(household_id)",
    "CREATE INDEX IF NOT EXISTS idx_sv_store ON store_visits(store_id, household_id, visit_date)",
    "CREATE INDEX IF NOT EXISTS idx_stores_hh ON stores(household_id)",
]

def init_db():
    db = get_db()
    try:
        for s in _SCHEMA: db.execute(s)
        try: db.execute("ALTER TABLE list_items ADD COLUMN IF NOT EXISTS quantity TEXT DEFAULT ''")
        except Exception: pass
        try: db.execute("ALTER TABLE stores ADD COLUMN IF NOT EXISTS category_order TEXT DEFAULT ''")
        except Exception: pass
        try: db.execute("ALTER TABLE stores ADD COLUMN IF NOT EXISTS cuisine TEXT DEFAULT ''")
        except Exception: pass
        try: db.execute("ALTER TABLE stores ADD COLUMN IF NOT EXISTS auto_populated BOOLEAN DEFAULT FALSE")
        except Exception: pass

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
            try: db.execute("UPDATE stores SET category_order = %s WHERE name ILIKE %s AND (category_order IS NULL OR category_order = '' OR category_order NOT LIKE '%Spices%')", (order, pattern))
            except Exception: pass
        try: db.execute("UPDATE stores SET category_order = 'Produce,Bakery,Meat & Seafood,Deli,Spices & Seasonings,Legumes & Grains,Pantry,Canned & Jarred,Dips & Spreads,Nuts & Seeds,Snacks & Sweets,Beverages,Dairy,Frozen,Household' WHERE (category_order IS NULL OR category_order = '')")
        except Exception: pass

        db.commit()
    finally: close_db(db)
