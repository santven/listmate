#!/usr/bin/env python3
"""Listmate auth module — Google SSO + household management.
Self-contained. Uses PostgreSQL when DATABASE_URL is set, SQLite otherwise."""

import os, sqlite3, json
from urllib.parse import urlencode
from functools import wraps

from flask import request, jsonify, session, redirect, current_app, send_from_directory
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

# ── Config ──────────────────────────────────────────────────
GOOGLE_CLIENT_ID = os.environ.get("SSO_GOOGLE_CLIENT_ID",
    "526061928190-8si99s2n17u7onf8mo2uapfjphtopnc1.apps.googleusercontent.com")
COOKIE_NAME = "listmate_session"
COOKIE_SECURE = False

USE_PG = bool(os.environ.get("DATABASE_URL"))

# ── PostgreSQL adapter ──────────────────────────────────────
if USE_PG:
    import re as _re
    import psycopg2
    from psycopg2 import pool as _pgpool, extras as _extras

    _pg_pool = None

    class _PgDb:
        def __init__(self, conn):
            self._c = conn; self._c.cursor_factory = _extras.RealDictCursor
            self._cur = None; self._rc = 0
        def cursor(self):
            if not self._cur: self._cur = self._c.cursor()
            return self._cur
        def execute(self, sql, params=None):
            sql = _re.sub(r'\?', '%s', sql)
            c = self.cursor()
            if params: c.execute(sql, params)
            else: c.execute(sql)
            self._rc = c.rowcount
            return self
        def executemany(self, sql, seq):
            sql = _re.sub(r'\?', '%s', sql)
            self.cursor().executemany(sql, seq)
            self._rc = self.cursor().rowcount
            return self
        def fetchall(self):
            rows = self.cursor().fetchall()
            return [dict(r) for r in rows] if rows else []
        def fetchone(self):
            row = self.cursor().fetchone()
            return dict(row) if row else None
        def commit(self): self._c.commit()
        def close(self):
            try: self._cur.close()
            except: pass
            try: self._c.commit()
            except: pass
            try: _pg_pool.putconn(self._c)
            except: pass
        def __del__(self):
            try: self._cur.close()
            except: pass
            try: _pg_pool.putconn(self._c)
            except: pass

    def _get_auth_db():
        global _pg_pool
        url = os.environ["DATABASE_URL"]
        if not _pg_pool:
            _pg_pool = _pgpool.ThreadedConnectionPool(2, 10, url)
        return _PgDb(_pg_pool.getconn())

    def _init_auth_db():
        return  # Schema created via SCHEMA below

    # Auth tables in Postgres schema
    def _ensure_auth_schema():
        db = _get_auth_db()
        for stmt in [
            """CREATE TABLE IF NOT EXISTS auth_users (
                id SERIAL PRIMARY KEY,
                google_id TEXT UNIQUE NOT NULL,
                email TEXT NOT NULL,
                name TEXT NOT NULL,
                household_id INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )""",
            """CREATE TABLE IF NOT EXISTS auth_households (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                invite_code TEXT UNIQUE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )""",
            """CREATE TABLE IF NOT EXISTS auth_feature_flags (
                user_id INTEGER NOT NULL REFERENCES auth_users(id),
                feature TEXT NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT FALSE,
                PRIMARY KEY (user_id, feature)
            )""",
            """CREATE INDEX IF NOT EXISTS idx_auth_users_email ON auth_users(email)""",
            """CREATE INDEX IF NOT EXISTS idx_auth_users_hh ON auth_users(household_id)""",
        ]:
            db.execute(stmt)
        db.commit()
        db.close()

    def _last_id(db, table):
        cur = db.cursor()
        cur.execute(f"SELECT currval(pg_get_serial_sequence('{table}','id'))")
        return cur.fetchone()['currval']

else:
    # ── SQLite adapter (local dev) ───────────────────────────
    AUTH_DB_PATH = os.environ.get("AUTH_DB", "listmate_auth.db")

    class _SqliteDb:
        def __init__(self, db):
            self._c = db
            self._c.row_factory = sqlite3.Row
            self._c.execute("PRAGMA journal_mode=WAL")
            self._c.execute("PRAGMA foreign_keys=ON")
            self._rc = 0
        def execute(self, sql, params=None):
            if params: c = self._c.execute(sql, params)
            else: c = self._c.execute(sql)
            self._rc = c.rowcount
            return self
        def fetchall(self): rows = self._c.fetchall(); return [dict(r) for r in rows] if rows else []
        def fetchone(self): row = self._c.fetchone(); return dict(row) if row else None
        def commit(self): self._c.commit()
        def close(self): self._c.close()

    def _get_auth_db():
        db = sqlite3.connect(AUTH_DB_PATH)
        return _SqliteDb(db)

    def _init_auth_db():
        db = _get_auth_db()
        for stmt in [
            """CREATE TABLE IF NOT EXISTS auth_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                google_id TEXT UNIQUE NOT NULL,
                email TEXT NOT NULL,
                name TEXT NOT NULL,
                household_id INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS auth_households (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                invite_code TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS auth_feature_flags (
                user_id INTEGER NOT NULL, feature TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, feature),
                FOREIGN KEY (user_id) REFERENCES auth_users(id)
            )""",
            """CREATE INDEX IF NOT EXISTS idx_auth_users_email ON auth_users(email)""",
            """CREATE INDEX IF NOT EXISTS idx_auth_users_hh ON auth_users(household_id)""",
        ]:
            db.execute(stmt)
        db.commit()
        db.close()

    def _last_id(db, table):
        db.execute("SELECT last_insert_rowid()")
        return db.fetchone()['last_insert_rowid()']

