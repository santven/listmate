#!/usr/bin/env python3
"""Listmate auth — Google SSO + household management.
PostgreSQL on Render, SQLite locally. Lazy schema init, crash-safe."""
import os, sqlite3, json, re, traceback
from functools import wraps
from flask import request, jsonify, session, send_from_directory
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

GOOGLE_CLIENT_ID = os.environ.get("SSO_GOOGLE_CLIENT_ID",
    "526061928190-8si99s2n17u7onf8mo2uapfjphtopnc1.apps.googleusercontent.com")
COOKIE_NAME = "listmate_session"
COOKIE_SECURE = False
USE_PG = bool(os.environ.get("DATABASE_URL"))
_schema_done = False

# ── DB: unified interface ───────────────────────────────────
if USE_PG:
    import psycopg2
    from psycopg2 import extras as _extras

    def _connect():
        return psycopg2.connect(os.environ["DATABASE_URL"])

    def _query(sql, params=None):
        sql = re.sub(r'\?', '%s', sql)
        conn = _connect()
        try:
            cur = conn.cursor(cursor_factory=_extras.RealDictCursor)
            if params: cur.execute(sql, params)
            else: cur.execute(sql)
            conn.commit()
            return cur
        except Exception:
            conn.rollback()
            raise

    def _run(sql, params=None):
        cur = _query(sql, params)
        rows = cur.fetchall()
        cur.close()
        cur.connection.close()
        return [dict(r) for r in rows] if rows else []

    def _one(sql, params=None):
        cur = _query(sql, params)
        row = cur.fetchone()
        cur.close()
        cur.connection.close()
        return dict(row) if row else None

    def _insert(sql, params=None):
        cur = _query(sql, params)
        cur.execute("SELECT LASTVAL()")
        lid = cur.fetchone()['lastval']
        cur.close()
        cur.connection.close()
        return lid

    _USERS = "auth_users"
    _HH = "auth_households"
    _FLAGS = "auth_feature_flags"

    def _init_schema():
        global _schema_done
        if _schema_done: return
        for stmt in [
            """CREATE TABLE IF NOT EXISTS auth_users (
                id SERIAL PRIMARY KEY, google_id TEXT UNIQUE NOT NULL,
                email TEXT NOT NULL, name TEXT NOT NULL,
                household_id INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS auth_households (
                id SERIAL PRIMARY KEY, name TEXT NOT NULL,
                invite_code TEXT UNIQUE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS auth_feature_flags (
                user_id INTEGER NOT NULL REFERENCES auth_users(id),
                feature TEXT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT FALSE,
                PRIMARY KEY (user_id, feature))""",
            """CREATE INDEX IF NOT EXISTS idx_au_email ON auth_users(email)""",
            """CREATE INDEX IF NOT EXISTS idx_au_hh ON auth_users(household_id)""",
        ]:
            _run(stmt)
        _schema_done = True

else:
    AUTH_DB_PATH = os.environ.get("AUTH_DB", "listmate_auth.db")

    def _connect():
        db = sqlite3.connect(AUTH_DB_PATH)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _run(sql, params=None):
        db = _connect()
        db.row_factory = sqlite3.Row
        if params: res = db.execute(sql, params)
        else: res = db.execute(sql)
        rows = [dict(r) for r in res.fetchall()]
        db.commit(); db.close()
        return rows

    def _one(sql, params=None):
        db = _connect()
        db.row_factory = sqlite3.Row
        if params: res = db.execute(sql, params)
        else: res = db.execute(sql)
        row = res.fetchone(); db.commit(); db.close()
        return dict(row) if row else None

    def _insert(sql, params=None):
        db = _connect()
        db.row_factory = sqlite3.Row
        if params: db.execute(sql, params)
        else: db.execute(sql)
        lid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit(); db.close()
        return lid

    _USERS = "auth_users"
    _HH = "auth_households"
    _FLAGS = "auth_feature_flags"

    def _init_schema():
        global _schema_done
        if _schema_done: return
        for stmt in [
            """CREATE TABLE IF NOT EXISTS auth_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, google_id TEXT UNIQUE NOT NULL,
                email TEXT NOT NULL, name TEXT NOT NULL,
                household_id INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS auth_households (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                invite_code TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS auth_feature_flags (
                user_id INTEGER NOT NULL, feature TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, feature))""",
            """CREATE INDEX IF NOT EXISTS idx_au_email ON auth_users(email)""",
            """CREATE INDEX IF NOT EXISTS idx_au_hh ON auth_users(household_id)""",
        ]:
            _run(stmt)
        _schema_done = True

