#!/usr/bin/env python3
"""Listmate auth — Google SSO + household management.
PostgreSQL on Render, SQLite locally. Lazy schema init, crash-safe."""
import os, sqlite3, json, re, traceback
from functools import wraps
from flask import request, jsonify, session, send_from_directory
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from google.auth.exceptions import GoogleAuthError

GOOGLE_CLIENT_ID = os.environ.get("SSO_GOOGLE_CLIENT_ID", "").strip() or \
    "526061928190-8si99s2n17u7onf8mo2uapfjphtopnc1.apps.googleusercontent.com"
COOKIE_NAME = "listmate_session"
COOKIE_SECURE = False
USE_PG = bool(os.environ.get("DATABASE_URL"))
_schema_done = False

# ── DB: unified interface ───────────────────────────────────
if USE_PG:
    import psycopg2
    from psycopg2 import extras as _extras
    from psycopg2 import pool as _pgpool

    _pool = None

    def _connect():
        global _pool
        if _pool is None:
            _pool = _pgpool.ThreadedConnectionPool(1, 4, os.environ["DATABASE_URL"])
        conn = _pool.getconn()
        conn.autocommit = True
        return conn

    def _put_conn(conn):
        global _pool
        if _pool and conn:
            try:
                _pool.putconn(conn)
            except Exception:
                try: conn.close()
                except: pass

    def _pool_close():
        global _pool
        if _pool:
            _pool.closeall()
            _pool = None

    def _one(sql, params=None):
        sql_fixed = re.sub(r'\?', '%s', sql)
        conn = _connect()
        try:
            cur = conn.cursor()
            if params: cur.execute(sql_fixed, params)
            else: cur.execute(sql_fixed)
            row = cur.fetchone()
            cols = [d[0] for d in cur.description] if cur.description else []
            cur.close()
            _put_conn(conn)
            return dict(zip(cols, row)) if row else None
        except Exception:
            conn.rollback()
            _put_conn(conn)
            return None

    def _run(sql, params=None):
        sql_fixed = re.sub(r'\?', '%s', sql)
        conn = _connect()
        cur = conn.cursor()
        if params: cur.execute(sql_fixed, params)
        else: cur.execute(sql_fixed)
        rows = cur.fetchall() if cur.description else []
        cols = [d[0] for d in cur.description] if cur.description else []
        cur.close()
        _put_conn(conn)
        return [dict(zip(cols, r)) for r in rows]

    def _exec(sql, params=None):
        '''Execute INSERT/UPDATE/DELETE — raises on error.'''
        sql_fixed = re.sub(r'\?', '%s', sql)
        conn = _connect()
        cur = conn.cursor()
        if params: cur.execute(sql_fixed, params)
        else: cur.execute(sql_fixed)
        cur.close()
        _put_conn(conn)

    def _insert(sql, params=None):
        """Insert a row and return the new ID (Postgres RETURNING)."""
        sql_fixed = re.sub(r'\?', '%s', sql)
        conn = _connect()
        cur = conn.cursor()
        if params: cur.execute(sql_fixed, params)
        else: cur.execute(sql_fixed)
        # Try getting RETURNING id first
        row = cur.fetchone() if cur.description else None
        if row:
            new_id = row[0]
        else:
            # No RETURNING — get lastval
            cur.execute("SELECT lastval()")
            new_id = cur.fetchone()[0]
        cur.close()
        _put_conn(conn)
        return new_id

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
            """CREATE TABLE IF NOT EXISTS invites (
                id SERIAL PRIMARY KEY, token TEXT UNIQUE NOT NULL,
                household_id INTEGER NOT NULL REFERENCES auth_households(id),
                email TEXT, created_by INTEGER NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                expires_at TIMESTAMP, used_by INTEGER, used_at TIMESTAMP)""",
            """CREATE INDEX IF NOT EXISTS idx_invites_token ON invites(token)""",
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
            """CREATE TABLE IF NOT EXISTS invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT UNIQUE NOT NULL,
                household_id INTEGER NOT NULL, email TEXT, created_by INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP, used_by INTEGER, used_at TIMESTAMP,
                FOREIGN KEY (household_id) REFERENCES auth_households(id))""",
            """CREATE INDEX IF NOT EXISTS idx_invites_token ON invites(token)""",
        ]:
            _run(stmt)
        _schema_done = True

# ── Session ─────────────────────────────────────────────────