# Initialize schema
_init_auth_db()
if USE_PG:
    _ensure_auth_schema()

# Table name mapping (unified)
_USERS = "auth_users"
_HOUSEHOLDS = "auth_households"
_FLAGS = "auth_feature_flags"

# ── Session helpers ─────────────────────────────────────────

def install(app, cookie_name="listmate_session", cookie_secure=False):
    global COOKIE_NAME, COOKIE_SECURE
    COOKIE_NAME = cookie_name
    COOKIE_SECURE = cookie_secure
    app.secret_key = os.environ.get("FLASK_SECRET_KEY",
        os.environ.get("SECRET_KEY", "dev-secret-change-in-production"))
    import datetime
    app.config["PERMANENT_SESSION_LIFETIME"] = datetime.timedelta(days=30)


def _set_session(user_id, email, name, household_id, household_name):
    session[COOKIE_NAME] = {
        "user_id": user_id, "email": email, "name": name,
        "household_id": household_id, "household_name": household_name,
    }
    session.permanent = True


def _clear_session():
    session.pop(COOKIE_NAME, None)


def _get_session():
    return session.get(COOKIE_NAME, {})


def is_logged_in():
    return bool(_get_session())


def get_user_id():
    return _get_session().get("user_id")

def get_display_name():
    return _get_session().get("name", "")

def get_email():
    return _get_session().get("email", "")

def get_household_id():
    return _get_session().get("household_id", 0)

def get_household_name():
    return _get_session().get("household_name", "")


# ── Decorators ──────────────────────────────────────────────