# ── Session ─────────────────────────────────────────────────

def install(app, cookie_name="listmate_session", cookie_secure=False):
    global COOKIE_NAME, COOKIE_SECURE
    COOKIE_NAME = cookie_name; COOKIE_SECURE = cookie_secure
    app.secret_key = os.environ.get("FLASK_SECRET_KEY",
        os.environ.get("SECRET_KEY", "dev-secret-change-me"))
    import datetime
    app.config["PERMANENT_SESSION_LIFETIME"] = datetime.timedelta(days=30)

def _set(uid, email, name, hhid, hhname):
    session[COOKIE_NAME] = {"user_id": uid, "email": email, "name": name,
                             "household_id": hhid, "household_name": hhname}
    session.permanent = True

def _clear(): session.pop(COOKIE_NAME, None)
def _get(): return session.get(COOKIE_NAME, {})
def is_logged_in(): return bool(_get())
def get_user_id(): return _get().get("user_id")
def get_display_name(): return _get().get("name", "")
def get_email(): return _get().get("email", "")
def get_household_id(): return _get().get("household_id", 0)
def get_household_name(): return _get().get("household_name", "")

def require_user(fn):
    @wraps(fn)
    def w(*a, **kw):
        if not is_logged_in(): return jsonify({"error": "Login required"}), 401
        return fn(*a, **kw)
    return w

# ── Routes ──────────────────────────────────────────────────

