#!/usr/bin/env python3
"""PostgreSQL — direct connections (same pattern as auth module, which works)."""
import os, re, psycopg2

def get_db():
    url = os.environ.get("DATABASE_URL")
    if not url: raise RuntimeError("DATABASE_URL not set")
    conn = psycopg2.connect(url)
    conn.autocommit = False
    return PgConnection(conn)

def close_db(conn):
    if conn:
        try: conn._conn.close()
        except: pass


class PgConnection:
    def __init__(self, conn):
        self._conn = conn
        self._cur = None
        self._last_rowcount = 0

    def execute(self, sql, params=None):
        sql = re.sub(r'\?', '%s', sql)
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
        if self._cur:
            try: self._cur.close()
            except: pass
            self._cur = None
        try: self._conn.commit()
        except: pass
        try: self._conn.close()
        except: pass

    def commit(self): self._conn.commit()
    def rollback(self): self._conn.rollback()
    total_changes = property(lambda self: self._last_rowcount)


_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS stores (id SERIAL PRIMARY KEY, name TEXT NOT NULL, household_id INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMP NOT NULL DEFAULT NOW())",
    "CREATE TABLE IF NOT EXISTS store_items (id SERIAL PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), name TEXT NOT NULL, category TEXT NOT NULL DEFAULT '', household_id INTEGER NOT NULL DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS list_items (id SERIAL PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), name TEXT NOT NULL, category TEXT NOT NULL DEFAULT '', added_by TEXT NOT NULL DEFAULT '', added_at TIMESTAMP NOT NULL DEFAULT NOW(), purchased BOOLEAN NOT NULL DEFAULT FALSE, purchased_by TEXT, purchased_at TIMESTAMP, household_id INTEGER NOT NULL DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS store_visits (id SERIAL PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), household_id INTEGER NOT NULL DEFAULT 1, visit_date DATE NOT NULL, items_count INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMP NOT NULL DEFAULT NOW())",
    "CREATE TABLE IF NOT EXISTS store_enrich_queue (id SERIAL PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), household_id INTEGER NOT NULL DEFAULT 1, city TEXT, state TEXT, country TEXT, zip_code TEXT, status TEXT NOT NULL DEFAULT 'pending', created_at TIMESTAMP NOT NULL DEFAULT NOW(), processed_at TIMESTAMP)",
    "CREATE INDEX IF NOT EXISTS idx_si_store ON store_items(store_id, household_id)",
    "CREATE INDEX IF NOT EXISTS idx_si_name ON store_items(LOWER(name))",
    "CREATE INDEX IF NOT EXISTS idx_li_store ON list_items(store_id, household_id, purchased)",
    "CREATE INDEX IF NOT EXISTS idx_li_name ON list_items(LOWER(name))",
    "CREATE INDEX IF NOT EXISTS idx_li_user ON list_items(household_id)",
    "CREATE INDEX IF NOT EXISTS idx_sv_store ON store_visits(store_id, household_id, visit_date)",
    "CREATE INDEX IF NOT EXISTS idx_stores_hh ON stores(household_id)",
    "CREATE INDEX IF NOT EXISTS idx_seq_pending ON store_enrich_queue(status)",
]

def init_db():
    db = get_db()
    try:
        for s in _SCHEMA: db.execute(s)
        db.commit()
        # Migration: add cuisine + auto_populated to stores (idempotent)
        for col, coldef in [
            ("cuisine", "TEXT DEFAULT ''"),
            ("auto_populated", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ]:
            try:
                db.execute(f"ALTER TABLE stores ADD COLUMN {col} {coldef}")
                db.commit()
            except Exception:
                db.rollback()
    finally: close_db(db)