def require_user(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            return jsonify({"error": "Login required", "redirect": "/login"}), 401
        return fn(*args, **kwargs)
    return wrapper


def feature_enabled(feature_name):
    uid = get_user_id()
    if not uid: return False
    db = _get_auth_db()
    row = db.execute(f"SELECT enabled FROM {_FLAGS} WHERE user_id = ? AND feature = ?", (uid, feature_name)).fetchone()
    db.close()
    return bool(row and row["enabled"])


def require_feature(feature_name):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not is_logged_in(): return jsonify({"error": "Login required"}), 401
            if not feature_enabled(feature_name):
                return jsonify({"error": f"Feature '{feature_name}' not enabled"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ── Auth Routes ─────────────────────────────────────────────

def register_auth_routes(app):
    @app.route("/api/auth/google", methods=["POST"])
    def auth_google():
        data = request.get_json(silent=True) or {}
        credential = data.get("credential")
        if not credential:
            return jsonify({"error": "Missing credential"}), 400

        try:
            info = id_token.verify_oauth2_token(credential, google_requests.Request(), GOOGLE_CLIENT_ID)
        except Exception as e:
            return jsonify({"error": f"Invalid token: {str(e)}"}), 401

        google_id = info["sub"]
        email = info.get("email", "")
        name = info.get("name", email.split("@")[0])

        db = _get_auth_db()
        user = db.execute(f"SELECT * FROM {_USERS} WHERE google_id = ?", (google_id,)).fetchone()

        if not user:
            db.execute(f"INSERT INTO {_USERS} (google_id, email, name, household_id) VALUES (?, ?, ?, 0)",
                       (google_id, email, name))
            db.commit()
            user = db.execute(f"SELECT * FROM {_USERS} WHERE google_id = ?", (google_id,)).fetchone()
            db.close()
            _set_session(user["id"], email, name, 0, "")
            return jsonify({"ok": True, "new_user": True, "needs_signup": True})

        db.close()

        hh_name = ""
        if user["household_id"]:
            hh_db = _get_auth_db()
            hh = hh_db.execute(f"SELECT name FROM {_HOUSEHOLDS} WHERE id = ?", (user["household_id"],)).fetchone()
            hh_name = hh["name"] if hh else ""
            hh_db.close()

        _set_session(user["id"], email, name, user["household_id"], hh_name)
        return jsonify({
            "ok": True, "name": name, "email": email,
            "household_id": user["household_id"], "household_name": hh_name,
        })

    @app.route("/api/auth/login", methods=["POST"])
    def auth_login():
        return auth_google()

    @app.route("/api/auth/config")
    def auth_config():
        resp = {"client_id": GOOGLE_CLIENT_ID}
        if is_logged_in():
            resp["display_name"] = get_display_name()
            resp["user"] = get_display_name().split(" ")[0].lower()
            resp["user_info"] = {
                "id": get_user_id(), "name": get_display_name(),
                "email": get_email(), "household_id": get_household_id(),
                "household_name": get_household_name(),
            }
            uid = get_user_id()
            if uid:
                db = _get_auth_db()
                flags = db.execute(f"SELECT feature, enabled FROM {_FLAGS} WHERE user_id = ?", (uid,)).fetchall()
                resp["feature_flags"] = {f["feature"]: bool(f["enabled"]) for f in flags}
                db.close()
        return jsonify(resp)

    @app.route("/api/auth/logout", methods=["POST"])
    def auth_logout():
        _clear_session()
        return jsonify({"ok": True})

    @app.route("/api/auth/me")
    def auth_me():
        if not is_logged_in():
            return jsonify({"logged_in": False})
        return jsonify({
            "logged_in": True, "user_id": get_user_id(),
            "name": get_display_name(), "email": get_email(),
            "household_id": get_household_id(), "household_name": get_household_name(),
        })

    @app.route("/api/auth/signup", methods=["POST"])
    def auth_signup():
        if not is_logged_in(): return jsonify({"error": "Login required"}), 401
        data = request.get_json(silent=True) or {}
        household_name = (data.get("household_name") or "").strip()
        invite_code = (data.get("invite_code") or "").strip()
        uid = get_user_id()

        db = _get_auth_db()
        user = db.execute(f"SELECT * FROM {_USERS} WHERE id = ?", (uid,)).fetchone()
        if not user: db.close(); return jsonify({"error": "User not found"}), 404
        if user["household_id"] != 0:
            db.close(); return jsonify({"error": "Already in a household"}), 400

        if invite_code:
            hh = db.execute(f"SELECT * FROM {_HOUSEHOLDS} WHERE invite_code = ?", (invite_code,)).fetchone()
            if not hh: db.close(); return jsonify({"error": "Invalid invite code"}), 404
            db.execute(f"UPDATE {_USERS} SET household_id = ? WHERE id = ?", (hh["id"], uid))
            db.commit(); db.close()
            _set_session(uid, user["email"], user["name"], hh["id"], hh["name"])
            return jsonify({"ok": True, "household_id": hh["id"], "household_name": hh["name"]})

        if not household_name: db.close(); return jsonify({"error": "household_name or invite_code required"}), 400

        import secrets
        code = secrets.token_hex(4).upper()
        db.execute(f"INSERT INTO {_HOUSEHOLDS} (name, invite_code) VALUES (?, ?)", (household_name, code))
        hhid = _last_id(db, _HOUSEHOLDS)
        db.execute(f"UPDATE {_USERS} SET household_id = ? WHERE id = ?", (hhid, uid))
        db.commit(); db.close()
        _set_session(uid, user["email"], user["name"], hhid, household_name)
        return jsonify({"ok": True, "household_id": hhid, "household_name": household_name, "invite_code": code})

    @app.route("/api/auth/household")
    def auth_household():
        if not is_logged_in(): return jsonify({"error": "Login required"}), 401
        hhid = get_household_id(); uid = get_user_id()
        if not hhid: return jsonify({"error": "No household"}), 404
        db = _get_auth_db()
        hh = db.execute(f"SELECT * FROM {_HOUSEHOLDS} WHERE id = ?", (hhid,)).fetchone()
        members = db.execute(f"SELECT id, name, email FROM {_USERS} WHERE household_id = ?", (hhid,)).fetchall()
        db.close()
        return jsonify({
            "ok": True,
            "household": {"id": hh["id"], "name": hh["name"], "invite_code": hh["invite_code"]},
            "members": [
                {"user_id": m["id"], "email": m["email"], "display_name": m["name"],
                 "role": "owner" if m["id"] == uid else "member"} for m in members
            ],
            "current_user_id": uid, "is_owner": True,
        })

    @app.route("/api/auth/household/members", methods=["POST"])
    def auth_add_member():
        if not is_logged_in(): return jsonify({"error": "Login required"}), 401
        hhid = get_household_id()
        if not hhid: return jsonify({"error": "No household"}), 400

        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        if not email: return jsonify({"error": "Email required"}), 400

        db = _get_auth_db()
        user = db.execute(f"SELECT * FROM {_USERS} WHERE email = ?", (email,)).fetchone()
        if not user:
            db.execute(f"INSERT INTO {_USERS} (google_id, email, name, household_id) VALUES (?, ?, ?, ?)",
                       (f"pending:{email}", email, email.split("@")[0], hhid))
        else:
            if user["household_id"] == hhid: db.close(); return jsonify({"ok": True, "already_added": True})
            db.execute(f"UPDATE {_USERS} SET household_id = ? WHERE id = ?", (hhid, user["id"]))
        db.commit(); db.close()
        return jsonify({"ok": True})