def register_auth_routes(app):
    @app.route("/api/auth/google", methods=["POST"])
    def auth_google():
        try:
            data = request.get_json(silent=True) or {}
            c = data.get("credential")
            if not c: return jsonify({"error": "Missing credential"}), 400
            
            info = id_token.verify_oauth2_token(c, google_requests.Request(), GOOGLE_CLIENT_ID)
            gid = info["sub"]
            email = info.get("email", "")
            name = info.get("name") or email.split("@")[0] if email else "User"
            
            _init_schema()
            user = _one(f"SELECT * FROM {_USERS} WHERE google_id = ?", (gid,))
            
            if not user:
                _insert(f"INSERT INTO {_USERS} (google_id, email, name, household_id) VALUES (?,?,?,0)",
                        (gid, email, name))
                user = _one(f"SELECT * FROM {_USERS} WHERE google_id = ?", (gid,))
                _set(user["id"], email, name, 0, "")
                return jsonify({"ok": True, "new_user": True, "needs_signup": True})
            
            hh_name = ""
            if user["household_id"]:
                hh = _one(f"SELECT name FROM {_HH} WHERE id = ?", (user["household_id"],))
                hh_name = hh["name"] if hh else ""
            
            _set(user["id"], email, name, user["household_id"], hh_name)
            return jsonify({"ok": True, "name": name, "email": email,
                            "household_id": user["household_id"], "household_name": hh_name})
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.route("/api/auth/login", methods=["POST"])
    def auth_login(): return auth_google()

    @app.route("/api/auth/config")
    def auth_config():
        resp = {"client_id": GOOGLE_CLIENT_ID}
        if is_logged_in():
            resp["display_name"] = get_display_name()
            resp["user"] = get_display_name().split(" ")[0].lower()
            resp["user_info"] = {"id": get_user_id(), "name": get_display_name(),
                "email": get_email(), "household_id": get_household_id(),
                "household_name": get_household_name()}
            uid = get_user_id()
            if uid:
                _init_schema()
                flags = _run(f"SELECT feature, enabled FROM {_FLAGS} WHERE user_id = ?", (uid,))
                resp["feature_flags"] = {f["feature"]: bool(f["enabled"]) for f in flags}
        return jsonify(resp)

    @app.route("/api/auth/logout", methods=["POST"])
    def auth_logout(): _clear(); return jsonify({"ok": True})

    @app.route("/api/auth/me")
    def auth_me():
        if not is_logged_in(): return jsonify({"logged_in": False})
        return jsonify({"logged_in": True, "user_id": get_user_id(), "name": get_display_name(),
                        "email": get_email(), "household_id": get_household_id(),
                        "household_name": get_household_name()})

    @app.route("/api/auth/signup", methods=["POST"])
    @require_user
    def auth_signup():
        data = request.get_json(silent=True) or {}
        hname = (data.get("household_name") or "").strip()
        invite = (data.get("invite_code") or "").strip()
        uid = get_user_id()

        _init_schema()
        user = _one(f"SELECT * FROM {_USERS} WHERE id = ?", (uid,))
        if not user: return jsonify({"error": "User not found"}), 404
        if user["household_id"] != 0: return jsonify({"error": "Already in household"}), 400

        if invite:
            hh = _one(f"SELECT * FROM {_HH} WHERE invite_code = ?", (invite,))
            if not hh: return jsonify({"error": "Invalid invite code"}), 404
            _run(f"UPDATE {_USERS} SET household_id = ? WHERE id = ?", (hh["id"], uid))
            _set(uid, user["email"], user["name"], hh["id"], hh["name"])
            return jsonify({"ok": True, "household_id": hh["id"], "household_name": hh["name"]})

        if not hname: return jsonify({"error": "household_name required"}), 400
        
        import secrets
        code = secrets.token_hex(4).upper()
        hhid = _insert(f"INSERT INTO {_HH} (name, invite_code) VALUES (?,?)", (hname, code))
        _run(f"UPDATE {_USERS} SET household_id = ? WHERE id = ?", (hhid, uid))
        _set(uid, user["email"], user["name"], hhid, hname)
        return jsonify({"ok": True, "household_id": hhid, "household_name": hname, "invite_code": code})

    @app.route("/api/auth/household")
    @require_user
    def auth_household():
        hhid = get_household_id(); uid = get_user_id()
        if not hhid: return jsonify({"error": "No household"}), 404
        
        _init_schema()
        hh = _one(f"SELECT * FROM {_HH} WHERE id = ?", (hhid,))
        members = _run(f"SELECT id, name, email FROM {_USERS} WHERE household_id = ?", (hhid,))
        return jsonify({"ok": True,
            "household": {"id": hh["id"], "name": hh["name"], "invite_code": hh["invite_code"]},
            "members": [{"user_id": m["id"], "email": m["email"], "display_name": m["name"],
                          "role": "owner" if m["id"] == uid else "member"} for m in members],
            "current_user_id": uid, "is_owner": True})

    @app.route("/api/auth/household/members", methods=["POST"])
    @require_user
    def auth_add_member():
        hhid = get_household_id()
        if not hhid: return jsonify({"error": "No household"}), 400

        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        if not email: return jsonify({"error": "Email required"}), 400

        _init_schema()
        user = _one(f"SELECT * FROM {_USERS} WHERE email = ?", (email,))
        if not user:
            _run(f"INSERT INTO {_USERS} (google_id, email, name, household_id) VALUES (?,?,?,?)",
                 (f"pending:{email}", email, email.split("@")[0], hhid))
        elif user["household_id"] != hhid:
            _run(f"UPDATE {_USERS} SET household_id = ? WHERE id = ?", (hhid, user["id"]))
        return jsonify({"ok": True})