def _seed_stores(household_id):
    """Create default stores for a new household (idempotent)."""
    stores = _run(f"SELECT id FROM stores WHERE household_id = ?", (household_id,))
    if stores: return  # Already seeded
    defaults = ["Costco","Whole Foods","Valli","Patel / IndiaCo","Jewel","Amazon"]
    for name in defaults:
        _run(f"INSERT INTO stores (household_id, name) VALUES (?,?)", (household_id, name))

def install(app, cookie_name="listmate_session", cookie_secure=False):
    global COOKIE_NAME
    COOKIE_NAME = cookie_name
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    from datetime import timedelta
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = cookie_secure

def _set(uid, email, name, hhid, hhname):
    session[COOKIE_NAME] = {"user_id": uid, "email": email, "name": name,
                             "household_id": hhid, "household_name": hhname}
    session.permanent = True
    session.modified = True

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
            name = info.get("name") or (email.split("@")[0] if email else "User")
            
            _init_schema()
            
            # Find user — match by email first (case-insensitive on all DBs)
            user = _one(f"SELECT id, google_id, email, name, household_id FROM {_USERS} WHERE LOWER(email) = LOWER(?)", (email,))
            if not user:
                user = _one(f"SELECT id, google_id, email, name, household_id FROM {_USERS} WHERE google_id = ?", (gid,))
            
            if not user:
                _run(f"INSERT INTO {_USERS} (google_id, email, name, household_id) VALUES (?,?,?,0)",
                     (gid, email, name))
                user = _one(f"SELECT id, email, name, household_id, google_id FROM {_USERS} WHERE google_id = ?", (gid,))
            
            # Update Google ID if different
            if user and user.get("google_id") != gid:
                _run(f"UPDATE {_USERS} SET google_id = ? WHERE id = ?", (gid, user["id"]))
            
            hh_id = user.get("household_id", 0) if user else 0
            
            # Auto-assign: only auto-create a household if NO households exist at all (first user ever)
            # Otherwise leave them unassigned — they need to sign up or accept an invite
            if not hh_id:
                hh_count = _one(f"SELECT COUNT(*) as cnt FROM {_HH}", None)
                if hh_count and hh_count.get("cnt", 0) == 0:
                    # First user on a fresh system — create household
                    import secrets
                    code = secrets.token_hex(4).upper()
                    _exec(f"INSERT INTO {_HH} (name, invite_code) VALUES (?,?)", ("Root Household", code))
                    hh = _one(f"SELECT id, name FROM {_HH} ORDER BY id DESC LIMIT 1", None)
                    hh_id = hh["id"] if hh else 1
                    hh_name = hh["name"] if hh else "Root Household"
                    _run(f"UPDATE {_USERS} SET household_id = ? WHERE id = ?", (hh_id, user["id"]))
                else:
                    # Households exist but this user isn't in one — they must sign up
                    # Register the user first so they have an account, then redirect to signup
                    _set(user["id"], email, name, 0, "")
                    return jsonify({"ok": False, "needs_signup": True,
                                    "message": "No household — please complete signup"}), 200
            if hh_id and not hh_name:
                hh = _one(f"SELECT name FROM {_HH} WHERE id = ?", (hh_id,))
                hh_name = hh.get("name", "") if hh else ""
            
            _set(user["id"], email, name, hh_id, hh_name)
            return jsonify({"ok": True, "name": name, "email": email,
                            "household_id": hh_id, "household_name": hh_name})
        except Exception as e:
            # GoogleAuthError (MalformedError, etc) → 401; anything else → 500
            if isinstance(e, GoogleAuthError):
                return jsonify({"error": f"Invalid token: {str(e)}"}), 401
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
        invites = _run("SELECT token, email, created_at FROM invites WHERE household_id = ? AND used_by IS NULL ORDER BY created_at DESC", (hhid,))
        return jsonify({"ok": True,
            "household": {"id": hh["id"], "name": hh["name"], "invite_code": hh.get("invite_code","")},
            "members": [{"user_id": m["id"], "email": m["email"], "display_name": m["name"],
                          "role": "owner" if m["id"] == uid else "member"} for m in members],
            "pending_invites": [{"email": i["email"], "token": i["token"], "created_at": str(i.get("created_at",""))} for i in invites],
            "current_user_id": uid, "is_owner": True})

    @app.route("/api/auth/household/invites/<token>", methods=["DELETE"])
    @require_user
    def auth_remove_invite(token):
        hhid = get_household_id()
        if not hhid: return jsonify({"error": "No household"}), 400
        _init_schema()
        _run("DELETE FROM invites WHERE token = ? AND household_id = ?", (token, hhid))
        return jsonify({"ok": True})

    @app.route("/api/auth/household/members", methods=["DELETE"])
    @require_user
    def auth_remove_member():
        """Remove a member from the household (owner only)."""
        hhid = get_household_id()
        if not hhid: return jsonify({"error": "No household"}), 400
        data = request.get_json(silent=True) or {}
        member_id = data.get("user_id")
        if not member_id: return jsonify({"error": "user_id required"}), 400
        _init_schema()
        # Only allow removing from own household; can't remove self
        me = get_user_id()
        if member_id == me: return jsonify({"error": "Cannot remove yourself"}), 400
        member = _one(f"SELECT * FROM {_USERS} WHERE id = ? AND household_id = ?", (member_id, hhid))
        if not member: return jsonify({"error": "Member not found in your household"}), 404
        _run(f"UPDATE {_USERS} SET household_id = NULL WHERE id = ?", (member_id,))
        return jsonify({"ok": True, "removed": member["email"]})

    @app.route("/api/auth/household/members", methods=["POST"])
    @require_user
    def auth_add_member():
        hhid = get_household_id()
        if not hhid: return jsonify({"error": "No household"}), 400

        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        if not email: return jsonify({"error": "Email required"}), 400

        _init_schema()

        # Check if already a member
        existing = _one(f"SELECT * FROM {_USERS} WHERE LOWER(email) = LOWER(?) AND household_id = ?",
                       (email, hhid))
        if existing:
            return jsonify({"ok": True, "already_member": True})

        import secrets
        token = secrets.token_urlsafe(32)
        import datetime as _dt
        expires = _dt.datetime.utcnow() + _dt.timedelta(days=7)
        expires_str = expires.strftime('%Y-%m-%d %H:%M:%S')
        _exec(f"""INSERT INTO invites (token, household_id, email, created_by, expires_at)
               VALUES (?, ?, ?, ?, ?)""",
             (token, hhid, email, get_user_id(), expires_str))

        # Get names for email
        hh_name = get_household_name()
        inviter = get_display_name()

        invite_link = f"https://grocerlist.app/login?token={token}"

        # Send email via SendGrid
        try:
            from email_helper import send_invite
            send_invite(email, invite_link, household_name=hh_name, inviter_name=inviter)
        except Exception as e:
            import traceback
            print(f"[send_invite ERROR] {e}", flush=True)
            traceback.print_exc()

        return jsonify({"ok": True, "invite_link": invite_link, "email": email})

    @app.route("/api/auth/invite/<token>")
    def auth_check_invite(token):
        _init_schema()
        invite = _one(
            """SELECT i.id, h.name as household_name, i.email, i.expires_at, i.used_by
               FROM invites i JOIN auth_households h ON h.id = i.household_id
               WHERE i.token = ?""",
            (token,))
        if not invite:
            return jsonify({"valid": False, "error": "Invalid invite link"}), 404
        if invite.get("used_by"):
            return jsonify({"valid": False, "error": "Invite already used"}), 410
        return jsonify({"valid": True, "household_name": invite["household_name"],
                        "email": invite.get("email")})

    @app.route("/api/auth/invite/<token>/accept", methods=["POST"])
    @require_user
    def auth_accept_invite(token):
        _init_schema()
        invite = _one("SELECT * FROM invites WHERE token = ? AND used_by IS NULL", (token,))
        if not invite:
            return jsonify({"error": "Invalid or expired invite"}), 404

        uid = get_user_id()
        user = _one(f"SELECT * FROM {_USERS} WHERE id = ?", (uid,))

        if invite.get("email") and user.get("email","").lower() != invite["email"].lower():
            return jsonify({"error": "This invite is for a different email address"}), 403

        _run(f"UPDATE {_USERS} SET household_id = ? WHERE id = ?", (invite["household_id"], uid))
        import datetime as _dt2
        _exec("UPDATE invites SET used_by = ?, used_at = ? WHERE id = ?", (uid, _dt2.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'), invite["id"]))

        hh = _one(f"SELECT name FROM {_HH} WHERE id = ?", (invite["household_id"],))
        hh_name = hh.get("name","") if hh else ""
        _set(uid, user["email"], user["name"], invite["household_id"], hh_name)
        return jsonify({"ok": True, "household_id": invite["household_id"], "household_name": hh_name})
