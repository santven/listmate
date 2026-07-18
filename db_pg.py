#!/usr/bin/env python3
"""PostgreSQL database module for cloud deployment.
Replaces db.py (SQLite) when DATABASE_URL is set.
Uses connection pooling, wraps psycopg2 to mimic sqlite3.Row API.

Drop-in compatible: all app.py queries work unchanged because
  - '?' placeholders are auto-converted to '%s'
  - fetchone()/fetchall() return dict (like sqlite3.Row)
  - total_changes returns cursor rowcount
"""

import os
import re
import psycopg2
from psycopg2 import pool, extras

_pool = None
MIN_CONN = 2
MAX_CONN = 10


def _get_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set — required for PostgreSQL mode")
    return url


def get_pool():
    global _pool
    if _pool is None:
        url = _get_url()
        _pool = pool.ThreadedConnectionPool(MIN_CONN, MAX_CONN, url)
    return _pool


class PgConnection:
    """Wrapper that mimics sqlite3.Connection's API (execute/fetchall/fetchone/close/commit/total_changes)
    so app.py doesn't need any query changes."""

    def __init__(self, conn):
        self._conn = conn
        self._conn.cursor_factory = extras.RealDictCursor
        self._cur = None
        self._last_rowcount = 0

    def cursor(self):
        if self._cur is None:
            self._cur = self._conn.cursor()
        return self._cur

    def execute(self, sql, params=None):
        sql = re.sub(r'\?', '%s', sql)
        c = self.cursor()
        if params:
            c.execute(sql, params)
        else:
            c.execute(sql)
        self._last_rowcount = c.rowcount
        return self

    def fetchall(self):
        rows = self.cursor().fetchall()
        return [dict(r) for r in rows] if rows else []

    def fetchone(self):
        row = self.cursor().fetchone()
        return dict(row) if row else None

    def close(self):
        if self._cur:
            try:
                self._cur.close()
            except Exception:
                pass
            self._cur = None
        try:
            self._conn.commit()
        except Exception:
            pass
        try:
            self._conn.close()
        except Exception:
            pass
        try:
            _pool.putconn(self._conn)
        except Exception:
            pass

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    @property
    def total_changes(self):
        return self._last_rowcount


def get_db():
    """Return a PgConnection (drop-in for SQLite get_db)."""
    p = get_pool()
    conn = p.getconn()
    conn.autocommit = False
    conn.cursor_factory = extras.RealDictCursor
    return PgConnection(conn)


def close_db(conn):
    """Return a connection to pool. PgConnection.close() already handles this."""
    if conn:
        conn.close()


# ── Schema ─────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stores (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    household_id INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS store_items (
    id SERIAL PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id),
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    household_id INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS list_items (
    id SERIAL PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id),
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    added_by TEXT NOT NULL DEFAULT '',
    added_at TIMESTAMP NOT NULL DEFAULT NOW(),
    purchased BOOLEAN NOT NULL DEFAULT FALSE,
    purchased_by TEXT,
    purchased_at TIMESTAMP,
    household_id INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS store_visits (
    id SERIAL PRIMARY KEY,
    store_id INTEGER NOT NULL REFERENCES stores(id),
    household_id INTEGER NOT NULL DEFAULT 1,
    visit_date DATE NOT NULL,
    items_count INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_si_store ON store_items(store_id, household_id);
CREATE INDEX IF NOT EXISTS idx_si_name ON store_items(LOWER(name));
CREATE INDEX IF NOT EXISTS idx_li_store ON list_items(store_id, household_id, purchased);
CREATE INDEX IF NOT EXISTS idx_li_name ON list_items(LOWER(name));
CREATE INDEX IF NOT EXISTS idx_li_user ON list_items(household_id);
CREATE INDEX IF NOT EXISTS idx_sv_store ON store_visits(store_id, household_id, visit_date);
CREATE INDEX IF NOT EXISTS idx_stores_hh ON stores(household_id);
"""


def init_db():
    """Create schema if it doesn't exist."""
    conn = get_db()
    try:
        conn.execute(SCHEMA_SQL)
        conn.commit()
    finally:
        close_db(conn)
