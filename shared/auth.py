#!/usr/bin/env python3
"""Listmate auth — Google SSO + household management.
PostgreSQL connection pool and authentication logic."""
import os, json, re, traceback
from functools import wraps
from flask import request, jsonify, session, send_from_directory
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from google.auth.exceptions import GoogleAuthError

GOOGLE_CLIENT_ID = os.environ.get("SSO_GOOGLE_CLIENT_ID", "").strip() or \
    "526061928190-8si99s2n17u7onf8mo2uapfjphtopnc1.apps.googleusercontent.com"
REVENUECAT_PUBLIC_KEY = os.environ.get("REVENUECAT_PUBLIC_KEY", "test_IiwuzQXuzucZlwihcMHIsqAMwby").strip()
REVENUECAT_APPLE_KEY = os.environ.get("REVENUECAT_APPLE_KEY", "").strip()
COOKIE_NAME = "listmate_session"
COOKIE_SECURE = False
_schema_done = False

# ── DB: unified PostgreSQL interface ───────────────────────
import psycopg2
from psycopg2 import extras as _extras
from psycopg2 import pool as _pgpool

_pool = None

def _connect():
    global _pool
    if _pool is None:
        import db_pg
        db_pg._ensure_local_pg()
        db_url = os.environ.get("DATABASE_URL", "postgresql://postgres@localhost:5432/listmate")
        _pool = _pgpool.ThreadedConnectionPool(1, 20, db_url)
    conn = _pool.getconn()
    conn.autocommit = True
    return conn

def _put_conn(conn):
    global _pool
    if _pool and conn:
        try:
            if not getattr(conn, 'closed', False):
                _pool.putconn(conn)
        except Exception:
            try: conn.close()
            except Exception: pass

def _pool_close():
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None

def _one(sql, params=None):
    sql_fixed = re.sub(r'\?', '%s', sql)
    conn = _connect()
    cur = None
    try:
        cur = conn.cursor()
        if params: cur.execute(sql_fixed, params)
        else: cur.execute(sql_fixed)
        row = cur.fetchone()
        cols = [d[0] for d in cur.description] if cur.description else []
        return dict(zip(cols, row)) if row else None
    except Exception:
        return None
    finally:
        if cur:
            try: cur.close()
            except Exception: pass
        _put_conn(conn)

def _run(sql, params=None):
    sql_fixed = re.sub(r'\?', '%s', sql)
    conn = _connect()
    cur = None
    try:
        cur = conn.cursor()
        if params: cur.execute(sql_fixed, params)
        else: cur.execute(sql_fixed)
        rows = cur.fetchall() if cur.description else []
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return []
    finally:
        if cur:
            try: cur.close()
            except Exception: pass
        _put_conn(conn)

def _exec(sql, params=None):
    '''Execute INSERT/UPDATE/DELETE — raises on error.'''
    sql_fixed = re.sub(r'\?', '%s', sql)
    conn = _connect()
    cur = None
    try:
        cur = conn.cursor()
        if params: cur.execute(sql_fixed, params)
        else: cur.execute(sql_fixed)
    finally:
        if cur:
            try: cur.close()
            except Exception: pass
        _put_conn(conn)

