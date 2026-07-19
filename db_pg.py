#!/usr/bin/env python3
"""PostgreSQL database module for cloud deployment.
Uses ThreadedConnectionPool, wraps psycopg2 to mimic sqlite3.Row API."""
import os, re, psycopg2
from psycopg2 import pool, extras

_pgpool = None

def _get_pool():
    global _pgpool
    if _pgpool is None:
        url = os.environ.get("DATABASE_URL")
        if not url: raise RuntimeError("DATABASE_URL not set")
        _pgpool = pool.ThreadedConnectionPool(2, 10, url)
    return _pgpool


class PgConnection:
    def __init__(self, conn):
        self._conn = conn
        self._cur = None
        self._last_rowcount = 0

    def execute(self, sql, params=None):
        sql = re.sub(r'\?', '%s', sql)
        self._cur = self._conn.cursor()
        if params:
            self._cur.execute(sql, params)
        else:
            self._cur.execute(sql)
        self._last_rowcount = self._cur.rowcount
        return self

    def fetchall(self):
        if self._cur is None: return []
        rows = self._cur.fetchall()
        cols = [d[0] for d in self._cur.description] if self._cur.description else []
        return [dict(zip(cols, r)) for r in rows] if rows else []

    def fetchone(self):
        if self._cur is None: return None
        row = self._cur.fetchone()
        if not row: return None
        cols = [d[0] for d in self._cur.description] if self._cur.description else []
        return dict(zip(cols, row))

    def close(self):
        if self._cur:
            try: self._cur.close()
            except: pass
            self._cur = None
        try:
            _pgpool.putconn(self._conn, close=False)
        except:
            try: self._conn.close()
            except: pass

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    @property
    def total_changes(self):
        return self._last_rowcount


def get_db():
    p = _get_pool()
    conn = p.getconn()
    return PgConnection(conn)


def close_db(conn):
    if conn: conn.close()


# ── Schema (run as individual statements) ──

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS stores (
        id SERIAL PRIMARY KEY, name TEXT NOT NULL,
        household_id INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP NOT NULL DEFAULT NOW())""",
    """CREATE TABLE IF NOT EXISTS store_items (
        id SERIAL PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
        name TEXT NOT NULL, category TEXT NOT NULL DEFAULT '',
        household_id INTEGER NOT NULL DEFAULT 1)""",
    """CREATE TABLE IF NOT EXISTS list_items (
        id SERIAL PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
        name TEXT NOT NULL, category TEXT NOT NULL DEFAULT '',
        added_by TEXT NOT NULL DEFAULT '',
        added_at TIMESTAMP NOT NULL DEFAULT NOW(),
        purchased BOOLEAN NOT NULL DEFAULT FALSE,
        purchased_by TEXT, purchased_at TIMESTAMP,
        household_id INTEGER NOT NULL DEFAULT 1)""",
    """CREATE TABLE IF NOT EXISTS store_visits (
        id SERIAL PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
        household_id INTEGER NOT NULL DEFAULT 1,
        visit_date DATE NOT NULL, items_count INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP NOT NULL DEFAULT NOW())""",
]

_INDEXES = [
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
        for stmt in _SCHEMA + _INDEXES:
            db.execute(stmt)
        db.commit()
    finally:
        close_db(db)