def _insert(sql, params=None):
    """Insert a row and return the new ID (Postgres RETURNING)."""
    sql_fixed = re.sub(r'\?', '%s', sql)
    conn = _connect()
    cur = None
    try:
        cur = conn.cursor()
        if params: cur.execute(sql_fixed, params)
        else: cur.execute(sql_fixed)
        row = cur.fetchone() if cur.description else None
        if row:
            new_id = row[0]
        else:
            cur.execute("SELECT lastval()")
            new_id = cur.fetchone()[0]
        return new_id
    finally:
        if cur:
            try: cur.close()
            except Exception: pass
        _put_conn(conn)

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
            id SERIAL PRIMARY KEY, name TEXT NOT NULL, owner_id INTEGER, downgraded_at TIMESTAMP,
            invite_code TEXT UNIQUE,
            dietary_restrictions TEXT DEFAULT '',
            zip_code TEXT DEFAULT '',
            country TEXT DEFAULT '',
            is_premium BOOLEAN NOT NULL DEFAULT FALSE,
            stripe_customer_id TEXT,
            rc_app_user_id TEXT,
            subscription_status TEXT NOT NULL DEFAULT 'free',
            trial_ends_at TIMESTAMP,
            subscription_ends_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS auth_feature_flags (
            user_id INTEGER NOT NULL REFERENCES auth_users(id),
            feature TEXT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT FALSE,
            PRIMARY KEY (user_id, feature))""",
        """CREATE INDEX IF NOT EXISTS idx_au_email ON auth_users(email)""",
        """CREATE INDEX IF NOT EXISTS idx_au_hh ON auth_users(household_id)""",
        
        """CREATE TABLE IF NOT EXISTS login_intents (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT NOW())""",
        
        """CREATE TABLE IF NOT EXISTS invites (
            id SERIAL PRIMARY KEY, token TEXT UNIQUE NOT NULL,
            household_id INTEGER NOT NULL REFERENCES auth_households(id),
            email TEXT, created_by INTEGER NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMP, used_by INTEGER, used_at TIMESTAMP)""",
        """CREATE INDEX IF NOT EXISTS idx_invites_token ON invites(token)""",
    ]:
        _run(stmt)
    for stmt in [
        
        "ALTER TABLE auth_households ADD COLUMN IF NOT EXISTS owner_id INTEGER",
        "ALTER TABLE auth_households ADD COLUMN IF NOT EXISTS downgraded_at TIMESTAMP",
        "UPDATE auth_households h SET owner_id = (SELECT id FROM auth_users u WHERE u.household_id = h.id ORDER BY id ASC LIMIT 1) WHERE owner_id IS NULL",
        """CREATE TABLE IF NOT EXISTS household_subscription_history (
            id SERIAL PRIMARY KEY,
            household_id INTEGER NOT NULL REFERENCES auth_households(id),
            is_premium BOOLEAN,
            subscription_status TEXT,
            subscription_ends_at TIMESTAMP,
            trial_ends_at TIMESTAMP,
            downgraded_at TIMESTAMP,
            changed_at TIMESTAMP NOT NULL DEFAULT NOW()
        )""",
        """CREATE OR REPLACE FUNCTION log_hh_sub_history() RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'INSERT' OR OLD.is_premium IS DISTINCT FROM NEW.is_premium OR OLD.subscription_status IS DISTINCT FROM NEW.subscription_status OR OLD.subscription_ends_at IS DISTINCT FROM NEW.subscription_ends_at OR OLD.trial_ends_at IS DISTINCT FROM NEW.trial_ends_at OR OLD.downgraded_at IS DISTINCT FROM NEW.downgraded_at THEN
                INSERT INTO household_subscription_history (household_id, is_premium, subscription_status, subscription_ends_at, trial_ends_at, downgraded_at)
                VALUES (NEW.id, NEW.is_premium, NEW.subscription_status, NEW.subscription_ends_at, NEW.trial_ends_at, NEW.downgraded_at);
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql""",
        """DROP TRIGGER IF EXISTS trg_log_hh_sub_history ON auth_households""",
        """CREATE TRIGGER trg_log_hh_sub_history AFTER INSERT OR UPDATE OF is_premium, subscription_status, subscription_ends_at, trial_ends_at, downgraded_at ON auth_households FOR EACH ROW EXECUTE FUNCTION log_hh_sub_history()""",
        """CREATE OR REPLACE FUNCTION update_downgraded_at() RETURNS TRIGGER AS $$
        BEGIN
            IF NEW.is_premium = TRUE OR NEW.subscription_status = 'trial' THEN
                NEW.downgraded_at = NULL;
            ELSIF (NEW.is_premium = FALSE AND OLD.is_premium = TRUE) OR (NEW.subscription_status IN ('expired', 'free', 'canceled') AND OLD.subscription_status IN ('premium', 'active', 'trial')) THEN
                NEW.downgraded_at = COALESCE(NEW.downgraded_at, NOW());
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql""",
        """DROP TRIGGER IF EXISTS trg_update_downgraded_at ON auth_households""",
        """CREATE TRIGGER trg_update_downgraded_at BEFORE UPDATE ON auth_households FOR EACH ROW EXECUTE FUNCTION update_downgraded_at()""",

        "ALTER TABLE auth_households ADD COLUMN IF NOT EXISTS is_premium BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE auth_households ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT",
        "ALTER TABLE auth_households ADD COLUMN IF NOT EXISTS rc_app_user_id TEXT",
        "ALTER TABLE auth_households ADD COLUMN IF NOT EXISTS subscription_status TEXT NOT NULL DEFAULT 'free'",
        "ALTER TABLE auth_households ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMP",
        "ALTER TABLE auth_households ADD COLUMN IF NOT EXISTS subscription_ends_at TIMESTAMP",
        "ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS apple_id TEXT DEFAULT ''"
    ]:
        try:
            _run(stmt)
        except Exception:
            pass

    # Seed dev household and user if they don't exist
    try:
        h = _one("SELECT id FROM auth_households WHERE id = 1")
        if not h:
            _run("INSERT INTO auth_households (id, name, invite_code) VALUES (1, 'Dev Household', 'DEV12345')")
        u = _one("SELECT id FROM auth_users WHERE id = 1")
        if not u:
            _run("INSERT INTO auth_users (id, google_id, email, name, household_id) VALUES (1, 'dev_google_id', 'dev@listmate.local', 'Dev User', 1)")
    except Exception as e:
        print(f'[seed dev error] {e}', flush=True)

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
    app.config["SESSION_COOKIE_SECURE"] = True
    
def _set(uid, email, name, hhid, hhname):
    session[COOKIE_NAME] = {"user_id": uid, "email": email, "name": name,
                             "household_id": hhid, "household_name": hhname}
    session.permanent = True
    session.modified = True

def _clear(): session.pop(COOKIE_NAME, None)
def _get():
    s = session.get(COOKIE_NAME)
    if not s:
        is_dev = bool(os.environ.get("BYPASS_AUTH")) or (not bool(os.environ.get("DATABASE_URL")) and "RENDER" not in os.environ.get("RENDER_EXTERNAL_HOSTNAME", ""))
         
        if is_dev:
            s = {"user_id": 1, "email": "dev@listmate.local", "name": "Dev User", "household_id": 1, "household_name": "Dev Household"}
            session[COOKIE_NAME] = s
            session.permanent = True
            session.modified = True
        else:
            return None
    return s

def get_household_status():
    hhid = get_household_id()
    uid = get_user_id()
    if not hhid or not uid: return None
    hh = _one(f"SELECT * FROM {_HH} WHERE id = ?", (hhid,))
    if not hh: return None
    is_prem = bool(hh.get("is_premium", False))
    sub_status = hh.get("subscription_status", "free")
    trial_ends_at = hh.get("trial_ends_at")
    
    if sub_status == 'trial' and trial_ends_at:
        import datetime
        try:
            t_end = trial_ends_at
            if isinstance(t_end, str):
                if 'T' in t_end:
                    t_end = datetime.datetime.fromisoformat(t_end.replace('Z', '+00:00'))
                else:
                    t_end = datetime.datetime.strptime(t_end, '%Y-%m-%d %H:%M:%S')
            now = datetime.datetime.now(datetime.timezone.utc) if getattr(t_end, 'tzinfo', None) else datetime.datetime.utcnow()
            if t_end > now:
                is_prem = True
        except:
            pass
            
    members = _run(f"SELECT id FROM {_USERS} WHERE household_id = ?", (hhid,))
    is_read_only = False
    over_limit = False
    if not is_prem and len(members) > int(__import__("os").environ.get("FREE_TIER_MEMBER_LIMIT", 1)):
        over_limit = True
        if hh.get("owner_id") != uid:
            is_read_only = True
            
    return {
        "is_premium": is_prem,
        "subscription_status": sub_status,
        "is_read_only": is_read_only,
        "over_limit": over_limit,
        "downgraded_at": hh.get("downgraded_at"),
        "owner_id": hh.get("owner_id")
    }

def is_logged_in(): 
    s = _get()
    return bool(s)
def get_user_id(): 
    s = _get()
    return s.get("user_id") if s else None
def get_display_name(): 
    s = _get()
    return s.get("name", "") if s else ""
def get_email(): 
    s = _get()
    return s.get("email", "") if s else ""
def get_household_id(): 
    s = _get()
    return s.get("household_id", 0) if s else 0
def get_household_name(): 
    s = _get()
    return s.get("household_name", "") if s else ""

def require_user(fn):
    @wraps(fn)
    def w(*a, **kw):
        if not is_logged_in(): return jsonify({"error": "Login required"}), 401
        return fn(*a, **kw)
    return w

# ── Routes ──────────────────────────────────────────────────

def register_auth_routes(app):

    @app.route("/api/auth/poll")
    def auth_poll_intent():
        intent_id = request.args.get("intent")
        if not intent_id: return jsonify({"error": "Missing intent"}), 400
        _init_schema()
        intent = _one("SELECT * FROM login_intents WHERE id = ?", (intent_id,))
        if not intent: return jsonify({"status": "pending"})
        user = _one(f"SELECT id, email, name, household_id FROM {_USERS} WHERE id = ?", (intent["user_id"],))
        if not user: return jsonify({"error": "User not found"}), 404
        hh_id = user.get('household_id', 0)
        hh_name = ''
        if not hh_id:
            hh_count = _one(f"SELECT COUNT(*) as cnt FROM {_HH}", None)
            if hh_count and hh_count.get("cnt", 0) == 0:
                import secrets
                code = secrets.token_hex(4).upper()
                prem_val = True
                _one(f"INSERT INTO {_HH} (name, invite_code, is_premium, subscription_status) VALUES (?,?,?,?)", ("Root Household", code, prem_val, 'premium'))
                hh = _one(f"SELECT id, name FROM {_HH} ORDER BY id DESC LIMIT 1", None)
                hh_id = hh["id"] if hh else 1
                hh_name = hh.get("name", "Root Household") if hh else "Root Household"
                _run(f"UPDATE {_USERS} SET household_id = ? WHERE id = ?", (hh_id, user["id"]))
        if hh_id and not hh_name:
            hh = _one(f"SELECT name FROM {_HH} WHERE id = ?", (hh_id,))
            hh_name = hh.get('name', '') if hh else ''
        _set(user["id"], user["email"], user["name"], hh_id, hh_name)
        _run("DELETE FROM login_intents WHERE id = ?", (intent_id,))
        
        if hh_id == 0:
            return jsonify({"ok": False, "status": "completed", "needs_signup": True, "message": "No household"})
        return jsonify({"ok": True, "status": "completed"})

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
            hh_name = ""
            
            # Auto-assign: only auto-create a household if NO households exist at all (first user ever)
            # Otherwise leave them unassigned — they need to sign up or accept an invite
            if not hh_id:
                hh_count = _one(f"SELECT COUNT(*) as cnt FROM {_HH}", None)
                if hh_count and hh_count.get("cnt", 0) == 0:
                    # First user on a fresh system — create household
                    import secrets
                    code = secrets.token_hex(4).upper()
                    prem_val = True
                    _one(f"INSERT INTO {_HH} (name, invite_code, is_premium, subscription_status) VALUES (?,?,?,?)", ("Root Household", code, prem_val, 'premium'))
                    hh = _one(f"SELECT id, name FROM {_HH} ORDER BY id DESC LIMIT 1", None)
                    hh_id = hh["id"] if hh else 1
                    hh_name = hh["name"] if hh else "Root Household"
                    _run(f"UPDATE {_USERS} SET household_id = ? WHERE id = ?", (hh_id, user["id"]))
                else:
                    _set(user["id"], email, name, 0, "")
                    intent_id = data.get("intent")
                    if intent_id:
                        _run("INSERT INTO login_intents (id, user_id) VALUES (?, ?)", (intent_id, user["id"]))
                    return jsonify({"ok": False, "needs_signup": True,
                                    "message": "No household — please complete signup"}), 200
            if hh_id and not hh_name:
                hh = _one(f"SELECT name FROM {_HH} WHERE id = ?", (hh_id,))
                hh_name = hh.get("name", "") if hh else ""
            
            _set(user["id"], email, name, hh_id, hh_name)

            intent_id = data.get("intent")
            if intent_id:
                _run("INSERT INTO login_intents (id, user_id) VALUES (?, ?)", (intent_id, user["id"]))


            return jsonify({"ok": True, "name": name, "email": email,
                            "household_id": hh_id, "household_name": hh_name})
        except Exception as e:
            # GoogleAuthError (MalformedError, etc) → 401; anything else → 500
            if isinstance(e, GoogleAuthError):
                return jsonify({"error": f"Invalid token: {str(e)}"}), 401
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.route("/api/auth/apple", methods=["POST"])
    def auth_apple():
        try:
            data = request.get_json(silent=True) or {}
            id_token_str = data.get("id_token") or (data.get("authorization") and data.get("authorization").get("id_token"))
            if not id_token_str:
                return jsonify({"error": "Missing id_token"}), 400

            apple_sub = None
            token_email = ""

            try:
                import jwt
                claims = jwt.decode(id_token_str, options={"verify_signature": False})
                apple_sub = claims.get("sub")
                token_email = claims.get("email", "")
            except Exception as jwte:
                print(f"[Apple Auth JWT decode error] {jwte}", flush=True)

            if not apple_sub:
                return jsonify({"error": f"Invalid or unparseable Apple id_token: {jwte}" if "jwte" in locals() else "Invalid or unparseable Apple id_token"}), 400

            client_user = data.get("user") or {}
            if isinstance(client_user, str):
                try:
                    client_user = json.loads(client_user)
                except Exception:
                    client_user = {}

            client_email = client_user.get("email") or ""
            email = (client_email or token_email or "").strip().lower()

            name_obj = client_user.get("name") or {}
            first = name_obj.get("firstName", "") if isinstance(name_obj, dict) else ""
            last = name_obj.get("lastName", "") if isinstance(name_obj, dict) else ""
            name_from_client = f"{first} {last}".strip()

            if not name_from_client:
                name = (email.split("@")[0] if email else f"User_{apple_sub[:6]}").capitalize()
            else:
                name = name_from_client

            gid_alias = f"apple_{apple_sub}"

            _init_schema()

            user = None
            if email:
                user = _one(f"SELECT id, google_id, email, name, household_id FROM {_USERS} WHERE LOWER(email) = LOWER(?)", (email,))
            if not user:
                user = _one(f"SELECT id, google_id, email, name, household_id FROM {_USERS} WHERE google_id = ?", (gid_alias,))

            if not user:
                _run(f"INSERT INTO {_USERS} (google_id, email, name, household_id) VALUES (?,?,?,0)",
                     (gid_alias, email, name))
                user = _one(f"SELECT id, email, name, household_id, google_id FROM {_USERS} WHERE google_id = ?", (gid_alias,))

            if user and not user.get("apple_id"):
                try:
                    _run(f"UPDATE {_USERS} SET apple_id = ? WHERE id = ?", (apple_sub, user["id"]))
                except Exception: pass

            hh_id = user.get("household_id", 0) if user else 0
            hh_name = ""

            if not hh_id:
                hh_count = _one(f"SELECT COUNT(*) as cnt FROM {_HH}", None)
                if hh_count and hh_count.get("cnt", 0) == 0:
                    import secrets
                    code = secrets.token_hex(4).upper()
                    prem_val = True
                    _one(f"INSERT INTO {_HH} (name, invite_code, is_premium, subscription_status) VALUES (?,?,?,?)", ("Root Household", code, prem_val, 'premium'))
                    hh = _one(f"SELECT id, name FROM {_HH} ORDER BY id DESC LIMIT 1", None)
                    hh_id = hh["id"] if hh else 1
                    hh_name = hh["name"] if hh else "Root Household"
                    _run(f"UPDATE {_USERS} SET household_id = ? WHERE id = ?", (hh_id, user["id"]))
                else:
                    _set(user["id"], email, user["name"] or name, 0, "")
                    intent_id = data.get("intent")
                    if intent_id:
                        _run("INSERT INTO login_intents (id, user_id) VALUES (?, ?)", (intent_id, user["id"]))
                    return jsonify({"ok": False, "needs_signup": True, "message": "No household — please complete signup"}), 200

            if hh_id and not hh_name:
                hh = _one(f"SELECT name FROM {_HH} WHERE id = ?", (hh_id,))
                hh_name = hh.get("name", "") if hh else ""

            
            _set(user["id"], email, user["name"] or name, hh_id, hh_name)

            intent_id = data.get("intent")
            if intent_id:
                _run("INSERT INTO login_intents (id, user_id) VALUES (?, ?)", (intent_id, user["id"]))

            return jsonify({"ok": True, "name": user["name"] or name, "email": email, "household_id": hh_id, "household_name": hh_name})
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.route("/api/auth/login", methods=["POST"])
    def auth_login(): return auth_google()

    @app.route("/api/auth/config")
    def auth_config():
        resp = {"client_id": GOOGLE_CLIENT_ID, "revenuecat_public_key": REVENUECAT_PUBLIC_KEY, "revenuecat_apple_key": REVENUECAT_APPLE_KEY}
        if is_logged_in():
            resp["display_name"] = get_display_name()
            resp["user"] = get_display_name().split(" ")[0].lower()
            uid = get_user_id()
            hh_id = get_household_id()
            is_prem = False
            if hh_id:
                _init_schema()
                hh = _one(f"SELECT is_premium, subscription_status, trial_ends_at, subscription_ends_at, owner_id FROM {_HH} WHERE id = ?", (hh_id,))
                is_prem = bool(hh.get("is_premium")) if hh else False
                sub_status = hh.get("subscription_status", "free") if hh else "free"
                trial_ends_at = hh.get("trial_ends_at") if hh else None
                if trial_ends_at and hasattr(trial_ends_at, 'isoformat'):
                    trial_ends_at = trial_ends_at.isoformat()
                subscription_ends_at = hh.get("subscription_ends_at") if hh else None
                if subscription_ends_at and hasattr(subscription_ends_at, 'isoformat'):
                    subscription_ends_at = subscription_ends_at.isoformat()

                
                # Check active trial
                if sub_status == 'trial' and trial_ends_at:
                    import datetime
                    try:
                        t_end = trial_ends_at
                        if isinstance(t_end, str):
                            if 'T' in t_end:
                                t_end = datetime.datetime.fromisoformat(t_end.replace('Z', '+00:00'))
                            else:
                                t_end = datetime.datetime.strptime(t_end, '%Y-%m-%d %H:%M:%S')
                        now = datetime.datetime.now(datetime.timezone.utc) if getattr(t_end, 'tzinfo', None) else datetime.datetime.utcnow()
                        if t_end > now:
                            is_prem = True
                        else:
                            sub_status = "expired"
                    except:
                        pass

            status = get_household_status() if hh_id else {"is_read_only": False, "over_limit": False}
            resp["is_premium"] = is_prem
            resp["subscription_status"] = sub_status if hh_id else "free"
            resp["trial_ends_at"] = trial_ends_at if hh_id else None
            resp["subscription_ends_at"] = subscription_ends_at if hh_id else None
            resp["is_read_only"] = status["is_read_only"]
            resp["is_owner"] = (uid == hh.get("owner_id")) if (hh_id and hh) else True
            resp["user_info"] = {"id": uid, "name": get_display_name(),
                "email": get_email(), "household_id": hh_id,
                "household_name": get_household_name(), "is_premium": is_prem, "subscription_status": sub_status if hh_id else "free", "trial_ends_at": trial_ends_at if hh_id else None, "subscription_ends_at": subscription_ends_at if hh_id else None}
            if uid:
                _init_schema()
                flags = _run(f"SELECT feature, enabled FROM {_FLAGS} WHERE user_id = ?", (uid,))
                resp["feature_flags"] = {f["feature"]: bool(f["enabled"]) for f in flags}
        return jsonify(resp)

    @app.route("/api/auth/logout", methods=["POST"])
    def auth_logout(): _clear(); return jsonify({"ok": True})

    @app.route("/api/auth/delete-account", methods=["POST", "DELETE"])
    @require_user
    def auth_delete_account():
        uid = get_user_id()
        hhid = get_household_id()
        if not uid:
            return jsonify({"error": "Unauthorized"}), 401

        _init_schema()

        if hhid:
            hh = _one(f"SELECT is_premium, subscription_status, owner_id FROM {_HH} WHERE id = ?", (hhid,))
            if hh and hh.get("owner_id") == uid:
                is_prem = hh.get("is_premium")
                sub_status = hh.get("subscription_status")
                is_early = bool(is_prem and sub_status == "premium" and hhid and int(hhid) <= int(__import__("os").environ.get("EARLY_ADOPTER_LIMIT", 25)))
                if is_prem and not is_early and sub_status in ['active', 'premium', 'trial']:
                    return jsonify({"error": "You cannot delete your account while you have an active subscription as the household owner. Please cancel your subscription first."}), 403


        # 1. Delete feature flags
        try: _run(f"DELETE FROM {_FLAGS} WHERE user_id = ?", (uid,))
        except Exception: pass

        # 2. Check remaining members in household
        members = _run(f"SELECT id FROM {_USERS} WHERE household_id = ?", (hhid,)) if hhid else []
        is_last_member = len(members) <= 1

        # 3. Delete user record
        _run(f"DELETE FROM {_USERS} WHERE id = ?", (uid,))

        # 4. If last member, purge household data
        if hhid and is_last_member:
            for stmt in [
                "DELETE FROM store_enrich_queue WHERE household_id = ?",
                "DELETE FROM store_visits WHERE household_id = ?",
                "DELETE FROM list_items WHERE household_id = ?",
                "DELETE FROM store_items WHERE household_id = ?",
                "DELETE FROM stores WHERE household_id = ?",
                "DELETE FROM invites WHERE household_id = ?",
                f"DELETE FROM {_HH} WHERE id = ?",
            ]:
                try: _run(stmt, (hhid,))
                except Exception: pass

        _clear()
        return jsonify({"ok": True, "message": "Account deleted successfully"})

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
        count_row = _one(f"SELECT COUNT(*) as cnt FROM {_HH}")
        existing_cnt = count_row.get("cnt", 0) if count_row else 0
        is_early = existing_cnt < int(__import__("os").environ.get("EARLY_ADOPTER_LIMIT", 25))
        prem_val = is_early
        status = 'premium' if is_early else 'trial'
        trial_expr = "NOW() + INTERVAL '30 days'" if not is_early else "NULL"
        hhid = _insert(f"INSERT INTO {_HH} (name, invite_code, is_premium, subscription_status, trial_ends_at) VALUES (?,?,?,?, {trial_expr}) RETURNING id", (hname, code, prem_val, status))
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
        if not hh: return jsonify({"error": "Household not found"}), 404
        
        status = get_household_status()
        is_prem = status["is_premium"]
        sub_status = status["subscription_status"]
        trial_ends_at = hh.get("trial_ends_at")
        subscription_ends_at = hh.get("subscription_ends_at")
        if subscription_ends_at and hasattr(subscription_ends_at, 'isoformat'):
            subscription_ends_at = subscription_ends_at.isoformat()
            
        members = _run(f"SELECT id, name, email FROM {_USERS} WHERE household_id = ?", (hhid,))
        invites = _run("SELECT token, email, created_at FROM invites WHERE household_id = ? AND used_by IS NULL ORDER BY created_at DESC", (hhid,))
        
        return jsonify({"ok": True,
            "household": {
                "id": hh["id"], "name": hh["name"], "invite_code": hh.get("invite_code",""), 
                "is_premium": is_prem, "subscription_status": sub_status, 
                "trial_ends_at": trial_ends_at, "subscription_ends_at": subscription_ends_at,
                "is_owner": uid == hh.get("owner_id"), "is_read_only": status["is_read_only"],
                "over_limit": status["over_limit"]
            },
            "members": [{"user_id": m["id"], "email": m["email"], "display_name": m["name"], 
                         "role": "owner" if m["id"] == hh.get("owner_id") else "member"} for m in members],
            "pending_invites": [{"email": i["email"], "token": i["token"], "created_at": str(i.get("created_at",""))} for i in invites],
            "current_user_id": uid, "is_owner": (uid == hh.get("owner_id"))})

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

        base = request.host_url.rstrip('/')
        invite_link = f"{base}/login?token={token}"

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
        from flask import request
        _init_schema()
        invite = _one("SELECT * FROM invites WHERE token = ? AND used_by IS NULL", (token,))
        if not invite:
            return jsonify({"error": "Invalid or expired invite"}), 404

        uid = get_user_id()
        user = _one(f"SELECT * FROM {_USERS} WHERE id = ?", (uid,))

        if invite.get("email") and user.get("email","").lower() != invite["email"].lower():
            return jsonify({"error": "This invite is for a different email address"}), 403

        current_hh_id = user.get("household_id")
        if current_hh_id and current_hh_id != invite["household_id"] and current_hh_id != 0:
            current_hh = _one(f"SELECT owner_id FROM {_HH} WHERE id = ?", (current_hh_id,))
            if current_hh and current_hh.get("owner_id") == uid:
                return jsonify({"error": "You are the owner of a household. You cannot accept this invite without transferring ownership first."}), 403
            
            force = request.args.get("force") or request.form.get("force") or (request.is_json and request.json.get("force"))
            if str(force).lower() not in ["true", "1"]:
                return jsonify({
                    "requires_confirmation": True,
                    "warning": "You are currently in another household. Accepting this invite will switch your household and you will lose access to the current one. Continue?"
                }), 409

        _run(f"UPDATE {_USERS} SET household_id = ? WHERE id = ?", (invite["household_id"], uid))
        import datetime as _dt2
        _exec("UPDATE invites SET used_by = ?, used_at = ? WHERE id = ?", (uid, _dt2.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'), invite["id"]))

        hh = _one(f"SELECT name FROM {_HH} WHERE id = ?", (invite["household_id"],))
        hh_name = hh.get("name","") if hh else ""
        _set(uid, user["email"], user["name"], invite["household_id"], hh_name)
        return jsonify({"ok": True, "household_id": invite["household_id"], "household_name": hh_name})

    @app.route("/api/auth/household/spinoff", methods=["POST"])
    @require_user
    def auth_spinoff_household():
        uid = get_user_id()
        old_hhid = get_household_id()
        if not old_hhid: return jsonify({"error": "No household"}), 404
        
        status = get_household_status()
        if not status or not status["is_read_only"]:
            return jsonify({"error": "Spin-off is only for read-only secondary members."}), 400
            
        data = request.get_json(silent=True) or {}
        new_name = data.get("name")
        if not new_name:
            user = _one(f"SELECT name FROM {_USERS} WHERE id = ?", (uid,))
            new_name = user["name"] + "'s Household" if user and user.get("name") else "My Personal Household"
        
        # Create new household without premium/trial
        import secrets
        code = secrets.token_hex(4).upper()
        res = _one(f"INSERT INTO {_HH} (name, invite_code, is_premium, subscription_status, owner_id) VALUES (?, ?, False, 'free', ?) RETURNING id", (new_name, code, uid))
        new_hhid = res["id"]
        
        # Move the user to the new household
        _run(f"UPDATE {_USERS} SET household_id = ? WHERE id = ?", (new_hhid, uid))
        
        # We need to copy lists, etc.
        # But this is inside auth.py, we might not have all tables imported. 
        # The schema is standard, we can just run queries directly.
        
        downgraded_at = status["downgraded_at"]
        
        # Copy stores
        old_stores = _run("SELECT * FROM stores WHERE household_id = ?", (old_hhid,))
        for s in old_stores:
            if downgraded_at and s.get("created_at") and s["created_at"] > downgraded_at: continue
            r = _one("INSERT INTO stores (household_id, name) VALUES (?, ?) RETURNING id", (new_hhid, s["name"]))
            new_store_id = r["id"]
            
            # Copy store items
            # store_items doesn't have created_at
            _run("INSERT INTO store_items (store_id, household_id, name, category) SELECT ?, ?, name, category FROM store_items WHERE store_id = ?", (new_store_id, new_hhid, s["id"]))
            
            # Copy list items (filtered by downgraded_at)
            if downgraded_at:
                _run("INSERT INTO list_items (store_id, household_id, name, category, added_by, purchased, purchased_by, quantity) SELECT ?, ?, name, category, added_by, purchased, purchased_by, quantity FROM list_items WHERE store_id = ? AND added_at <= ?", (new_store_id, new_hhid, s["id"], downgraded_at))
            else:
                _run("INSERT INTO list_items (store_id, household_id, name, category, added_by, purchased, purchased_by, quantity) SELECT ?, ?, name, category, added_by, purchased, purchased_by, quantity FROM list_items WHERE store_id = ?", (new_store_id, new_hhid, s["id"]))
        
        # Copy recipes
        if downgraded_at:
            _run("INSERT INTO recipes (household_id, title, description, prep_time, cook_time, servings, cuisine, dietary_tags, instructions, ingredients) SELECT ?, title, description, prep_time, cook_time, servings, cuisine, dietary_tags, instructions, ingredients FROM recipes WHERE household_id = ? AND created_at <= ?", (new_hhid, old_hhid, downgraded_at))
        else:
            _run("INSERT INTO recipes (household_id, title, description, prep_time, cook_time, servings, cuisine, dietary_tags, instructions, ingredients) SELECT ?, title, description, prep_time, cook_time, servings, cuisine, dietary_tags, instructions, ingredients FROM recipes WHERE household_id = ?", (new_hhid, old_hhid))

        _set(uid, get_email(), get_display_name(), new_hhid, new_name)
        return jsonify({"ok": True, "household_id": new_hhid})
