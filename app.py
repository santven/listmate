#!/usr/bin/env python3
"""ListMate — store-specific grocery list for households.
Each household's data is completely isolated by household_id on every query.
Uses SQLite locally; switches to PostgreSQL when DATABASE_URL is set."""
import os, json, sys, time, re, urllib.request
from functools import wraps
from urllib.parse import quote, urlencode

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from flask import Flask, request, jsonify, session, redirect, send_from_directory
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

import shared.auth as authmod
from shared.auth import (
    install as install_auth, register_auth_routes,
    require_user, get_user_id, get_display_name,
    get_household_id, get_household_name, get_email, is_logged_in,
)

import pii_sanitizer
from categorize import categorize

from werkzeug.middleware.proxy_fix import ProxyFix
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__, static_folder="static")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

# API Security and Rate Limiting
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["1000 per day", "300 per hour"],
    storage_uri="memory://"
)

install_auth(app, cookie_name="listmate_session", cookie_secure=False)

CLIENT_ID = os.environ.get("SSO_GOOGLE_CLIENT_ID",
                           "526061928190-8si99s2n17u7onf8mo2uapfjphtopnc1.apps.googleusercontent.com")
APPLE_CLIENT_ID = os.environ.get("SSO_APPLE_CLIENT_ID",
                           os.environ.get("APPLE_CLIENT_ID", "com.pvkslabs.listmate.web"))
DB_PATH = os.environ.get("DB_PATH", "listmate.db")

# ── Schema migration: dietary_restrictions (added Jul 2026, idempotent) ──

_MIGRATED = False

def _ensure_schema():
    global _MIGRATED
    if _MIGRATED:
        return
    _MIGRATED = True
    try:
        authmod._init_schema()
        col_type = "TEXT DEFAULT ''"
        prem_type = "BOOLEAN DEFAULT FALSE"
        
        for col, ctype in [
            ("dietary_restrictions", col_type),
            ("zip_code", col_type),
            ("country", col_type),
            ("is_premium", prem_type)
        ]:
            try:
                authmod._run(f"ALTER TABLE {authmod._HH} ADD COLUMN IF NOT EXISTS {col} {ctype}")
            except Exception:
                pass

        store_tables = [
            """CREATE TABLE IF NOT EXISTS stores (
                id SERIAL PRIMARY KEY, name TEXT NOT NULL,
                household_id INTEGER NOT NULL DEFAULT 1,
                planned_visit_date DATE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS store_items (
                id SERIAL PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
                name TEXT NOT NULL, category TEXT NOT NULL DEFAULT '',
                household_id INTEGER NOT NULL DEFAULT 1)""",
            """CREATE TABLE IF NOT EXISTS list_items (
                id SERIAL PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
                name TEXT NOT NULL, category TEXT NOT NULL DEFAULT '',
                added_by TEXT NOT NULL DEFAULT '', added_at TIMESTAMP NOT NULL DEFAULT NOW(),
                purchased BOOLEAN NOT NULL DEFAULT FALSE,
                purchased_by TEXT, purchased_at TIMESTAMP,
                household_id INTEGER NOT NULL DEFAULT 1)""",
            """CREATE TABLE IF NOT EXISTS store_visits (
                id SERIAL PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
                household_id INTEGER NOT NULL DEFAULT 1,
                visit_date DATE NOT NULL, items_count INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS store_enrich_queue (
                id SERIAL PRIMARY KEY, store_id INTEGER NOT NULL,
                household_id INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                processed_at TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS item_purchase_stats (
                id SERIAL PRIMARY KEY,
                household_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                total_purchases INTEGER NOT NULL DEFAULT 1,
                last_purchased TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE(household_id, name)
            )""",
            """CREATE TABLE IF NOT EXISTS ai_insights_cache (
                id SERIAL PRIMARY KEY,
                household_id INTEGER NOT NULL UNIQUE,
                insight_text TEXT NOT NULL,
                generated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )""",
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_stores_hh_name ON stores(household_id, name)""",
            """CREATE INDEX IF NOT EXISTS idx_li_store ON list_items(store_id, household_id, purchased)""",
            """CREATE INDEX IF NOT EXISTS idx_sv_store ON store_visits(store_id, household_id, visit_date)""",
            """CREATE INDEX IF NOT EXISTS idx_si_store_name ON store_items(household_id, store_id, name)""",
        ]
        for stmt in store_tables:
            try: authmod._run(stmt)
            except Exception: pass
            
        try:
            authmod._run('''
                INSERT INTO item_purchase_stats (household_id, name, category, total_purchases, last_purchased)
                SELECT household_id, name, MAX(COALESCE(category, '')), COUNT(*), NOW()
                FROM list_items
                WHERE purchased = TRUE
                GROUP BY household_id, name
                ON CONFLICT (household_id, name) DO NOTHING
            ''')
        except Exception as e:
            pass
            
        try: authmod._run("ALTER TABLE stores ADD COLUMN IF NOT EXISTS planned_visit_date DATE")
        except Exception: pass

        try:
            from db_pg import init_db as init_store_db
            init_store_db()
            from categorize import backfill_uncategorized_items
            backfill_uncategorized_items()
        except Exception:
            pass
    except Exception:
        pass


@app.before_request
def enforce_read_only():
    if request.method in ["POST", "PUT", "DELETE"]:
        if request.path.startswith("/api/list") or request.path.startswith("/api/stores") or request.path.startswith("/api/recipes") or request.path == "/api/sync":
            # Allowed for read-only: None, but wait, maybe some specific ones?
            if request.path == "/api/recipes/generate":
                # Recipes generate might require premium entirely, but let's just guard modifications to data.
                pass
            import shared.auth as authmod_local
            try:
                hh_status = authmod_local.get_household_status()
                if hh_status and hh_status.get("is_read_only"):
                    return jsonify({"error": "Live household sync is paused because your household is on the Free plan. Only the owner can make changes, or you can spin off into a personal household.", "code": "read_only"}), 403
            except Exception:
                pass

@app.before_request

def _check_migration():
    _ensure_schema()

# Database: PostgreSQL
import db_pg as dbmod


def get_db():
    return dbmod.get_db()


def close_db(conn):
    dbmod.close_db(conn)


def _hh():
    """Current household_id — used to scope EVERY query."""
    return get_household_id() or 0


# ── Pages ───────────────────────────────────────────────────

@app.after_request
def add_security_headers(response):
    response.headers['Content-Security-Policy'] = "default-src 'self' https: data: 'unsafe-inline' 'unsafe-eval';"
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

@app.route("/login", methods=["GET", "POST"])
@limiter.limit("20 per minute")
def login_page():
    if request.method == "POST":
        id_token_str = request.form.get("id_token")
        user_json = request.form.get("user")
        state_str = request.form.get("state")
        
        if id_token_str:
            import jwt
            import json
            import secrets
            try:
                claims = jwt.decode(id_token_str, options={"verify_signature": False})
                apple_sub = claims.get("sub")
                token_email = claims.get("email", "")
                if apple_sub:
                    import shared.auth as authmod
                    authmod._init_schema()
                    
                    client_user = {}
                    if user_json:
                        try: client_user = json.loads(user_json)
                        except: pass
                    
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
                    user = None
                    if apple_sub:
                        user = authmod._one(f"SELECT id, google_id, apple_id, email, name, household_id FROM {authmod._USERS} WHERE apple_id = ?", (apple_sub,))
                    if not user and email:
                        user = authmod._one(f"SELECT id, google_id, apple_id, email, name, household_id FROM {authmod._USERS} WHERE LOWER(email) = LOWER(?)", (email,))
                    if not user:
                        user = authmod._one(f"SELECT id, google_id, apple_id, email, name, household_id FROM {authmod._USERS} WHERE google_id = ?", (gid_alias,))
                        
                    is_new_user = False
                    if not user:
                        is_new_user = True
                        authmod._run(f"INSERT INTO {authmod._USERS} (google_id, apple_id, email, name, household_id) VALUES (?,?,?,?,0)", (gid_alias, apple_sub, email, name))
                        user = authmod._one(f"SELECT id, email, name, household_id, google_id, apple_id FROM {authmod._USERS} WHERE apple_id = ? OR google_id = ?", (apple_sub, gid_alias))
                    
                    if user and (not user.get("apple_id") or user.get("apple_id") == ""):
                        try:
                            authmod._run(f"UPDATE {authmod._USERS} SET apple_id = ? WHERE id = ?", (apple_sub, user["id"]))
                            user["apple_id"] = apple_sub
                        except Exception: pass
                    
                    if user:
                        uid = user["id"]
                        hh_id = user.get("household_id", 0) or 0
                        hh_name = ""
                        if not is_new_user and hh_id == 0:
                            owned = authmod._one("SELECT household_id FROM auth_household_members WHERE user_id = ? AND role = 'owner' LIMIT 1", (uid,))
                            if owned:
                                hh_id = owned["household_id"]
                                authmod._run(f"UPDATE {authmod._USERS} SET household_id = ? WHERE id = ?", (hh_id, uid))
                            else:
                                mem = authmod._one("SELECT household_id FROM auth_household_members WHERE user_id = ? LIMIT 1", (uid,))
                                if mem:
                                    hh_id = mem["household_id"]
                                    authmod._run(f"UPDATE {authmod._USERS} SET household_id = ? WHERE id = ?", (hh_id, uid))
                        if not hh_id:
                            hh_count = authmod._one(f"SELECT COUNT(*) as cnt FROM {authmod._HH}", None)
                            if hh_count and hh_count.get("cnt", 0) == 0:
                                code = secrets.token_hex(4).upper()
                                prem_val = True
                                authmod._run(f"INSERT INTO {authmod._HH} (name, invite_code, is_premium, subscription_status) VALUES (?,?,?,?)", ("Root Household", code, prem_val, "premium"))
                                hh = authmod._one(f"SELECT id, name FROM {authmod._HH} ORDER BY id DESC LIMIT 1", None)
                                hh_id = hh["id"] if hh else 1
                                hh_name = hh["name"] if hh else "Root Household"
                                authmod._run(f"UPDATE {authmod._USERS} SET household_id = ? WHERE id = ?", (hh_id, user["id"]))
                        if hh_id and not hh_name:
                            hh = authmod._one(f"SELECT name FROM {authmod._HH} WHERE id = ?", (hh_id,))
                            hh_name = hh.get("name", "") if hh else ""
                        authmod._set(user["id"], email, name, hh_id, hh_name)
                        
                        if state_str and state_str.startswith("intent_"):
                            intent_id = state_str.split("intent_")[1].replace("_web", "")
                            if intent_id:
                                authmod._run("INSERT INTO login_intents (id, user_id) VALUES (?, ?)", (intent_id, user["id"]))
                        
                        code_token = secrets.token_urlsafe(32)
                        authmod._run("INSERT INTO login_intents (id, user_id) VALUES (?, ?)", ("code_" + code_token, user["id"]))
                        
                        return f"""<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Authenticating...</title></head><body style="text-align:center;font-family:sans-serif;padding-top:40px;background:#f0f4ed;color:#2c2c2c;"><h2>✅ Authenticating...</h2><p style="color:#888;margin-top:20px;">Redirecting to ListMate...</p><script>window.location.replace("/auth/callback?code={code_token}");</script></body></html>"""
            except Exception as e:
                import traceback
                traceback.print_exc()
            # Fallback
            return f'''<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>
            <body><script>
            sessionStorage.setItem('apple_id_token', {json.dumps(id_token_str)});
            sessionStorage.setItem('apple_user', {json.dumps(user_json or '')});
            sessionStorage.setItem('apple_state', {json.dumps(state_str or '')});
            window.location.replace('/login');
            </script></body></html>'''
            
    html = open(os.path.join(os.path.dirname(__file__), "static", "login.html")).read()
    html = html.replace("CLIENT_ID_PLACEHOLDER", CLIENT_ID)
    return html.replace("APPLE_CLIENT_ID_PLACEHOLDER", APPLE_CLIENT_ID)

@app.route("/auth/callback")
def auth_callback():
    code = request.args.get("code")
    if not code:
        return redirect("/login")
    import shared.auth as authmod
    authmod._init_schema()
    intent = authmod._one("SELECT * FROM login_intents WHERE id = ?", ("code_" + code,))
    if not intent:
        return redirect("/login")
    user = authmod._one(f"SELECT id, email, name, household_id FROM {authmod._USERS} WHERE id = ?", (intent["user_id"],))
    if not user:
        return redirect("/login")
    authmod._run("DELETE FROM login_intents WHERE id = ?", ("code_" + code,))
    hh_id = user.get("household_id", 0)
    hh_name = ""
    if hh_id:
        hh = authmod._one(f"SELECT name FROM {authmod._HH} WHERE id = ?", (hh_id,))
        hh_name = hh.get("name", "") if hh else ""
    authmod._set(user["id"], user.get("email", ""), user.get("name", ""), hh_id, hh_name)
    target_url = "/login?needs_signup=1" if hh_id == 0 else "/"
    return f"""<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Authentication Successful</title></head><body style="text-align:center;font-family:sans-serif;padding-top:40px;background:#f0f4ed;color:#2c2c2c;"><h2>✅ Authentication Successful</h2><p style="color:#888;margin-top:20px;">Redirecting to ListMate...</p><script>function proceed(){{try{{window.location.href="listmate://sso_callback";}}catch(e){{}}setTimeout(function(){{window.location.replace("{target_url}");}},1000);}}if(window.opener && window.opener !== window){{try{{window.close();}}catch(e){{}}setTimeout(proceed, 500);}}else{{proceed();}}</script></body></html>"""


@app.route("/login_google_native", methods=["POST"])
@limiter.limit("20 per minute")
def login_google_native():
    c = request.form.get("credential")
    intent_id = request.form.get("intent")
    try:
        from google.oauth2 import id_token
        import google.auth.transport.requests as google_requests
        info = id_token.verify_firebase_token(c, google_requests.Request(), 'listmate-58e1a')
        gid = info['sub']
        email = (info.get("email") or "").strip().lower()
        name = info.get("name") or (email.split("@")[0] if email else "User")
        
        import shared.auth as authmod
        authmod._init_schema()
        user = None
        if email:
            user = authmod._one(f"SELECT id, google_id, apple_id, email, name, household_id FROM {authmod._USERS} WHERE LOWER(email) = LOWER(?)", (email,))
        if not user:
            user = authmod._one(f"SELECT id, google_id, apple_id, email, name, household_id FROM {authmod._USERS} WHERE google_id = ?", (gid,))
        
        is_new_user = False
        if not user:
            is_new_user = True
            authmod._run(f"INSERT INTO {authmod._USERS} (google_id, email, name, household_id) VALUES (?,?,?,0)", (gid, email, name))
            user = authmod._one(f"SELECT id, email, name, household_id, google_id, apple_id FROM {authmod._USERS} WHERE google_id = ?", (gid,))
            
        if user:
            if user.get("google_id") != gid:
                authmod._run(f"UPDATE {authmod._USERS} SET google_id = ? WHERE id = ?", (gid, user["id"]))
            
            uid = user["id"]
            hh_id = user.get("household_id", 0) or 0
            hh_name = ""
            
            if not is_new_user and hh_id == 0:
                owned = authmod._one("SELECT household_id FROM auth_household_members WHERE user_id = ? AND role = 'owner' LIMIT 1", (uid,))
                if owned:
                    hh_id = owned["household_id"]
                    authmod._run(f"UPDATE {authmod._USERS} SET household_id = ? WHERE id = ?", (hh_id, uid))
                else:
                    mem = authmod._one("SELECT household_id FROM auth_household_members WHERE user_id = ? LIMIT 1", (uid,))
                    if mem:
                        hh_id = mem["household_id"]
                        authmod._run(f"UPDATE {authmod._USERS} SET household_id = ? WHERE id = ?", (hh_id, uid))
            
            if not hh_id:
                hh_count = authmod._one(f"SELECT COUNT(*) as cnt FROM {authmod._HH}", None)
                if hh_count and hh_count.get("cnt", 0) == 0:
                    import secrets
                    code = secrets.token_hex(4).upper()
                    prem_val = True
                    authmod._run(f"INSERT INTO {authmod._HH} (name, invite_code, is_premium, subscription_status) VALUES (?,?,?,?)", ("Root Household", code, prem_val, 'premium'))
                    hh = authmod._one(f"SELECT id, name FROM {authmod._HH} ORDER BY id DESC LIMIT 1", None)
                    hh_id = hh["id"] if hh else 1
                    hh_name = hh["name"] if hh else "Root Household"
                    authmod._run(f"UPDATE {authmod._USERS} SET household_id = ? WHERE id = ?", (hh_id, user["id"]))
            
            if hh_id and not hh_name:
                hh = authmod._one(f"SELECT name FROM {authmod._HH} WHERE id = ?", (hh_id,))
                hh_name = hh.get("name", "") if hh else ""
            
            authmod._set(user["id"], email, user.get("name") or name, hh_id, hh_name)
            if intent_id:
                authmod._run("INSERT INTO login_intents (id, user_id) VALUES (?, ?)", (intent_id, user["id"]))
                
            if hh_id == 0:
                return '''<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><script>window.location.replace('/login?needs_signup=1');</script></body></html>'''
                
            return '''<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><script>window.location.replace('/');</script></body></html>'''
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f'''<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><script>alert("Login failed"); window.location.replace('/login');</script></body></html>'''

@app.route("/open")
def open_deep_link():
    url = request.args.get("url", "/")
    if url.startswith("http"):
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path
        if parsed.query:
            path += "?" + parsed.query
    else:
        path = url
    if not path.startswith("/"):
        path = "/" + path

    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Opening ListMate...</title>
        <style>
            body {{ font-family: -apple-system, sans-serif; text-align: center; padding-top: 60px; background: #f0f4ed; color: #2c5a2c; }}
            .loader {{ border: 3px solid #eaf8ef; border-top: 3px solid #5ebe7e; border-radius: 50%; width: 36px; height: 36px; animation: spin 1s linear infinite; margin: 24px auto; }}
            @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
            .btn {{ display: inline-block; background: #5ebe7e; color: #fff; padding: 14px 28px; text-decoration: none; border-radius: 10px; font-weight: bold; margin-top: 24px; box-shadow: 0 2px 6px rgba(94,190,126,0.3); }}
            p {{ color: #64748b; font-size: 14px; margin-top: 32px; }}
        </style>
    </head>
    <body>
        <h2 style="margin:0; font-size: 22px;">Opening ListMate...</h2>
        <div class="loader"></div>
        <p>If the app does not open automatically:</p>
        <a href="{path}" class="btn">Continue in Browser</a>
        <script>
            var path = "{path}";
            var customSchemeUrl = "listmate:/" + path; // e.g. listmate://requests/1
            var webUrl = window.location.origin + path;
            var host = window.location.host;
            var intentUrl = "intent://" + host + path + "#Intent;scheme=https;package=com.pvkslabs.listmate;S.browser_fallback_url=" + encodeURIComponent(webUrl) + ";end";
            
            var isAndroid = /Android/i.test(navigator.userAgent);
            var isIOS = /iPhone|iPad|iPod/i.test(navigator.userAgent);
            
            setTimeout(function() {{
                if (isAndroid) {{
                    window.location.href = intentUrl;
                }} else if (isIOS) {{
                    window.location.href = customSchemeUrl;
                    setTimeout(function() {{
                        window.location.href = webUrl;
                    }}, 2000);
                }} else {{
                    window.location.href = webUrl;
                }}
            }}, 100);
        </script>
    </body>
    </html>
    '''
@app.route("/signup")
def signup_page():
    return redirect("/login")
@app.route("/privacy")
def privacy_page():
    return send_from_directory("static", "privacy.html")

@app.route("/terms")
def terms_page():
    return send_from_directory("static", "terms.html")


@app.route("/settings")
def settings_page():
    if not is_logged_in():
        next_url = request.full_path if request.query_string else request.path
        return redirect("/login?next=" + quote(next_url))
    return send_from_directory("static", "settings.html")


@app.route("/upgrade")
def upgrade_page():
    source = request.args.get("source", "direct")
    target_path = f"/settings?action=upgrade&source={source}"
    if not is_logged_in():
        return redirect("/login?next=" + quote(target_path))
    return redirect(target_path)


@app.route("/requests")
@app.route("/requests/<int:req_id>")
def requests_page(req_id=None):
    return send_from_directory("static", "requests.html")


# ── Dietary restrictions (household-level) ──

@app.route("/api/settings/dietary", methods=["GET", "POST"])
@require_user
def dietary_settings():
    hhid = _hh()
    if not hhid:
        return jsonify({"error": "No household"}), 400
    authmod._init_schema()
    
    if request.method == "GET":
        hh = authmod._one(f"SELECT dietary_restrictions FROM {authmod._HH} WHERE id = ?", (hhid,))
        val = (hh.get("dietary_restrictions") or "") if hh else ""
        return jsonify({"dietary_restrictions": val})
    
    data = request.get_json(silent=True) or {}
    restrictions = (data.get("dietary_restrictions") or "").strip()
    authmod._run(f"UPDATE {authmod._HH} SET dietary_restrictions = ? WHERE id = ?", (restrictions, hhid))
    return jsonify({"ok": True, "dietary_restrictions": restrictions})

@app.route("/api/settings/location", methods=["GET", "POST"])
@require_user
def location_settings():
    """Get or set household location (zip + country)."""
    hhid = _hh()
    if not hhid:
        return jsonify({"error": "No household"}), 400
    authmod._init_schema()
    
    if request.method == "GET":
        hh = authmod._one(f"SELECT zip_code, country FROM {authmod._HH} WHERE id = ?", (hhid,))
        return jsonify({
            "zip_code": (hh.get("zip_code") or "") if hh else "",
            "country": (hh.get("country") or "") if hh else ""
        })
    
    data = request.get_json(silent=True) or {}
    zip_code = (data.get("zip_code") or "").strip()
    country = (data.get("country") or "").strip()
    authmod._run(f"UPDATE {authmod._HH} SET zip_code = ?, country = ? WHERE id = ?", (zip_code, country, hhid))
    return jsonify({"ok": True, "zip_code": zip_code, "country": country})


def _find_household_id_from_uid(uid, event=None):
    """Resolve household_id from app_user_id, household_id, or event aliases."""
    candidates = []
    if uid:
        candidates.append(str(uid))
    if event and isinstance(event, dict):
        aliases = event.get("aliases", [])
        if isinstance(aliases, list):
            candidates.extend([str(a) for a in aliases])
        orig_id = event.get("original_app_user_id")
        if orig_id:
            candidates.append(str(orig_id))
        transferred_to = event.get("transferred_to", [])
        if isinstance(transferred_to, list):
            candidates.extend([str(a) for a in transferred_to])

    for cand in candidates:
        clean = cand.replace("hh_", "").replace("user_", "").replace("hh-", "").replace("user-", "").strip()
        if clean.isdigit():
            cand_int = int(clean)
            user = authmod._one(f"SELECT household_id FROM {authmod._USERS} WHERE id = ?", (cand_int,))
            if user and user.get("household_id"):
                return user["household_id"]
            hh = authmod._one(f"SELECT id FROM {authmod._HH} WHERE id = ?", (cand_int,))
            if hh and hh.get("id"):
                return hh["id"]
    return None


@app.route("/api/feedback", methods=["POST"])
@require_user
def submit_feedback():
    data = request.get_json() or {}
    message = data.get("message", "").strip()
    feedback_type = data.get("type", "feedback")
    rating = data.get("rating", 0)
    if rating == 0:
        rating = None
    if not message:
        return jsonify({"error": "Message is required"}), 400
    
    hhid = _hh()
    user_email = get_email()
    user_name = get_display_name()
    
    db = get_db()
    try:
        db.execute(
            "INSERT INTO app_feedback (household_id, user_email, user_name, feedback_type, rating, message) VALUES (%s, %s, %s, %s, %s, %s)",
            (hhid, user_email, user_name, feedback_type, rating, message)
        )
        db.commit()
    except Exception as e:
        print(f"Feedback insert error: {e}")
    finally:
        close_db(db)
        
    return jsonify({"success": True})


# ── Feedback Loop & Roadmap APIs ──────────────────────────

ADMIN_EMAILS = {"venragh@gmail.com"}

def is_admin_user():
    email = (get_email() or "").strip().lower()
    return is_logged_in() and email in ADMIN_EMAILS

def require_admin(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_admin_user():
            return jsonify({"error": "Forbidden: Admin access only"}), 403
        return f(*args, **kwargs)
    return decorated_function

def _serialize_feedback(row):
    if not row:
        return None
    d = dict(row)
    for k in ["created_at", "resolved_at", "notified_at", "acknowledged_at"]:
        if d.get(k) and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    return d

@app.route("/api/feedback/unacknowledged-resolved", methods=["GET"])
@require_user
def get_unacknowledged_resolved_feedback():
    """Get resolved feedback for current user that hasn't been acknowledged in-app yet."""
    email = get_email()
    hhid = _hh()
    if not email and not hhid:
        return jsonify({"notifications": []})
        
    db = get_db()
    try:
        rows = db.execute(
            """SELECT id, public_title, public_description, public_type, status, 
                      build_number, resolution_note, resolved_at, acknowledged_at
               FROM app_feedback
               WHERE (user_email = %s OR household_id = %s)
                 AND status = 'resolved'
                 AND acknowledged_at IS NULL
               ORDER BY resolved_at DESC NULLS LAST
               LIMIT 5""",
            (email, hhid)
        ).fetchall()
        return jsonify({"notifications": [_serialize_feedback(r) for r in rows]})
    except Exception as e:
        print(f"Error fetching unacknowledged feedback: {e}")
        return jsonify({"notifications": []}), 500
    finally:
        close_db(db)

@app.route("/api/feedback/<int:fb_id>/acknowledge", methods=["POST"])
@require_user
def acknowledge_feedback_resolution(fb_id):
    """Mark a resolved feedback notification as acknowledged by the user."""
    email = get_email()
    hhid = _hh()
    is_adm = is_admin_user()
    
    db = get_db()
    try:
        if is_adm:
            db.execute("UPDATE app_feedback SET acknowledged_at = NOW() WHERE id = %s", (fb_id,))
        else:
            db.execute(
                "UPDATE app_feedback SET acknowledged_at = NOW() WHERE id = %s AND (user_email = %s OR household_id = %s)",
                (fb_id, email, hhid)
            )
        db.commit()
        return jsonify({"ok": True})
    except Exception as e:
        print(f"Error acknowledging feedback #{fb_id}: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        close_db(db)

@app.route("/api/requests", methods=["GET"])
def get_public_requests():
    """Public roadmap / requests list (no PII, filtered to public items)."""
    db = get_db()
    try:
        rows = db.execute(
            """SELECT id, public_title, public_description, public_type, status, 
                      build_number, resolution_note, created_at, resolved_at
               FROM app_feedback
               WHERE is_public = TRUE
               ORDER BY 
                 CASE 
                   WHEN status = 'in_progress' THEN 1 
                   WHEN status = 'planned' THEN 2 
                   WHEN status = 'resolved' THEN 3 
                   ELSE 4 
                 END, 
                 resolved_at DESC NULLS LAST, 
                 created_at DESC"""
        ).fetchall()
        data = [_serialize_feedback(r) for r in rows]
        return jsonify({"requests": data})
    except Exception as e:
        print(f"Error fetching public requests: {e}")
        return jsonify({"requests": []}), 500
    finally:
        close_db(db)

@app.route("/api/requests/<int:req_id>", methods=["GET"])
def get_public_request_detail(req_id):
    """Public request detail for a specific item (or admin preview)."""
    db = get_db()
    try:
        is_adm = is_admin_user()
        if is_adm:
            row = db.execute(
                """SELECT id, public_title, public_description, public_type, status, 
                          build_number, resolution_note, created_at, resolved_at, is_public,
                          user_name, user_email, message, feedback_type, rating, github_issue, notified_at
                   FROM app_feedback
                   WHERE id = %s""", (req_id,)
            ).fetchone()
        else:
            row = db.execute(
                """SELECT id, public_title, public_description, public_type, status, 
                          build_number, resolution_note, created_at, resolved_at
                   FROM app_feedback
                   WHERE id = %s AND is_public = TRUE""", (req_id,)
            ).fetchone()
        if not row:
            return jsonify({"error": "Request not found"}), 404
        return jsonify({"request": _serialize_feedback(row)})
    except Exception as e:
        print(f"Error fetching request detail: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        close_db(db)

# ── Admin Feedback Management (venragh@gmail.com only) ──────

@app.route("/api/admin/feedback", methods=["GET"])
@require_admin
def admin_get_feedback():
    """List all app feedback items for admin triage."""
    db = get_db()
    try:
        rows = db.execute(
            """SELECT id, household_id, user_email, user_name, feedback_type, rating, 
                      message, status, is_public, public_title, public_description, 
                      public_type, build_number, resolution_note, github_issue, 
                      created_at, resolved_at, notified_at
               FROM app_feedback
               ORDER BY created_at DESC"""
        ).fetchall()
        return jsonify({"feedback": [_serialize_feedback(r) for r in rows]})
    except Exception as e:
        print(f"Admin feedback fetch error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        close_db(db)

@app.route("/api/admin/feedback/<int:fb_id>/sanitize", methods=["GET", "POST"])
@require_admin
def admin_sanitize_feedback(fb_id):
    """Use AI & Rule-based PII scrubber to convert raw feedback into clean, anonymized roadmap title & description."""
    db = get_db()
    try:
        row = db.execute("SELECT * FROM app_feedback WHERE id = %s", (fb_id,)).fetchone()
        if not row:
            return jsonify({"error": "Feedback not found"}), 404
        
        sanitized = pii_sanitizer.sanitize_and_synthesize_feedback(
            raw_message=row.get("message", ""),
            user_name=row.get("user_name", ""),
            user_email=row.get("user_email", ""),
            feedback_type=row.get("feedback_type", "feature")
        )
        return jsonify({"ok": True, "sanitized": sanitized})
    except Exception as e:
        print(f"Admin sanitize feedback error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        close_db(db)

@app.route("/api/admin/feedback/sanitize-text", methods=["POST"])
@require_admin
def admin_sanitize_text():
    """Sanitize arbitrary user text to strip names/PII and generate clean product roadmap representation."""
    data = request.get_json() or {}
    raw_text = data.get("text", "").strip()
    user_name = data.get("user_name", "").strip()
    user_email = data.get("user_email", "").strip()
    f_type = data.get("type", "feature").strip()
    sanitized = pii_sanitizer.sanitize_and_synthesize_feedback(
        raw_message=raw_text,
        user_name=user_name,
        user_email=user_email,
        feedback_type=f_type
    )
    return jsonify({"ok": True, "sanitized": sanitized})

@app.route("/api/admin/feedback/<int:fb_id>/triage", methods=["POST"])
@require_admin
def admin_triage_feedback(fb_id):
    """Promote feedback into a public feature request or bug report."""
    data = request.get_json() or {}
    public_title = data.get("public_title", "").strip()
    public_description = data.get("public_description", "").strip()
    public_type = data.get("public_type", "feature").strip().lower()
    status = data.get("status", "planned").strip().lower()
    github_issue = data.get("github_issue")
    if github_issue:
        try: github_issue = int(github_issue)
        except: github_issue = None
    
    if not public_title:
        return jsonify({"error": "Public title is required"}), 400
    if public_type not in ["feature", "bug", "enhancement"]:
        public_type = "feature"
    if status not in ["planned", "in_progress", "resolved", "open", "dismissed"]:
        status = "planned"
    
    db = get_db()
    try:
        current = db.execute("SELECT * FROM app_feedback WHERE id = %s", (fb_id,)).fetchone()
        u_name = current.get("user_name", "") if current else ""
        u_email = current.get("user_email", "") if current else ""
        
        # Guardrail: clean PII from public title and description
        clean_title = pii_sanitizer.clean_text_pii_rule_based(public_title, user_name=u_name, user_email=u_email)
        clean_desc = pii_sanitizer.clean_text_pii_rule_based(public_description, user_name=u_name, user_email=u_email)
        if not clean_title:
            clean_title = public_title

        db.execute(
            """UPDATE app_feedback 
               SET is_public = TRUE, 
                   public_title = %s, 
                   public_description = %s, 
                   public_type = %s, 
                   status = %s, 
                   github_issue = %s
               WHERE id = %s""",
            (clean_title, clean_desc, public_type, status, github_issue, fb_id)
        )
        db.commit()
        updated = db.execute("SELECT * FROM app_feedback WHERE id = %s", (fb_id,)).fetchone()
        return jsonify({"ok": True, "feedback": _serialize_feedback(updated)})
    except Exception as e:
        print(f"Admin triage error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        close_db(db)

@app.route("/api/admin/feedback/<int:fb_id>/status", methods=["POST"])
@require_admin
def admin_update_feedback_status(fb_id):
    """Update status of a feedback item (e.g. planned, in_progress, dismissed)."""
    data = request.get_json() or {}
    status = data.get("status", "").strip().lower()
    if status not in ["open", "planned", "in_progress", "resolved", "dismissed"]:
        return jsonify({"error": "Invalid status"}), 400
    
    db = get_db()
    try:
        db.execute("UPDATE app_feedback SET status = %s WHERE id = %s", (status, fb_id))
        db.commit()
        updated = db.execute("SELECT * FROM app_feedback WHERE id = %s", (fb_id,)).fetchone()
        return jsonify({"ok": True, "feedback": _serialize_feedback(updated)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        close_db(db)

@app.route("/api/admin/feedback/<int:fb_id>/resolve", methods=["POST"])
@require_admin
def admin_resolve_feedback(fb_id):
    """Mark feedback as resolved with Build Number, customer note, and trigger email."""
    data = request.get_json() or {}
    build_number = str(data.get("build_number", "")).strip()
    resolution_note = str(data.get("resolution_note", "")).strip()
    public_title = str(data.get("public_title", "")).strip()
    public_description = str(data.get("public_description", "")).strip()
    send_email = data.get("send_email", True)
    
    if not build_number:
        return jsonify({"error": "Build Number is required"}), 400
    
    db = get_db()
    try:
        current = db.execute("SELECT * FROM app_feedback WHERE id = %s", (fb_id,)).fetchone()
        if not current:
            return jsonify({"error": "Feedback not found"}), 404
            
        u_name = current.get("user_name", "")
        u_email = current.get("user_email", "")

        # If title/desc are missing, synthesize them via PII sanitizer instead of using raw message
        p_title = public_title or current.get("public_title")
        p_desc = public_description or current.get("public_description")
        
        if not p_title or not p_desc:
            synthesized = pii_sanitizer.sanitize_and_synthesize_feedback(
                raw_message=current.get("message", ""),
                user_name=u_name,
                user_email=u_email,
                feedback_type=current.get("feedback_type", "feature")
            )
            if not p_title:
                p_title = synthesized["public_title"]
            if not p_desc:
                p_desc = synthesized["public_description"]

        # Ensure all fields are PII-scrubbed before saving
        p_title = pii_sanitizer.clean_text_pii_rule_based(p_title, user_name=u_name, user_email=u_email)
        p_desc = pii_sanitizer.clean_text_pii_rule_based(p_desc, user_name=u_name, user_email=u_email)
        res_note_clean = pii_sanitizer.clean_text_pii_rule_based(resolution_note, user_name=u_name, user_email=u_email)
        
        db.execute(
            """UPDATE app_feedback 
               SET status = 'resolved', 
                   is_public = TRUE, 
                   build_number = %s, 
                   resolution_note = %s, 
                   public_title = %s, 
                   public_description = %s, 
                   resolved_at = NOW() 
               WHERE id = %s""",
            (build_number, res_note_clean, p_title, p_desc, fb_id)
        )
        db.commit()
        
        email_sent = False
        if send_email and current.get("user_email"):
            import email_helper
            recipient_email = current["user_email"].strip()
            recipient_name = current.get("user_name") or ""
            req_url = f"https://grocerlist.app/requests/{fb_id}"
            
            email_sent = email_helper.send_feedback_resolved_email(
                to_email=recipient_email,
                user_name=recipient_name,
                feedback_title=p_title,
                feedback_id=fb_id,
                build_number=build_number,
                resolution_note=res_note_clean,
                request_url=req_url
            )
            if email_sent:
                db.execute("UPDATE app_feedback SET notified_at = NOW() WHERE id = %s", (fb_id,))
                db.commit()
                
        updated = db.execute("SELECT * FROM app_feedback WHERE id = %s", (fb_id,)).fetchone()
        return jsonify({
            "ok": True, 
            "feedback": _serialize_feedback(updated), 
            "email_sent": email_sent
        })
    except Exception as e:
        print(f"Admin resolve feedback error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        close_db(db)

@app.route("/api/webhooks/revenuecat", methods=["POST"])
def revenuecat_webhook():
    """Handle RevenueCat webhooks for cross-platform (iOS, Android, Web/Stripe) subscriptions."""
    expected_token = os.environ.get("REVENUECAT_WEBHOOK_SECRET")
    if expected_token:
        auth_header = request.headers.get("Authorization")
        if auth_header not in [expected_token, f"Bearer {expected_token}"]:
            return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    event = data.get("event", {})
    evt_type = event.get("type")
    uid = event.get("app_user_id")

    print(f"[Webhook] Processing {evt_type} for app_user_id: {uid}")
    hhid = _find_household_id_from_uid(uid, event)

    if not hhid:
        print(f"[Webhook] Could not resolve household_id for uid: {uid}, aliases: {event.get('aliases')}")
        return jsonify({"ok": True, "warning": "Household not found"})

    exp_ms = event.get("expiration_at_ms")
    exp_clause = ""
    exp_args = []
    if exp_ms:
        exp_clause = ", subscription_ends_at = TO_TIMESTAMP(?)"
        exp_args = [int(exp_ms) / 1000.0]

    if evt_type == "CANCELLATION":
        authmod._run(f"UPDATE {authmod._HH} SET subscription_status = ? {exp_clause} WHERE id = ?", ("canceled", *exp_args, hhid))
        print(f"[Webhook] Marked household {hhid} as canceled")

    elif evt_type == "EXPIRATION":
        authmod._run(f"UPDATE {authmod._HH} SET is_premium = ?, subscription_status = ? {exp_clause} WHERE id = ?", (False, "expired", *exp_args, hhid))
        print(f"[Webhook] Downgraded household {hhid} due to expiration")

    elif evt_type == "TRANSFER":
        transferred_from = event.get("transferred_from", [])
        if isinstance(transferred_from, list):
            old_hhid = None
            for cand in transferred_from:
                old_hhid = old_hhid or _find_household_id_from_uid(str(cand))
            if old_hhid:
                # Explicitly set downgraded_at to NOW() just in case the trigger doesn't fire (e.g. if is_premium was already false)
                authmod._run(f"UPDATE {authmod._HH} SET is_premium = ?, subscription_status = ?, downgraded_at = NOW() WHERE id = ?", (False, "expired", old_hhid))
                print(f"[Webhook] Downgraded old household {old_hhid} due to TRANSFER")
        
        if hhid:
            # TRANSFER events usually don't have expiration_at_ms, so we copy it from the old household
            if old_hhid and not exp_clause:
                authmod._run(f"UPDATE {authmod._HH} SET is_premium = ?, subscription_status = ?, subscription_ends_at = (SELECT subscription_ends_at, owner_id FROM {authmod._HH} WHERE id = ?), trial_ends_at = (SELECT trial_ends_at FROM {authmod._HH} WHERE id = ?) WHERE id = ?", (True, "active", old_hhid, old_hhid, hhid))
            else:
                authmod._run(f"UPDATE {authmod._HH} SET is_premium = ?, subscription_status = ? {exp_clause} WHERE id = ?", (True, "active", *exp_args, hhid))
            print(f"[Webhook] Upgraded new household {hhid} due to TRANSFER")

    elif evt_type in ["INITIAL_PURCHASE", "RENEWAL", "UNCANCELLATION", "NON_RENEWING_PURCHASE", "PRODUCT_CHANGE"]:
        authmod._run(f"UPDATE {authmod._HH} SET is_premium = ?, subscription_status = ? {exp_clause} WHERE id = ?", (True, "active", *exp_args, hhid))
        print(f"[Webhook] Upgraded household {hhid} due to {evt_type}")

    return jsonify({"ok": True})


@app.route("/api/webhooks/stripe", methods=["POST"])
def stripe_webhook():
    """Handle Stripe webhooks directly for web billing, bypassing RevenueCat."""
    data = request.get_json(silent=True) or {}
    event_type = data.get("type")
    
    try:
        with open("/tmp/stripe_webhook.log", "a") as logf:
            logf.write(f"\n--- EVENT: {event_type} ---\n")
            import json
            logf.write(json.dumps(data) + "\n")
    except Exception:
        pass
        
    print(f"[Stripe Webhook] Received event: {event_type}")
    
    if event_type == "checkout.session.completed":
        session_obj = data.get("data", {}).get("object", {})
        
        # Extract from metadata we set during checkout creation
        metadata = session_obj.get("metadata", {})
        hhid = metadata.get("household_id")
        uid = metadata.get("app_user_id") or session_obj.get("client_reference_id")
        customer_id = session_obj.get("customer")
        subscription_id = session_obj.get("subscription")
        
        if not hhid and uid:
            hhid = _find_household_id_from_uid(uid)
            
        if hhid:
            current_period_end = None
            if subscription_id:
                try:
                    import urllib.request, json, os
                    stripe_secret = os.environ.get("STRIPE_SECRET_KEY")
                    if stripe_secret:
                        req = urllib.request.Request(
                            f"https://api.stripe.com/v1/subscriptions/{subscription_id}",
                            headers={"Authorization": f"Bearer {stripe_secret}"}
                        )
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            sub_data = json.loads(resp.read().decode("utf-8"))
                            current_period_end = sub_data.get("current_period_end")
                            if not current_period_end:
                                items_data = sub_data.get("items", {}).get("data", [])
                                if items_data:
                                    current_period_end = items_data[0].get("current_period_end")
                except Exception as e:
                    print(f"Error fetching subscription {subscription_id}: {e}")
            
            if customer_id:
                if current_period_end:
                    authmod._run(f"UPDATE {authmod._HH} SET is_premium = True, subscription_status = 'active', stripe_customer_id = ?, subscription_ends_at = TO_TIMESTAMP(?) WHERE id = ?", (customer_id, current_period_end, hhid))
                else:
                    authmod._run(f"UPDATE {authmod._HH} SET is_premium = True, subscription_status = 'active', stripe_customer_id = ? WHERE id = ?", (customer_id, hhid))
            else:
                authmod._run(f"UPDATE {authmod._HH} SET is_premium = True, subscription_status = 'active' WHERE id = ?", (hhid,))
            print(f"[Stripe Webhook] Upgraded household {hhid} due to checkout.session.completed")
        else:
            print(f"[Stripe Webhook] Could not resolve household_id for uid: {uid}")

    elif event_type in ["customer.subscription.updated", "customer.subscription.created"]:
        sub_obj = data.get("data", {}).get("object", {})
        customer_id = sub_obj.get("customer")
        status = sub_obj.get("status")
        current_period_end = sub_obj.get("current_period_end")
        if not current_period_end:
            items_data = sub_obj.get("items", {}).get("data", [])
            if items_data:
                current_period_end = items_data[0].get("current_period_end")
        cancel_at_period_end = sub_obj.get("cancel_at_period_end")
        canceled_at = sub_obj.get("canceled_at")
        cancel_at = sub_obj.get("cancel_at")
        
        metadata = sub_obj.get("metadata", {})
        hhid = metadata.get("household_id")
        
        print(f"[Stripe Webhook] Received subscription {event_type} for customer: {customer_id}, status: {status}, cancel_at_period_end: {cancel_at_period_end}, canceled_at: {canceled_at}, hhid: {hhid}")
        
        if customer_id:
            # Fix logic: they are premium if active/trialing, regardless of cancel_at_period_end
            is_premium = True if status in ["active", "trialing"] else False
            is_canceled = bool(cancel_at_period_end or canceled_at or cancel_at)
            db_status = "canceled" if is_canceled else status
            
            # Use hhid if available (for robustness if customer_id not yet linked)
            if hhid:
                if current_period_end:
                    authmod._run(f"UPDATE {authmod._HH} SET is_premium = ?, subscription_status = ?, subscription_ends_at = TO_TIMESTAMP(?), stripe_customer_id = ? WHERE id = ?", (is_premium, db_status, current_period_end, customer_id, hhid))
                else:
                    authmod._run(f"UPDATE {authmod._HH} SET is_premium = ?, subscription_status = ?, stripe_customer_id = ? WHERE id = ?", (is_premium, db_status, customer_id, hhid))
            else:
                if current_period_end:
                    authmod._run(f"UPDATE {authmod._HH} SET is_premium = ?, subscription_status = ?, subscription_ends_at = TO_TIMESTAMP(?) WHERE stripe_customer_id = ?", (is_premium, db_status, current_period_end, customer_id))
                else:
                    authmod._run(f"UPDATE {authmod._HH} SET is_premium = ?, subscription_status = ? WHERE stripe_customer_id = ?", (is_premium, db_status, customer_id))

    elif event_type == "customer.subscription.deleted":
        sub_obj = data.get("data", {}).get("object", {})
        customer_id = sub_obj.get("customer")
        print(f"[Stripe Webhook] Received subscription deleted for customer: {customer_id}")
        if customer_id:
            authmod._run(f"UPDATE {authmod._HH} SET is_premium = False, subscription_status = 'canceled', subscription_ends_at = NOW() WHERE stripe_customer_id = ?", (customer_id,))
            print(f"[Stripe Webhook] Downgraded household with Stripe customer {customer_id}")
            
    return jsonify({"ok": True})


def _verify_sendgrid_signature(raw_payload: bytes, signature: str, timestamp: str, public_key_b64: str) -> bool:
    """Verify SendGrid Signed Event Webhook ECDSA signature."""
    if not signature or not timestamp or not public_key_b64:
        return False

    # 1. Try SendGrid official SDK
    try:
        from sendgrid.helpers.eventwebhook import EventWebhook
        ew = EventWebhook()
        key = ew.convert_public_key_to_ecdsa(public_key_b64.strip())
        payload_str = raw_payload.decode("utf-8", errors="replace")
        if ew.verify_signature(payload_str, signature.strip(), timestamp.strip(), key):
            return True
    except Exception:
        pass

    # 2. Try standard cryptography library
    try:
        import base64
        from cryptography.hazmat.primitives.serialization import load_der_public_key
        from cryptography.hazmat.primitives.asymmetric import ec, utils
        from cryptography.hazmat.primitives import hashes

        pub_der = base64.b64decode(public_key_b64.strip())
        pub_key = load_der_public_key(pub_der)
        sig_bytes = base64.b64decode(signature.strip())
        data_to_verify = timestamp.strip().encode("utf-8") + raw_payload

        try:
            pub_key.verify(sig_bytes, data_to_verify, ec.ECDSA(hashes.SHA256()))
            return True
        except Exception:
            if len(sig_bytes) == 64:
                r = int.from_bytes(sig_bytes[:32], byteorder="big")
                s = int.from_bytes(sig_bytes[32:], byteorder="big")
                der_sig = utils.encode_dss_signature(r, s)
                pub_key.verify(der_sig, data_to_verify, ec.ECDSA(hashes.SHA256()))
                return True
    except Exception as e:
        print(f"[SendGrid Webhook] ECDSA signature check exception: {e}")

    return False


@app.route("/api/webhooks/sendgrid", methods=["POST"])
def sendgrid_webhook():
    """Handle SendGrid Event Webhook for real-time delivery, open, click, bounce, etc."""
    # 1. Cryptographic Signature Verification (SendGrid Signed Event Webhooks)
    verification_key = os.environ.get("SENDGRID_WEBHOOK_VERIFICATION_KEY")
    if verification_key:
        signature = request.headers.get("X-Twilio-Email-Event-Webhook-Signature") or request.headers.get("X-Sendgrid-Event-Webhook-Signature", "")
        timestamp = request.headers.get("X-Twilio-Email-Event-Webhook-Timestamp") or request.headers.get("X-Sendgrid-Event-Webhook-Timestamp", "")
        raw_body = request.get_data()
        if not signature or not timestamp or not _verify_sendgrid_signature(raw_body, signature, timestamp, verification_key):
            print("[SendGrid Webhook] Signature verification failed or missing signature/timestamp headers.")
            return jsonify({"error": "Invalid webhook signature"}), 401
    else:
        # 2. Secret Token / Bearer fallback (if configured)
        expected_token = os.environ.get("SENDGRID_WEBHOOK_SECRET")
        if expected_token:
            auth_header = request.headers.get("Authorization", "")
            token_param = request.args.get("token", "")
            if auth_header not in [expected_token, f"Bearer {expected_token}"] and token_param != expected_token:
                return jsonify({"error": "Unauthorized"}), 401

    events = request.get_json(silent=True)
    if not events:
        return jsonify({"ok": True, "processed": 0})

    if isinstance(events, dict):
        events = [events]

    processed_count = 0
    import datetime
    for ev in events:
        if not isinstance(ev, dict):
            continue

        email = ev.get("email")
        event_type = ev.get("event")
        if not email or not event_type:
            continue

        campaign = ev.get("campaign")
        if not campaign:
            cat = ev.get("category")
            if isinstance(cat, list) and cat:
                campaign = cat[0]
            elif isinstance(cat, str):
                campaign = cat

        user_id = ev.get("user_id")
        household_id = ev.get("household_id")

        try:
            user_id = int(user_id) if user_id is not None and str(user_id).isdigit() else None
        except (ValueError, TypeError):
            user_id = None

        try:
            household_id = int(household_id) if household_id is not None and str(household_id).isdigit() else None
        except (ValueError, TypeError):
            household_id = None

        # 1. Resolve user and household by email first
        db_user = None
        try:
            db_user = authmod._one("SELECT id, household_id FROM auth_users WHERE LOWER(email) = LOWER(%s) LIMIT 1", (email,))
        except Exception:
            pass

        if db_user:
            user_id = db_user.get("id")
            household_id = db_user.get("household_id")
        else:
            # If no user matches email, verify if supplied user_id exists in auth_users
            if user_id:
                try:
                    exists = authmod._one("SELECT id, household_id FROM auth_users WHERE id = %s LIMIT 1", (user_id,))
                    if not exists:
                        user_id = None
                    elif not household_id:
                        household_id = exists.get("household_id")
                except Exception:
                    user_id = None

        # 2. Verify that household_id exists in auth_households to prevent FK violations
        if household_id:
            try:
                hh_exists = authmod._one("SELECT id FROM auth_households WHERE id = %s LIMIT 1", (household_id,))
                if not hh_exists:
                    household_id = None
            except Exception:
                household_id = None

        target_url = ev.get("url")
        user_agent = ev.get("useragent")
        ip_address = ev.get("ip")
        sg_event_id = ev.get("sg_event_id")
        sg_message_id = ev.get("sg_message_id")
        reason = ev.get("reason") or ev.get("response") or ev.get("status")
        
        ts_val = ev.get("timestamp")
        event_timestamp = None
        if ts_val:
            try:
                event_timestamp = datetime.datetime.fromtimestamp(int(ts_val), tz=datetime.timezone.utc)
            except Exception:
                event_timestamp = None

        insert_sql = """
            INSERT INTO email_events (
                email, event_type, campaign, user_id, household_id,
                target_url, user_agent, ip_address, sg_event_id, sg_message_id,
                reason, event_timestamp, created_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, COALESCE(%s, NOW()), NOW()
            )
            ON CONFLICT (sg_event_id) DO NOTHING
        """
        try:
            authmod._run(insert_sql, (
                email, event_type, campaign, user_id, household_id,
                target_url, user_agent, ip_address, sg_event_id, sg_message_id,
                reason, event_timestamp
            ))
            processed_count += 1
        except Exception as e:
            # Fallback without FK relations if constraint error occurred
            try:
                authmod._run(insert_sql, (
                    email, event_type, campaign, None, None,
                    target_url, user_agent, ip_address, sg_event_id, sg_message_id,
                    reason, event_timestamp
                ))
                processed_count += 1
            except Exception as e2:
                print(f"[SendGrid Webhook] Error inserting event {sg_event_id}: {e2}")

        # Automated suppression and opt-out handling
        ev_type_lower = (event_type or "").strip().lower()
        if ev_type_lower in ("bounce", "dropped", "spamreport", "unsubscribe", "group_unsubscribe"):
            try:
                authmod.suppress_email(
                    email=email,
                    reason=ev_type_lower,
                    sg_event_id=sg_event_id,
                    details=str(reason or ev.get("status") or "")
                )
                print(f"[SendGrid Webhook] Suppressed {email} due to event '{ev_type_lower}'")
            except Exception as se:
                print(f"[SendGrid Webhook] Error suppressing {email}: {se}")
        elif ev_type_lower == "group_resubscribe":
            try:
                authmod.unsuppress_email(email=email)
                print(f"[SendGrid Webhook] Unsuppressed {email} due to 'group_resubscribe'")
            except Exception as ue:
                print(f"[SendGrid Webhook] Error unsuppressing {email}: {ue}")

    return jsonify({"ok": True, "processed": processed_count})



def _fetch_stripe_plans():
    stripe_secret = os.environ.get("STRIPE_SECRET_KEY")
    if not stripe_secret:
        return None
    if stripe_secret.startswith("pk_"):
        return {"error": "STRIPE_SECRET_KEY is configured with a Publishable Key (pk_***). You must use your Secret Key (sk_***) from the Stripe Dashboard."}
    try:
        url = "https://api.stripe.com/v1/prices?active=true&expand[]=data.product&limit=20"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {stripe_secret}",
                "Accept": "application/json"
            }
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            prices = data.get("data", [])
            plans = []
            for p in prices:
                if p.get("type") != "recurring":
                    continue
                prod = p.get("product", {})
                if not isinstance(prod, dict):
                    prod = {}
                unit_cents = p.get("unit_amount", 0) or 0
                unit_val = unit_cents / 100.0
                currency = (p.get("currency") or "usd").upper()
                symbol = "$" if currency == "USD" else f"{currency} "
                interval = p.get("recurring", {}).get("interval", "month")
                interval_label = "yr" if interval == "year" else "mo"
                pkg_type = "yearly" if interval == "year" else "monthly"
                name = prod.get("name") or f"ListMate Premium ({'Annual' if pkg_type == 'yearly' else 'Monthly'})"
                desc = prod.get("description") or "Unlock AI Recipe Planner, meal generator & smart store mapping."
                plans.append({
                    "id": p.get("id"),
                    "price_id": p.get("id"),
                    "package_type": pkg_type,
                    "name": name,
                    "description": desc,
                    "price_string": f"{symbol}{unit_val:.2f} / {interval_label}",
                    "amount": unit_val,
                    "currency": currency,
                    "interval": interval
                })
            env_monthly = os.environ.get("STRIPE_PRICE_MONTHLY")
            env_yearly = os.environ.get("STRIPE_PRICE_YEARLY")
            
            if env_monthly and not (env_monthly.startswith("price_") or env_monthly.startswith("plan_")):
                env_monthly = None
            if env_yearly and not (env_yearly.startswith("price_") or env_yearly.startswith("plan_")):
                env_yearly = None
                
            final_plans = []
            seen_types = set()
            for p in plans:
                ptype = p["package_type"]
                pid = p["id"]
                if ptype == "monthly" and env_monthly and pid != env_monthly:
                    continue
                if ptype == "yearly" and env_yearly and pid != env_yearly:
                    continue
                if ptype not in seen_types:
                    seen_types.add(ptype)
                    final_plans.append(p)
            
            final_plans.sort(key=lambda x: 0 if x["package_type"] == "monthly" else 1)
            if not final_plans and plans:
                # Fallback: if they had active prices but none matched the environment variables, just take the first ones we found
                for p in plans:
                    if p["package_type"] not in seen_types:
                        seen_types.add(p["package_type"])
                        final_plans.append(p)
                final_plans.sort(key=lambda x: 0 if x["package_type"] == "monthly" else 1)
                
            if not final_plans:
                return {"error": "No active recurring prices (subscriptions) were found in your Stripe account. Please ensure you have created Products with recurring Prices and marked them as active."}
            return final_plans
    except Exception as e:
        err_str = str(e)
        if hasattr(e, 'read'):
            err_str += " " + e.read().decode('utf-8')
        print(f"[Stripe API] Error fetching prices: {err_str}")
        return {"error": f"Stripe API Error: {err_str}"}


def _fetch_revenuecat_plans():
    rc_key = os.environ.get("REVENUECAT_PUBLIC_KEY") or os.environ.get("REVENUECAT_SECRET_KEY")
    if not rc_key:
        return None
    try:
        url = "https://api.revenuecat.com/v1/subscribers/default/offerings"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {rc_key}",
                "Accept": "application/json",
                "X-Platform": "android"
            }
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            offerings = data.get("offerings", [])
            plans = []
            for off in offerings:
                for pkg in off.get("packages", []):
                    pkg_id = pkg.get("identifier", "")
                    plan_type = "yearly" if ("annual" in pkg_id.lower() or "year" in pkg_id.lower()) else "monthly"
                    prod_id = pkg.get("platform_product_identifier", "listmate_premium")
                    plan_id = pkg.get("platform_product_plan_identifier", plan_type)
                    label = "Annual" if plan_type == "yearly" else "Monthly"
                    
                    default_price = "$29.99 / yr" if plan_type == "yearly" else "$2.99 / mo"
                    env_price = os.environ.get(f"STRIPE_PRICE_{plan_type.upper()}_AMOUNT") or os.environ.get(f"PLAN_{plan_type.upper()}_PRICE")
                    price_str = f"${env_price}" if env_price else default_price

                    plans.append({
                        "id": pkg_id,
                        "price_id": pkg_id,
                        "package_type": plan_type,
                        "name": f"ListMate Premium ({label})",
                        "description": "Unlock AI Recipe Planner, meal generator & smart store mapping.",
                        "price_string": price_str,
                        "product_id": prod_id,
                        "plan_id": plan_id
                    })
            return plans if plans else None
    except Exception as e:
        print(f"[RevenueCat API] Error fetching offerings: {e}")
        return None


@app.route("/api/billing/plans", methods=["GET"])
def billing_plans():
    """Retrieve active subscription plans dynamically from Stripe API, RevenueCat, or environment configuration."""
    stripe_secret = os.environ.get("STRIPE_SECRET_KEY")
    if stripe_secret:
        stripe_plans = _fetch_stripe_plans()
        if stripe_plans and isinstance(stripe_plans, list):
            return jsonify({"ok": True, "source": "stripe_api", "plans": stripe_plans})
        elif isinstance(stripe_plans, dict) and "error" in stripe_plans:
            return jsonify({"ok": False, "error": stripe_plans["error"]})
            
    stripe_plans = _fetch_stripe_plans()
    if stripe_plans and isinstance(stripe_plans, list):
        return jsonify({"ok": True, "source": "stripe_api", "plans": stripe_plans})

    rc_plans = _fetch_revenuecat_plans()
    if rc_plans:
        return jsonify({"ok": True, "source": "revenuecat_api", "plans": rc_plans})

    monthly_price = os.environ.get("STRIPE_PRICE_MONTHLY_AMOUNT") or os.environ.get("PLAN_MONTHLY_PRICE") or "2.99"
    yearly_price = os.environ.get("STRIPE_PRICE_YEARLY_AMOUNT") or os.environ.get("PLAN_YEARLY_PRICE") or "29.99"
    monthly_title = os.environ.get("STRIPE_PRICE_MONTHLY_TITLE") or "Monthly Plan"
    yearly_title = os.environ.get("STRIPE_PRICE_YEARLY_TITLE") or "Annual Plan"

    monthly_id = os.environ.get("STRIPE_PRICE_MONTHLY") or "monthly"
    yearly_id = os.environ.get("STRIPE_PRICE_YEARLY") or "yearly"

    default_plans = [
        {
            "id": monthly_id,
            "price_id": monthly_id,
            "package_type": "monthly",
            "name": monthly_title,
            "price_string": f"${monthly_price} / mo",
            "description": "Billed monthly. Cancel anytime in Stripe Customer Portal."
        },
        {
            "id": yearly_id,
            "price_id": yearly_id,
            "package_type": "yearly",
            "name": yearly_title,
            "price_string": f"${yearly_price} / yr",
            "description": "Save on annual subscription! Billed annually."
        }
    ]
    return jsonify({"ok": True, "source": "default", "plans": default_plans})


@app.route("/api/billing/checkout", methods=["GET", "POST"])
@require_user
def billing_checkout():
    """Generate or retrieve a Web Billing checkout URL for RevenueCat / Stripe."""
    hhid = _hh()
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    pkg_type = request.args.get("package") or request.args.get("price_id") or "monthly"
    if request.is_json and request.get_json(silent=True):
        data = request.get_json()
        pkg_type = data.get("price_id") or data.get("package") or pkg_type

    host_url = request.host_url.rstrip("/")
    if "localhost" not in host_url and "127.0.0.1" not in host_url and host_url.startswith("http://"):
        host_url = host_url.replace("http://", "https://")
    success_redirect = f"{host_url}/settings?purchase=success"
    cancel_redirect = f"{host_url}/settings?purchase=cancel"

    stripe_secret = os.environ.get("STRIPE_SECRET_KEY")
    if stripe_secret and stripe_secret.startswith("pk_"):
        return jsonify({"error": "Configuration Error: STRIPE_SECRET_KEY is set to a Publishable Key (pk_***). Please use the Secret Key (sk_***)."}), 400
        
    # Map non-Stripe package types (like '$rc_monthly', 'monthly', 'yearly') to Stripe price IDs if possible
    if stripe_secret and not (pkg_type.startswith("price_") or pkg_type.startswith("plan_")):
        is_yearly = "year" in pkg_type.lower() or "annual" in pkg_type.lower()
        mapped_price = os.environ.get("STRIPE_PRICE_YEARLY") if is_yearly else os.environ.get("STRIPE_PRICE_MONTHLY")
        
        if mapped_price and not (mapped_price.startswith("price_") or mapped_price.startswith("plan_")):
            mapped_price = None
            
        if not mapped_price:
            stripe_plans = _fetch_stripe_plans()
            if stripe_plans:
                for p in stripe_plans:
                    if (is_yearly and p["package_type"] == "yearly") or (not is_yearly and p["package_type"] == "monthly"):
                        mapped_price = p["price_id"]
                        break
        
        if mapped_price:
            pkg_type = mapped_price

    if stripe_secret and (pkg_type.startswith("price_") or pkg_type.startswith("plan_")):
        try:
            url = "https://api.stripe.com/v1/checkout/sessions"
            body_params = {
                "mode": "subscription",
                "payment_method_types[0]": "card",
                "line_items[0][price]": pkg_type,
                "line_items[0][quantity]": "1",
                "client_reference_id": str(user_id),
                "metadata[household_id]": str(hhid),
                "metadata[app_user_id]": str(user_id),
                "subscription_data[metadata][household_id]": str(hhid),
                "subscription_data[metadata][app_user_id]": str(user_id),
                "success_url": success_redirect,
                "cancel_url": cancel_redirect,
            }
            encoded_body = urllib.parse.urlencode(body_params).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=encoded_body,
                headers={
                    "Authorization": f"Bearer {stripe_secret}",
                    "Content-Type": "application/x-www-form-urlencoded"
                }
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                session_data = json.loads(resp.read().decode("utf-8"))
                if session_data.get("url"):
                    return jsonify({"ok": True, "checkout_url": session_data["url"], "price_id": pkg_type})
        except Exception as e:
            print(f"[Stripe Checkout] Error creating session: {e}")

    monthly_url = os.environ.get("REVENUECAT_WEB_BILLING_MONTHLY_URL") or os.environ.get("REVENUECAT_WEB_BILLING_URL") or os.environ.get("STRIPE_CHECKOUT_URL_MONTHLY")
    yearly_url = os.environ.get("REVENUECAT_WEB_BILLING_YEARLY_URL") or os.environ.get("REVENUECAT_WEB_BILLING_URL") or os.environ.get("STRIPE_CHECKOUT_URL_YEARLY")

    target_url = yearly_url if "year" in pkg_type.lower() else monthly_url

    if not target_url:
        if stripe_secret:
            return jsonify({"error": "Failed to create Stripe Checkout session. Please ensure your Stripe API keys and active Products are correctly configured."}), 400
        base_pay_url = os.environ.get("REVENUECAT_WEB_BILLING_BASE_URL", "https://pay.revenuecat.com/listmate-pro")
        target_url = f"{base_pay_url}/{pkg_type}"

    sep = "&" if "?" in target_url else "?"
    checkout_url = f"{target_url}{sep}app_user_id={user_id}&household_id={hhid}&success_url={success_redirect}&cancel_url={cancel_redirect}"

    return jsonify({"ok": True, "checkout_url": checkout_url, "package": pkg_type})


@app.route("/api/billing/portal", methods=["GET", "POST"])
@require_user
def billing_portal():
    """Retrieve Stripe Customer Portal management URL via Stripe API or RevenueCat REST API."""
    user_id = get_user_id()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    hhid = _hh()
    stripe_secret = os.environ.get("STRIPE_SECRET_KEY")
    
    if stripe_secret:
        hh = authmod._one(f"SELECT stripe_customer_id FROM {authmod._HH} WHERE id = ?", (hhid,))
        if hh and hh.get("stripe_customer_id"):
            try:
                import urllib.request, json, urllib.parse
                url = "https://api.stripe.com/v1/billing_portal/sessions"
                
                host_url = request.host_url.rstrip("/")
                if "localhost" not in host_url and "127.0.0.1" not in host_url and host_url.startswith("http://"):
                    host_url = host_url.replace("http://", "https://")
                return_redirect = f"{host_url}/settings"
                
                body_params = {
                    "customer": hh["stripe_customer_id"],
                    "return_url": return_redirect
                }
                encoded_body = urllib.parse.urlencode(body_params).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=encoded_body,
                    headers={
                        "Authorization": f"Bearer {stripe_secret}",
                        "Content-Type": "application/x-www-form-urlencoded"
                    }
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    session_data = json.loads(resp.read().decode("utf-8"))
                    if session_data.get("url"):
                        return jsonify({"ok": True, "portal_url": session_data["url"]})
            except Exception as e:
                err_msg = str(e)
                if hasattr(e, 'read'):
                    err_msg += " " + e.read().decode('utf-8')
                print(f"[Billing Portal] Error creating Stripe portal session: {err_msg}")
                return jsonify({"error": f"Stripe Portal API Error: {err_msg}"}), 400
        else:
            return jsonify({"error": "No Stripe customer ID found for your household. Because you subscribed before this update, you may need to wait for your next billing cycle or contact support."}), 400
    else:
        return jsonify({"error": "STRIPE_SECRET_KEY is not configured on the server."}), 400

    stripe_portal_env = os.environ.get("STRIPE_CUSTOMER_PORTAL_URL") or os.environ.get("STRIPE_PORTAL_URL")
    if stripe_portal_env:
        return jsonify({"ok": True, "portal_url": stripe_portal_env})

    rc_secret = os.environ.get("REVENUECAT_SECRET_KEY")
    if rc_secret:
        try:
            import urllib.request, json
            req_url = f"https://api.revenuecat.com/v1/subscribers/{user_id}/management_url"
            req = urllib.request.Request(
                req_url,
                headers={
                    "Authorization": f"Bearer {rc_secret}",
                    "Accept": "application/json"
                }
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                m_url = res_data.get("management_url")
                if m_url:
                    return jsonify({"ok": True, "portal_url": m_url})
        except Exception as e:
            print(f"[Billing Portal] Error fetching management URL: {e}")

    return jsonify({"error": "No billing portal available. Please contact support."}), 400


@app.route("/api/settings/premium", methods=["GET", "POST"])
@require_user
def premium_settings():
    """Get or set household premium status."""
    hhid = _hh()
    if not hhid:
        return jsonify({"error": "No household"}), 400
    authmod._init_schema()

    if request.method == "GET":
        hh = authmod._one(f"SELECT is_premium, subscription_status, trial_ends_at, subscription_ends_at, owner_id FROM {authmod._HH} WHERE id = ?", (hhid,))
        is_prem = bool(hh.get("is_premium")) if hh else False
        sub_status = hh.get("subscription_status", "free") if hh else "free"
        trial_ends_at = hh.get("trial_ends_at") if hh else None
        if trial_ends_at and hasattr(trial_ends_at, 'isoformat'):
            trial_ends_at = trial_ends_at.isoformat()
            
        sub_ends_at = hh.get("subscription_ends_at") if hh else None
        if sub_ends_at and hasattr(sub_ends_at, 'isoformat'):
            sub_ends_at = sub_ends_at.isoformat()

        is_early = bool(is_prem and sub_status == "premium" and not sub_ends_at)



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

        uid = authmod.get_user_id()
        is_owner = (uid == hh.get("owner_id")) if hh else False
        return jsonify({
            "is_premium": is_prem,
            "household_id": hhid,
            "is_early_adopter": is_early,
            "subscription_status": sub_status,
            "trial_ends_at": trial_ends_at,
            "subscription_ends_at": sub_ends_at,
            "is_owner": is_owner,
            "early_adopter_limit": int(__import__("os").environ.get("EARLY_ADOPTER_LIMIT", 25))
        })

    data = request.get_json(silent=True) or {}
    is_premium = bool(data.get("is_premium", False))
    val = is_premium
    status = "active" if is_premium else "free"
    authmod._run(f"UPDATE {authmod._HH} SET is_premium = ?, subscription_status = ? WHERE id = ?", (val, status, hhid))
    is_early = bool(is_premium and status == "premium")
    
    return jsonify({
        "ok": True,
        "is_premium": is_premium,
        "household_id": hhid,
        "is_early_adopter": is_early
    })




# ── Recipe Planner & AI Recipe Generator (Premium Feature) ──

def _generate_fallback_recipe(prompt, dietary_restrictions=""):
    title = prompt.strip().title()
    diet_tags = [d.strip() for d in dietary_restrictions.split(",") if d.strip()] if dietary_restrictions else ["Homemade"]
    if "Vegetarian" not in diet_tags and any(w in title.lower() for w in ["veg", "paneer", "tofu", "dal", "subzi"]):
        diet_tags.append("Vegetarian")

    return {
        "title": title,
        "description": f"A delicious custom recipe for {title}, tailored for your household.",
        "prep_time": "15 mins",
        "cook_time": "20 mins",
        "servings": "4 servings",
        "dietary_tags": diet_tags,
        "ingredients": [
            {"name": f"Main ingredient for {title}", "amount": "1 lb", "category": "Produce"},
            {"name": "Cooking Oil", "amount": "2 tbsp", "category": "Pantry"},
            {"name": "Garlic", "amount": "1 tbsp, minced", "category": "Produce"},
            {"name": "Onion", "amount": "1 medium, chopped", "category": "Produce"},
            {"name": "Salt", "amount": "to taste", "category": "Spices"},
            {"name": "Black pepper", "amount": "to taste", "category": "Spices"}
        ],
        "instructions": [
            f"Prepare all fresh ingredients for {title}.",
            "Heat cooking oil or butter in a pan over medium heat.",
            "Add aromatics and sauté until fragrant.",
            "Stir in main ingredients and simmer until well blended.",
            "Season to taste, garnish with fresh herbs, and serve warm!"
        ]
    }


def _call_gemini_recipe(prompt, dietary_restrictions=""):
    """Call Gemini API with multi-key discovery, Lite model fallback, and smart recipe generation fallback."""
    key = ""
    for var in ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"]:
        k = os.environ.get(var, "").strip()
        if k and not k.startswith("dev-") and not k.startswith("secret-"):
            key = k
            break
    
    if not key:
        for path in ["/opt/shared/.env", ".env", "/app/applet/.env"]:
            if os.path.exists(path):
                try:
                    for line in open(path):
                        for var in ["GEMINI_API_KEY=", "GOOGLE_API_KEY=", "GOOGLE_GENAI_API_KEY="]:
                            if line.strip().startswith(var):
                                k = line.split("=", 1)[1].strip().strip("'").strip('"')
                                if k and not k.startswith("dev-") and not k.startswith("secret-"):
                                    key = k
                                    break
                        if key: break
                except Exception:
                    pass
            if key: break

    # Prioritize Gemini 3.6 Flash and Gemini 3.1 Flash Lite (higher allowance/free tier friendly)
    models_to_try = [m.strip() for m in __import__("os").environ.get("GEMINI_MODEL_NAME", "gemini-3.1-flash-lite,gemini-flash-latest").split(",") if m.strip()]

    if key:
        system_instruction = (
            "You are a professional chef and meal planner assistant. "
            "Your job is to generate a detailed, delicious, properly formatted recipe in JSON based on the user request. "
            "Always respect any specified dietary restrictions. "
            "CRITICAL INGREDIENT FORMATTING RULES: "
            "1. Ingredient `name` must be a clean, base grocery item WITHOUT preparation states or adjectives (e.g., use 'Garlic', not 'Minced garlic'; use 'Cheese', not 'Grated cheese'). "
            "2. Move preparation details (like grated, minced, chopped) to the `amount` field (e.g. amount: '2 cloves, minced') or instructions. "
            "3. DO NOT combine ingredients. Instead of 'Salt and pepper', list 'Salt' and 'Black pepper' as two separate items. "
            "Produce ONLY a valid JSON object matching this structure with no markdown formatting:\n"
            "{\n"
            '  "title": "Recipe Name",\n'
            '  "description": "Short description of the dish",\n'
            '  "prep_time": "15 mins",\n'
            '  "cook_time": "25 mins",\n'
            '  "servings": "4 servings",\n'
            '  "cuisine": "Italian",\n'
            '  "dietary_tags": ["Gluten-Free", "Vegetarian"],\n'
            '  "ingredients": [\n'
            '    {"name": "Ingredient Name", "amount": "1.5 lbs", "category": "Produce"}\n'
            '  ],\n'
            '  "instructions": [\n'
            '    "Step 1...",\n'
            '    "Step 2..."\n'
            '  ]\n'
            "}"
        )

        user_prompt = f"Recipe request: {prompt}"
        if dietary_restrictions:
            user_prompt += f"\nImportant Household Dietary Restrictions: {dietary_restrictions}"

        body = {
            "contents": [
                {
                    "parts": [
                        {"text": system_instruction + "\n\n" + user_prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.4,
                "responseMimeType": "application/json"
            }
        }

        for model_name in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": key,
                    "User-Agent": "aistudio-build"
                }
            )
            print(f"[GEMINI REQUEST] Model: {model_name} | URL: {url}", flush=True)
            print(f"[GEMINI REQUEST BODY] {json.dumps(body)}", flush=True)
            try:
                with urllib.request.urlopen(req, timeout=12) as resp:
                    raw_resp = resp.read().decode("utf-8")
                    print(f"[GEMINI RESPONSE RAW] {raw_resp}", flush=True)
                    data = json.loads(raw_resp)
                    candidates = data.get("candidates", [])
                    if candidates:
                        part_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        clean_text = part_text.strip()
                        if clean_text.startswith("```"):
                            lines = clean_text.splitlines()
                            if lines[0].startswith("```"): lines = lines[1:]
                            if lines and lines[-1].startswith("```"): lines = lines[:-1]
                            clean_text = "\n".join(lines).strip()
                        recipe_data = json.loads(clean_text)
                        if isinstance(recipe_data, dict) and "title" in recipe_data:
                            return recipe_data
            except Exception as e:
                print(f"[GEMINI ERROR] Call to {model_name} failed: {e}", flush=True)
                if hasattr(e, 'read'):
                    try:
                        err_resp = e.read().decode("utf-8")
                        print(f"[GEMINI ERROR DETAILS] {err_resp}", flush=True)
                    except Exception:
                        pass
                continue
    else:
        print("[GEMINI WARNING] No API key found. Falling back to local smart recipe generator.", flush=True)
    return _generate_fallback_recipe(prompt, dietary_restrictions)


def _get_weekly_recipe_count(db, hhid):
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    days_since_sunday = (now.weekday() + 1) % 7
    start_of_week = (now - datetime.timedelta(days=days_since_sunday)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_str = start_of_week.strftime("%Y-%m-%d %H:%M:%S")
    try:
        db.execute("CREATE TABLE IF NOT EXISTS recipe_generations (id SERIAL PRIMARY KEY, household_id INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMP NOT NULL DEFAULT NOW())")
        row = db.execute("SELECT COUNT(*) as cnt FROM recipe_generations WHERE household_id = ? AND created_at >= ?", (hhid, start_of_week)).fetchone()
        return row["cnt"] if row else 0
    except Exception as e:
        print(f"Error checking weekly recipe count: {e}")
        return 0


def _record_recipe_generation(db, hhid):
    try:
        db.execute("INSERT INTO recipe_generations (household_id) VALUES (?)", (hhid,))
    except Exception as e:
        print(f"Error recording recipe generation: {e}")


@app.route("/api/recipes/usage", methods=["GET"])
@require_user
def recipe_usage_endpoint():
    hhid = _hh()
    if not hhid:
        return jsonify({"error": "No household"}), 400
    db = get_db()
    try:
        used = _get_weekly_recipe_count(db, hhid)
        limit = int(__import__("os").environ.get("WEEKLY_RECIPE_LIMIT", 7))
        return jsonify({
            "ok": True,
            "used": used,
            "limit": limit,
            "remaining": max(0, limit - used)
        })
    finally:
        db.close()


@app.route("/api/recipes/generate", methods=["POST"])
@require_user
def generate_recipe_endpoint():
    hhid = _hh()
    if not hhid:
        return jsonify({"error": "No household"}), 400
    authmod._init_schema()
    hh = authmod._one(f"SELECT is_premium, dietary_restrictions, subscription_status, trial_ends_at FROM {authmod._HH} WHERE id = ?", (hhid,))
    is_prem = bool(hh.get("is_premium")) if hh else False
    sub_status = hh.get("subscription_status", "free") if hh else "free"
    trial_ends_at = hh.get("trial_ends_at") if hh else None

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

    if not is_prem:
        return jsonify({
            "error": "Recipe Planner is a Premium feature. Please upgrade to Premium in Settings.",
            "code": "PREMIUM_REQUIRED"
        }), 403

    db = get_db()
    try:
        used = _get_weekly_recipe_count(db, hhid)
        limit = int(__import__("os").environ.get("WEEKLY_RECIPE_LIMIT", 7))
        if used >= limit:
            return jsonify({
                "error": f"Weekly limit reached ({limit} of {limit} recipes generated this week). Quota resets on Sunday.",
                "code": "WEEKLY_LIMIT_REACHED",
                "used": used,
                "limit": limit,
                "remaining": 0
            }), 400

        data = request.get_json(silent=True) or {}
        prompt = (data.get("prompt") or "").strip()
        if not prompt:
            return jsonify({"error": "Please enter what recipe you want to make."}), 400
        dietary = (hh.get("dietary_restrictions") or "").strip() if hh else ""

        recipe_data = None
        try:
            recipe_data = _call_gemini_recipe(prompt, dietary)
        except Exception as e:
            print(f"Error calling _call_gemini_recipe: {e}")
            try:
                recipe_data = _generate_fallback_recipe(prompt, dietary)
            except Exception as fallback_e:
                return jsonify({"error": f"Failed to generate recipe: {str(fallback_e)}"}), 500

        if recipe_data:
            _record_recipe_generation(db, hhid)
            new_used = used + 1
            return jsonify({
                "ok": True,
                "recipe": recipe_data,
                "weekly_usage": {
                    "used": new_used,
                    "limit": limit,
                    "remaining": max(0, limit - new_used)
                }
            })
        else:
            return jsonify({"error": "Failed to generate recipe"}), 500
    finally:
        db.close()


@app.route("/api/recipes", methods=["GET", "POST"])
@require_user
def recipes_endpoint():
    hhid = _hh()
    if not hhid:
        return jsonify({"error": "No household"}), 400

    db = get_db()
    try:
        if request.method == "GET":
            hh_status = authmod.get_household_status()
            is_read_only = hh_status.get("is_read_only") if hh_status else False
            downgraded_at = hh_status.get("downgraded_at") if hh_status else None
            
            if is_read_only and downgraded_at:
                rows = db.execute("SELECT * FROM recipes WHERE household_id = ? AND created_at <= ? ORDER BY id DESC", (hhid, downgraded_at)).fetchall()
            else:
                rows = db.execute("SELECT * FROM recipes WHERE household_id = ? ORDER BY id DESC", (hhid,)).fetchall()
            recipes = []
            for r in rows:
                rec = dict(r)
                try: rec["dietary_tags"] = json.loads(rec.get("dietary_tags") or "[]")
                except Exception: rec["dietary_tags"] = []
                try: rec["instructions"] = json.loads(rec.get("instructions") or "[]")
                except Exception: rec["instructions"] = []
                try: rec["ingredients"] = json.loads(rec.get("ingredients") or "[]")
                except Exception: rec["ingredients"] = []
                recipes.append(rec)
            return jsonify({"recipes": recipes})

        # POST: Save recipe
        data = request.get_json(silent=True) or {}
        title = (data.get("title") or "Untitled Recipe").strip()
        desc = (data.get("description") or "").strip()
        prep = (data.get("prep_time") or "").strip()
        cook = (data.get("cook_time") or "").strip()
        cuisine = (data.get("cuisine") or "").strip()
        servings = (data.get("servings") or "").strip()
        tags_json = json.dumps(data.get("dietary_tags") or [])
        instr_json = json.dumps(data.get("instructions") or [])
        ingr_json = json.dumps(data.get("ingredients") or [])

        cur = db.execute(
            "INSERT INTO recipes (household_id, title, description, prep_time, cook_time, servings, cuisine, dietary_tags, instructions, ingredients) "
            "VALUES (%s, %s, %s, %s, %s, ?, ?, ?, ?, ?) RETURNING id",
            (hhid, title, desc, prep, cook, servings, cuisine, tags_json, instr_json, ingr_json)
        )
        recipe_id = cur.fetchall()[0]["id"]

        return jsonify({"ok": True, "recipe_id": recipe_id, "title": title})
    finally:
        db.close()


@app.route("/api/recipes/<int:recipe_id>", methods=["DELETE"])
@require_user
def delete_recipe_endpoint(recipe_id):
    hhid = _hh()
    if not hhid:
        return jsonify({"error": "No household"}), 400
    db = get_db()
    try:
        db.execute("DELETE FROM recipes WHERE id = ? AND household_id = ?", (recipe_id, hhid))
        return jsonify({"ok": True})
    finally:
        db.close()


@app.route("/api/recipes/add-to-list", methods=["POST"])
@require_user
def add_recipe_to_list_endpoint():
    hhid = _hh()
    if not hhid:
        return jsonify({"error": "No household"}), 400

    data = request.get_json(silent=True) or {}
    recipe_title = (data.get("recipe_title") or "Recipe").strip()
    items = data.get("items") or []

    if not items:
        return jsonify({"error": "No ingredients provided"}), 400

    db = get_db()
    try:
        user_name = get_display_name() if authmod else "User"

        added_count = 0
        for item in items:
            name = (item.get("name") or "").strip()
            if not name:
                continue
            store_id = item.get("store_id")
            if not store_id:
                continue
            quantity = ""

            # Ensure store item exists for auto-complete, and copy its category
            cat_row = db.execute(
                "SELECT category FROM store_items WHERE store_id = ? AND household_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?))",
                (store_id, hhid, name),
            ).fetchone()

            if cat_row:
                category = ((cat_row["category"] if isinstance(cat_row, dict) else cat_row[0]) or "").strip()
                if not category:
                    category = categorize(name)
                    if category:
                        try:
                            db.execute(
                                "UPDATE store_items SET category = ? WHERE store_id = ? AND household_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?))",
                                (category, store_id, hhid, name),
                            )
                        except Exception:
                            pass
            else:
                category = (item.get("category") or "").strip()
                if not category:
                    category = categorize(name)
                try:
                    db.execute(
                        "INSERT INTO store_items (household_id, store_id, name, category) VALUES (?, ?, ?, ?)",
                        (hhid, store_id, name, category),
                    )
                except Exception:
                    pass

            existing = db.execute(
                "SELECT id, quantity, recipe_tag FROM list_items WHERE household_id = ? AND store_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?)) AND purchased = FALSE",
                (hhid, store_id, name)
            ).fetchall()

            if existing and len(existing) > 0:
                # Update existing
                ext = existing[0]
                new_qty = quantity
                old_qty = ext["quantity"] or ""
                if new_qty and old_qty and new_qty not in old_qty:
                    new_qty = f"{old_qty} + {new_qty}"
                elif old_qty:
                    new_qty = old_qty
                
                old_tag = ext["recipe_tag"] or ""
                new_tag = recipe_title
                if old_tag and new_tag and new_tag not in old_tag:
                    new_tag = f"{old_tag}, {new_tag}"
                elif old_tag:
                    new_tag = old_tag

                db.execute(
                    "UPDATE list_items SET quantity = ?, recipe_tag = ? WHERE id = ?",
                    (new_qty, new_tag, ext["id"])
                )
                added_count += 1
            else:
                db.execute(
                    "INSERT INTO list_items (store_id, name, category, added_by, quantity, household_id, recipe_tag) "
                    "VALUES (%s, %s, %s, %s, %s, ?, ?)",
                    (store_id, name, category, user_name, quantity, hhid, recipe_title)
                )
                added_count += 1
        return jsonify({"ok": True, "added_count": added_count, "recipe_title": recipe_title})
    finally:
        db.close()

@app.route("/logout")
def logout_page():
    """Log the user out and redirect to login."""
    session.clear()
    return redirect("/login")

@app.route("/api/version", methods=["GET"])
def api_version():
    import os
    return jsonify({"version": os.environ.get("RENDER_GIT_COMMIT", "local")[:7]})

@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "db": "pg",
        "db_url_set": bool(os.environ.get("DATABASE_URL")),
        "db_url_prefix": os.environ.get("DATABASE_URL", "")[:25] + "..." if os.environ.get("DATABASE_URL") else "EMPTY",
        "render_hostname": os.environ.get("RENDER_EXTERNAL_HOSTNAME", "not set"),
    })


@app.route("/<path:filename>")
def root_files(filename):
    if filename == "favicon.ico":
        return send_from_directory("static", "icon-192.png", mimetype="image/png")
    if filename in ["app-ads.txt", "ads.txt", "robots.txt"]:
        return send_from_directory("static", filename, mimetype="text/plain")
    if filename in ["sw.js", "manifest.json", "favicon.ico"] or filename.startswith("icon-") or filename.endswith(".png") or filename.endswith(".ico"):
        return send_from_directory("static", filename)
    return "", 404

@app.route("/")
@app.route("/index.html")
def index():
    if not is_logged_in():
        return redirect("/login")
    resp = send_from_directory("static", "index.html")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


# ── Auth API (shared, includes signup + household management) ──

register_auth_routes(app)


# ── stores (household-scoped) ──




@app.route("/api/init")
@require_user
def init_data():
    db = get_db()
    hh = _hh()
    hh_status = authmod.get_household_status()
    is_read_only = hh_status.get("is_read_only") if hh_status else False
    downgraded_at = hh_status.get("downgraded_at") if hh_status else None
    
    try:
        gl = db.execute("SELECT id FROM stores WHERE household_id = %s AND name = 'General List'", (hh,)).fetchone()
        if not gl:
            db.execute("INSERT INTO stores (household_id, name) VALUES (%s, 'General List')", (hh,))
        
        if is_read_only and downgraded_at:
            stores = db.execute("SELECT s.*, (SELECT MAX(visit_date) FROM store_visits WHERE store_id = s.id AND household_id = %s) as last_visited FROM stores s WHERE s.household_id = %s AND (s.created_at <= %s OR s.name = 'General List') ORDER BY CASE WHEN s.name = 'General List' THEN 0 ELSE 1 END, s.name", (hh, hh, downgraded_at)).fetchall()
            list_items = db.execute('''
                SELECT l.*, s.name as store_name, s.category_order as store_category_order
                FROM list_items l
                JOIN stores s ON l.store_id = s.id AND s.household_id = %s
                WHERE l.household_id = %s AND l.added_at <= %s
                ORDER BY l.purchased ASC, CASE WHEN s.name = 'General List' THEN 0 ELSE 1 END, s.name, COALESCE(NULLIF(l.category,''),'ZZZ'), l.name
            ''', (hh, hh, downgraded_at)).fetchall()
        else:
            stores = db.execute("SELECT s.*, (SELECT MAX(visit_date) FROM store_visits WHERE store_id = s.id AND household_id = %s) as last_visited FROM stores s WHERE s.household_id = %s ORDER BY CASE WHEN s.name = 'General List' THEN 0 ELSE 1 END, s.name", (hh, hh)).fetchall()
            list_items = db.execute('''
                SELECT l.*, s.name as store_name, s.category_order as store_category_order
                FROM list_items l
                JOIN stores s ON l.store_id = s.id AND s.household_id = %s
                WHERE l.household_id = %s
                ORDER BY l.purchased ASC, CASE WHEN s.name = 'General List' THEN 0 ELSE 1 END, s.name, COALESCE(NULLIF(l.category,''),'ZZZ'), l.name
            ''', (hh, hh)).fetchall()
        if is_read_only and downgraded_at:
            recipes_rows = db.execute("SELECT * FROM recipes WHERE household_id = ? AND created_at <= ? ORDER BY id DESC", (hh, downgraded_at)).fetchall()
        else:
            recipes_rows = db.execute("SELECT * FROM recipes WHERE household_id = ? ORDER BY id DESC", (hh,)).fetchall()
        
        recipes = []
        import json
        for r in recipes_rows:
            rec = dict(r)
            try: rec["dietary_tags"] = json.loads(rec.get("dietary_tags") or "[]")
            except Exception: rec["dietary_tags"] = []
            try: rec["instructions"] = json.loads(rec.get("instructions") or "[]")
            except Exception: rec["instructions"] = []
            try: rec["ingredients"] = json.loads(rec.get("ingredients") or "[]")
            except Exception: rec["ingredients"] = []
            recipes.append(rec)

        stores_list = []
        for s in stores:
            d = dict(s)
            if d.get("planned_visit_date"): d["planned_visit_date"] = str(d["planned_visit_date"])
            if d.get("last_visited"): d["last_visited"] = str(d["last_visited"])
            stores_list.append(d)

        hh_count = 1
        uid = authmod.get_user_id()
        if uid:
            try:
                hh_row = authmod._one("SELECT COUNT(*) as c FROM auth_household_members WHERE user_id = ?", (uid,))
                if hh_row and hh_row.get("c"):
                    hh_count = int(hh_row["c"])
            except Exception:
                pass

        return jsonify({
            "stores": stores_list,
            "list": [dict(r) for r in list_items],
            "recipes": recipes,
            "is_read_only": is_read_only,
            "user_email": authmod._get().get("email") if authmod._get() else "",
            "user_name": authmod._get().get("name", "Someone").split()[0] if authmod._get() else "Someone",
            "households_count": hh_count,
            "household_created_at": str(hh_status.get("created_at")) if hh_status and hh_status.get("created_at") else ""
        })
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

@app.route("/api/stores")
@require_user
def list_stores():
    db = get_db()
    try:
        hh = _hh()
        stores = db.execute(
            "SELECT s.*, (SELECT MAX(visit_date) FROM store_visits WHERE store_id = s.id AND household_id = ?) as last_visited FROM stores s WHERE s.household_id = ? ORDER BY CASE WHEN name = 'General List' THEN 0 ELSE 1 END, name", (hh, hh)
        ).fetchall()
        stores_list = []
        for s in stores:
            d = dict(s)
            if d.get("planned_visit_date"):
                d["planned_visit_date"] = str(d["planned_visit_date"])
            if d.get("last_visited"):
                d["last_visited"] = str(d["last_visited"])
            stores_list.append(d)
        return jsonify(stores_list)
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

@app.route("/api/stores", methods=["POST"])
@require_user
def add_store():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    hh = _hh()
    db = get_db()
    store_id = None
    try:
        cat_order = "Produce,Bakery,Meat & Seafood,Deli,Spices & Seasonings,Legumes & Grains,Pantry,Canned & Jarred,Dips & Spreads,Nuts & Seeds,Snacks & Sweets,Beverages,Dairy,Frozen,Household"
        if any(k in name.lower() for k in ["patel", "indiaco", "indian", "desi", "bazar", "apna"]):
            cat_order = "Produce,Spices & Seasonings,Legumes & Grains,Indian Specialties,Nuts & Seeds,Dips & Spreads,Canned & Jarred,Snacks & Sweets,Beverages,Dairy,Frozen,Household"
        db.execute("INSERT INTO stores (household_id, name, category_order) VALUES (?, ?, ?)", (hh, name, cat_order))
        st = db.execute("SELECT id FROM stores WHERE household_id = ? AND name = ? ORDER BY id DESC LIMIT 1", (hh, name)).fetchone()
        if st:
            store_id = st.get("id") if isinstance(st, dict) else st[0]
            try:
                db.execute("INSERT INTO store_enrich_queue (store_id, household_id) VALUES (?, ?)", (store_id, hh))
            except Exception:
                pass
        db.commit()
    except Exception:
        try: db.rollback()
        except Exception: pass
    finally:
        db.close()
    if store_id:
        return jsonify({"id": store_id, "name": name, "ok": True})
    return jsonify({"ok": True})


@app.route("/api/stores/<int:store_id>", methods=["DELETE"])
@require_user
def delete_store(store_id):
    hh = _hh()
    db = get_db()
    try:
        store = db.execute(
            "SELECT id FROM stores WHERE id = ? AND household_id = ?",
            (store_id, hh),
        ).fetchone()
        if not store:
            return jsonify({"error": "store not found"}), 404

        try: db.execute("DELETE FROM store_enrich_queue WHERE store_id = ? AND household_id = ?", (store_id, hh))
        except Exception: pass
        try: db.execute("DELETE FROM store_visits WHERE store_id = ? AND household_id = ?", (store_id, hh))
        except Exception: pass
        try: db.execute("DELETE FROM store_items WHERE store_id = ? AND household_id = ?", (store_id, hh))
        except Exception: pass
        try: db.execute("DELETE FROM list_items WHERE store_id = ? AND household_id = ?", (store_id, hh))
        except Exception: pass

        db.execute("DELETE FROM stores WHERE id = ? AND household_id = ?", (store_id, hh))
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


@app.route("/api/stores/<int:store_id>", methods=["PUT"])
@require_user
def rename_store(store_id):
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    hh = _hh()
    db = get_db()
    try:
        store = db.execute(
            "SELECT id FROM stores WHERE id = ? AND household_id = ?",
            (store_id, hh),
        ).fetchone()
        if not store:
            return jsonify({"error": "store not found"}), 404

        db.execute(
            "UPDATE stores SET name = ? WHERE id = ? AND household_id = ?",
            (name, store_id, hh),
        )
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


# ── store items (household-scoped) ──

@app.route("/api/stores/<int:store_id>/items")
@require_user
def list_store_items(store_id):
    db = get_db()
    try:
        # Verify store belongs to this household
        store = db.execute(
            "SELECT id FROM stores WHERE id = ? AND household_id = ?",
            (store_id, _hh()),
        ).fetchone()
        if not store:
            return jsonify({"error": "not found"}), 404

        items = db.execute(
            "SELECT * FROM store_items WHERE store_id = ? AND household_id = ? ORDER BY COALESCE(NULLIF(category,''),'ZZZ'), name",
            (store_id, _hh()),
        ).fetchall()

        resp = jsonify([dict(r) for r in items])
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return resp
    finally:
        db.close()


@app.route("/api/stores/<int:store_id>/items", methods=["POST"])
@require_user
def add_store_item(store_id):
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    category = (data.get("category") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400

    db = get_db()
    try:
        # Verify store ownership
        store = db.execute(
            "SELECT id FROM stores WHERE id = ? AND household_id = ?",
            (store_id, _hh()),
        ).fetchone()
        if not store:
            return jsonify({"error": "store not found"}), 404

        existing = db.execute(
            "SELECT id, category FROM store_items WHERE store_id = ? AND household_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?))",
            (store_id, _hh(), name),
        ).fetchone()
        if existing:
            # Update category if provided or auto-categorize if missing
            if category:
                db.execute("UPDATE store_items SET category = ? WHERE id = ?", (category, existing["id"]))
                db.commit()
            else:
                existing_cat = (existing["category"] if isinstance(existing, dict) else existing[1]) or ""
                if not str(existing_cat).strip():
                    new_cat = categorize(name)
                    if new_cat:
                        db.execute("UPDATE store_items SET category = ? WHERE id = ?", (new_cat, existing["id"]))
                        db.commit()
            return jsonify({"ok": True, "existing": True, "id": existing["id"]})

        # Auto-categorize if not provided
        if not category:
            category = categorize(name)

        db.execute(
            "INSERT INTO store_items (household_id, store_id, name, category) VALUES (?, ?, ?, ?)",
            (_hh(), store_id, name, category),
        )
        db.commit()

        row = db.execute("SELECT id FROM store_items WHERE store_id = ? AND household_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?))",
                         (store_id, _hh(), name)).fetchone()
        return jsonify({"ok": True, "id": row["id"] if row else 0})
    finally:
        db.close()


@app.route("/api/stores/<int:store_id>/items/<int:item_id>", methods=["DELETE"])
@require_user
def delete_store_item(store_id, item_id):
    hh = _hh()
    db = get_db()
    try:
        store = db.execute(
            "SELECT id FROM stores WHERE id = ? AND household_id = ?",
            (store_id, hh),
        ).fetchone()
        if not store:
            return jsonify({"error": "store not found"}), 404

        db.execute(
            "DELETE FROM store_items WHERE id = ? AND store_id = ? AND household_id = ?",
            (item_id, store_id, hh),
        )
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


@app.route("/api/stores/<int:store_id>/items/<int:item_id>", methods=["PUT"])
@require_user
def update_store_item(store_id, item_id):
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    category = (data.get("category") or "").strip()
    hh = _hh()
    db = get_db()
    try:
        store = db.execute(
            "SELECT id FROM stores WHERE id = ? AND household_id = ?",
            (store_id, hh),
        ).fetchone()
        if not store:
            return jsonify({"error": "store not found"}), 404

        if name and category:
            db.execute(
                "UPDATE store_items SET name = ?, category = ? WHERE id = ? AND store_id = ? AND household_id = ?",
                (name, category, item_id, store_id, hh),
            )
        elif name:
            db.execute(
                "UPDATE store_items SET name = ? WHERE id = ? AND store_id = ? AND household_id = ?",
                (name, item_id, store_id, hh),
            )
        elif category:
            db.execute(
                "UPDATE store_items SET category = ? WHERE id = ? AND store_id = ? AND household_id = ?",
                (category, item_id, store_id, hh),
            )

        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()



@app.route("/api/list")
@require_user
def list_grocery():
    db = get_db()
    try:
        items = db.execute("""
            SELECT l.*, s.name as store_name, s.category_order as store_category_order
            FROM list_items l
            JOIN stores s ON l.store_id = s.id AND s.household_id = ?
            WHERE l.household_id = ?
            ORDER BY l.purchased ASC, CASE WHEN s.name = 'General List' THEN 0 ELSE 1 END, s.name, COALESCE(NULLIF(l.category,''),'ZZZ'), l.name
        """, (_hh(), _hh())).fetchall()
        return jsonify([dict(r) for r in items])
    finally:
        db.close()


@app.route("/api/item_frequencies", methods=["GET"])
@require_user
def item_frequencies():
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({})
    db = get_db()
    try:
        res = db.execute("""
            SELECT l.store_id, COUNT(*) as c
            FROM list_items l
            JOIN stores s ON l.store_id = s.id
            WHERE l.household_id = ? AND LOWER(TRIM(l.name)) = LOWER(TRIM(?)) AND l.purchased = TRUE AND s.name != 'General List'
            GROUP BY l.store_id
        """, (_hh(), name)).fetchall()
        return jsonify({r["store_id"]: r["c"] for r in res})
    finally:
        db.close()

@app.route("/api/search_catalog", methods=["GET"])
@require_user
def search_catalog():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])
        
    db = get_db()
    hh = _hh()
    try:
        # Get matching items across all stores for this household
        # Only suggest from actual stores (not General List, or maybe include General List if they want?)
        # Let's include all stores.
        items = db.execute('''
            SELECT si.id, si.name, si.store_id, s.name as store_name,
              (SELECT COUNT(*) FROM list_items li JOIN stores st ON li.store_id = st.id WHERE li.store_id = si.store_id AND li.household_id = si.household_id AND LOWER(li.name) = LOWER(si.name) AND li.purchased = TRUE AND st.name != 'General List') as purchased_count
            FROM store_items si
            JOIN stores s ON si.store_id = s.id
            WHERE si.household_id = ? AND si.name ILIKE ?
            ORDER BY si.name, s.name
            LIMIT 20
        ''', (hh, f"%{query}%")).fetchall()
        
        # We need to deduplicate by name to show unique items first, or maybe group by name
        res = []
        seen = set()
        for i in items:
            key = (i["name"].lower(), i["store_id"])
            if key not in seen:
                seen.add(key)
                res.append(dict(i))
                
        return jsonify(res)
    finally:
        db.close()

@app.route("/api/suggest_store", methods=["GET"])
@require_user
def suggest_store():
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"store_id": None})
    
    db = get_db()
    hh = _hh()
    try:
        row = db.execute('''
            SELECT s.id, s.name, COUNT(*) as c
            FROM list_items l
            JOIN stores s ON l.store_id = s.id
            WHERE l.household_id = ? AND l.name ILIKE ? AND s.name != 'General List'
            GROUP BY s.id, s.name
            ORDER BY c DESC
            LIMIT 1
        ''', (hh, name)).fetchone()
        
        if row:
            return jsonify({"store_id": row["id"], "store_name": row["name"]})
        else:
            return jsonify({"store_id": None})
    finally:
        db.close()

@app.route("/api/list", methods=["POST"])
@require_user
def add_to_list():
    data = request.get_json(silent=True) or {}
    store_id = data.get("store_id")
    name = (data.get("name") or "").strip()
    if not name or not store_id:
        return jsonify({"error": "store_id and name required"}), 400
    db = get_db()
    try:
        # Verify store ownership
        store = db.execute(
            "SELECT id FROM stores WHERE id = ? AND household_id = ?",
            (store_id, _hh()),
        ).fetchone()
        if not store:
            return jsonify({"error": "store not found"}), 404

        existing = db.execute(
            "SELECT id FROM list_items WHERE store_id = ? AND household_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?)) AND purchased = FALSE",
            (store_id, _hh(), name),
        ).fetchone()
        if existing:
            return jsonify({"ok": False, "duplicate": True, "existing_id": existing["id"]})

        # Ensure store item exists for auto-complete, and copy its category
        cat_row = db.execute(
            "SELECT category FROM store_items WHERE store_id = ? AND household_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?))",
            (store_id, _hh(), name),
        ).fetchone()
        existing_category = ((cat_row["category"] if cat_row else "") or "").strip()

        if not existing_category:
            existing_category = categorize(name)
            if not cat_row:
                try:
                    db.execute(
                        "INSERT INTO store_items (household_id, store_id, name, category) VALUES (?, ?, ?, ?)",
                        (_hh(), store_id, name, existing_category),
                    )
                except Exception:
                    pass
            elif existing_category:
                try:
                    db.execute(
                        "UPDATE store_items SET category = ? WHERE store_id = ? AND household_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?))",
                        (existing_category, store_id, _hh(), name),
                    )
                except Exception:
                    pass

        quantity = (data.get("quantity") or "").strip()
        db.execute(
            "INSERT INTO list_items (household_id, store_id, name, category, quantity, added_by) VALUES (%s, %s, %s, %s, %s, ?)",
            (_hh(), store_id, name, existing_category, quantity, get_display_name()),
        )
        db.commit()

        row = db.execute("SELECT id FROM list_items WHERE store_id = ? AND household_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?)) AND purchased = FALSE ORDER BY id DESC LIMIT 1",
                         (store_id, _hh(), name)).fetchone()
        return jsonify({"ok": True, "id": row["id"] if row else 0})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()




@app.route("/api/list/<int:item_id>/quantity", methods=["PUT"])
@require_user
def update_item_quantity(item_id):
    data = request.get_json(silent=True) or {}
    quantity = (data.get("quantity") or "").strip()
    db = get_db()
    try:
        db.execute(
            "UPDATE list_items SET quantity = ? WHERE id = ? AND household_id = ?",
            (quantity, item_id, _hh()),
        )
        db.commit()
        return jsonify({"ok": True, "id": item_id, "quantity": quantity})
    finally:
        db.close()

@app.route("/api/list/<int:item_id>/toggle", methods=["POST"])
@require_user
def toggle_list_item(item_id):
    db = get_db()
    try:
        item = db.execute(
            "SELECT * FROM list_items WHERE id = ? AND household_id = ?",
            (item_id, _hh()),
        ).fetchone()
        if not item:
            return jsonify({"error": "not found"}), 404

        if item["purchased"]:
            db.execute("UPDATE list_items SET purchased=FALSE, purchased_by=NULL, purchased_at=NULL WHERE id=?", (item_id,))
        else:
            db.execute(
                "UPDATE list_items SET purchased=TRUE, purchased_by=?, purchased_at=NOW() WHERE id=?",
                (get_display_name(), item_id),
            )
            # Update item_purchase_stats
            db.execute("""
                INSERT INTO item_purchase_stats (household_id, name, category, total_purchases, last_purchased)
                VALUES (?, ?, ?, 1, NOW())
                ON CONFLICT (household_id, name)
                DO UPDATE SET total_purchases = item_purchase_stats.total_purchases + 1, last_purchased = NOW()
            """, (_hh(), item["name"], item["category"]))
            # Auto-record a visit for this store today
            today = __import__('datetime').date.today().isoformat()
            sv = db.execute(
                "SELECT id FROM store_visits WHERE store_id = ? AND household_id = ? AND visit_date = ?",
                (item["store_id"], _hh(), today)
            ).fetchone()
            if sv:
                db.execute("UPDATE store_visits SET items_count = items_count + 1 WHERE id = ?", (sv["id"],))
            else:
                db.execute(
                    "INSERT INTO store_visits (store_id, household_id, visit_date, items_count) VALUES (?, ?, ?, 1)",
                    (item["store_id"], _hh(), today)
                )
            db.execute("UPDATE stores SET planned_visit_date = NULL, planned_visit_by = NULL, visit_notified_users = '' WHERE id = ? AND household_id = ?", (item["store_id"], _hh()))
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()





@app.route("/api/stores/<int:store_id>/visits/<visit_date>/items")
@require_user
def get_visit_items(store_id, visit_date):
    db = get_db()
    try:
        # PostgreSQL specific cast: DATE(purchased_at)
        items = db.execute('''
            SELECT id, name, category 
            FROM list_items 
            WHERE store_id = ? AND household_id = ? 
              AND purchased = TRUE 
              AND DATE(purchased_at) = ?
            ORDER BY name
        ''', (store_id, _hh(), visit_date)).fetchall()
        return jsonify([dict(r) for r in items])
    finally:
        db.close()

@app.route("/api/stores/<int:store_id>/visits/replan", methods=["POST"])
@require_user
def replan_visit_items(store_id):
    data = request.get_json(silent=True) or {}
    items_to_add = data.get("items", [])
    if not items_to_add:
        return jsonify({"ok": True})
        
    db = get_db()
    try:
        added_count = 0
        for name in items_to_add:
            name_clean = str(name).strip()
            if not name_clean:
                continue
            
            # Check if already in active list for this store
            existing = db.execute(
                "SELECT id FROM list_items WHERE store_id = ? AND household_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?)) AND purchased = FALSE",
                (store_id, _hh(), name_clean)
            ).fetchone()
            
            if not existing:
                # Add it as a new unpurchased item without quantity
                db.execute(
                    "INSERT INTO list_items (store_id, name, category, household_id, added_by, purchased) VALUES (?, ?, '', ?, ?, FALSE)",
                    (store_id, name_clean, _hh(), get_display_name())
                )
                added_count += 1
                
        db.commit()
        return jsonify({"ok": True, "added": added_count})
    finally:
        db.close()

@app.route("/api/visits/history")
@require_user
def get_global_visits():
    db = get_db()
    try:
        visits = db.execute('''
            SELECT v.store_id, v.visit_date, v.items_count, s.name as store_name
            FROM store_visits v
            JOIN stores s ON v.store_id = s.id
            WHERE v.household_id = ? AND s.name != 'General List'
            ORDER BY v.visit_date DESC
            LIMIT 100
        ''', (_hh(),)).fetchall()
        
        visits_list = []
        for v in visits:
            d = dict(v)
            if d.get("visit_date"):
                d["visit_date"] = str(d["visit_date"])
            visits_list.append(d)
        return jsonify(visits_list)
    finally:
        db.close()

@app.route("/api/stores/<int:store_id>/history")
@require_user
def get_store_history(store_id):
    db = get_db()
    try:
        visits = db.execute("SELECT visit_date, items_count FROM store_visits WHERE store_id = ? AND household_id = ? ORDER BY visit_date DESC LIMIT 50", (store_id, _hh())).fetchall()
        return jsonify([dict(v) for v in visits])
    finally:
        db.close()

@app.route("/api/stores/<int:store_id>/plan", methods=["POST"])
@require_user
def plan_store_visit(store_id):
    data = request.get_json(silent=True) or {}
    date = data.get("date")
    db = get_db()
    try:
        if date:
            import shared.auth as authmod
            user_info = authmod._get() or {}
            first_name = user_info.get("name", "Someone").split()[0]
            if len(first_name) > 8:
                first_name = first_name[:8] + "..."
            user_id = user_info.get("email", "")
            db.execute("UPDATE stores SET planned_visit_date = ?, planned_visit_by = ?, visit_notified_users = ? WHERE id = ? AND household_id = ?", (date, first_name, user_id, store_id, _hh()))
        else:
            db.execute("UPDATE stores SET planned_visit_date = NULL, planned_visit_by = NULL, visit_notified_users = '' WHERE id = ? AND household_id = ?", (store_id, _hh()))
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()

@app.route("/api/stores/<int:store_id>/dismiss_visit_notification", methods=["POST"])
@require_user
def dismiss_visit_notification(store_id):
    db = get_db()
    try:
        import shared.auth as authmod
        user_info = authmod._get() or {}
        user_id = user_info.get("email", "")
        store = db.execute("SELECT visit_notified_users FROM stores WHERE id = ? AND household_id = ?", (store_id, _hh())).fetchone()
        if store:
            notified = store.get("visit_notified_users") or ""
            if user_id not in notified.split(","):
                notified = notified + "," + user_id if notified else user_id
                db.execute("UPDATE stores SET visit_notified_users = ? WHERE id = ? AND household_id = ?", (notified, store_id, _hh()))
                db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


@app.route("/api/list/<int:item_id>", methods=["DELETE"])
@require_user
def delete_list_item(item_id):
    db = get_db()
    try:
        db.execute(
            "DELETE FROM list_items WHERE id = ? AND household_id = ?",
            (item_id, _hh()),
        )
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


@app.route("/api/list/<int:item_id>/move", methods=["PUT"])
@require_user
def move_list_item(item_id):
    data = request.get_json(silent=True) or {}
    target_store_id = data.get("store_id")
    if not target_store_id:
        return jsonify({"error": "store_id required"}), 400
    db = get_db()
    try:
        # Verify item belongs to this household
        item = db.execute(
            "SELECT * FROM list_items WHERE id = ? AND household_id = ?",
            (item_id, _hh()),
        ).fetchone()
        if not item:
            return jsonify({"error": "not found"}), 404

        # Verify target store belongs to this household
        target = db.execute(
            "SELECT id FROM stores WHERE id = ? AND household_id = ?",
            (target_store_id, _hh()),
        ).fetchone()
        if not target:
            return jsonify({"error": "target store not found"}), 404

        # Check if target store already has this exact item active (unpurchased)
        existing_list_item = db.execute(
            "SELECT id FROM list_items WHERE store_id = ? AND household_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?)) AND purchased = FALSE",
            (target_store_id, _hh(), item["name"])
        ).fetchone()

        if existing_list_item:
            # Deduplicate: just delete the original item being moved
            db.execute(
                "DELETE FROM list_items WHERE id = ? AND household_id = ?",
                (item_id, _hh())
            )
        else:
            # Check if item with exact same name already exists in target store list
            existing_list_item = db.execute(
                "SELECT id FROM list_items WHERE store_id = ? AND household_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?))",
                (target_store_id, _hh(), item["name"])
            ).fetchone()

            if existing_list_item:
                # Item already in target list, deduplicate: just delete the one being moved
                db.execute("DELETE FROM list_items WHERE id = ? AND household_id = ?", (item_id, _hh()))
            else:
                # Move the item
                db.execute(
                    "UPDATE list_items SET store_id = ? WHERE id = ? AND household_id = ?",
                    (target_store_id, item_id, _hh()),
                )

        # Also ensure the item exists in the target store's catalog for autocomplete
        exists = db.execute("SELECT id, category FROM store_items WHERE store_id = ? AND household_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?))", 
                            (target_store_id, _hh(), item["name"])).fetchone()
        item_cat = (item.get("category") or "").strip() or categorize(item["name"])
        if not exists:
            db.execute(
                "INSERT INTO store_items (household_id, store_id, name, category) VALUES (?, ?, ?, ?)",
                (_hh(), target_store_id, item["name"], item_cat),
            )
        elif item_cat and not (exists.get("category") if isinstance(exists, dict) else exists[1]):
            db.execute(
                "UPDATE store_items SET category = ? WHERE id = ?",
                (item_cat, exists["id"] if isinstance(exists, dict) else exists[0]),
            )
        
        db.commit()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

@app.route("/api/list/clear", methods=["POST"])
@require_user
def clear_list():
    db = get_db()
    try:
        db.execute(
            "DELETE FROM list_items WHERE purchased = FALSE AND household_id = ?",
            (_hh(),),
        )
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


@app.route("/api/sync", methods=["POST"])
@require_user
def sync_offline_actions():
    """Sync offline queued actions from client for Pro / Premium users."""
    data = request.get_json(silent=True) or {}
    actions = data.get("actions", [])
    if not isinstance(actions, list):
        return jsonify({"error": "actions array required"}), 400
        
    hh_status = authmod.get_household_status()
    if request.method == "POST":
        if hh_status and hh_status.get("is_read_only"):
            return jsonify({"error": "Live household sync is paused because your household is on the Free plan. Only the owner can make changes, or you can spin off into a personal household.", "code": "read_only"}), 403


    db = get_db()
    applied_count = 0
    try:
        hh_id = _hh()
        display_name = get_display_name()

        for act in actions:
            if not isinstance(act, dict):
                continue
            act_type = act.get("type")
            act_data = act.get("data", {})

            if act_type == "add":
                store_id = act_data.get("store_id")
                name = (act_data.get("name") or "").strip()
                quantity = (act_data.get("quantity") or "").strip()
                if name and store_id:
                    store = db.execute("SELECT id FROM stores WHERE id = ? AND household_id = ?", (store_id, hh_id)).fetchone()
                    if store:
                        existing = db.execute(
                            "SELECT id FROM list_items WHERE store_id = ? AND household_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?)) AND purchased = FALSE",
                            (store_id, hh_id, name)
                        ).fetchone()
                        if not existing:
                            cat_row = db.execute(
                                "SELECT category FROM store_items WHERE store_id = ? AND household_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?))",
                                (store_id, hh_id, name)
                            ).fetchone()
                            existing_category = ((cat_row["category"] if cat_row else "") or "").strip() or categorize(name)
                            if cat_row and not (cat_row["category"] or "").strip() and existing_category:
                                try:
                                    db.execute(
                                        "UPDATE store_items SET category = ? WHERE store_id = ? AND household_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?))",
                                        (existing_category, store_id, hh_id, name)
                                    )
                                except Exception:
                                    pass
                            db.execute(
                                "INSERT INTO list_items (household_id, store_id, name, category, quantity, added_by) VALUES (%s, %s, %s, %s, %s, ?)",
                                (hh_id, store_id, name, existing_category, quantity, display_name)
                            )
                            applied_count += 1

            elif act_type == "toggle":
                item_id = act_data.get("id")
                if item_id and not str(item_id).startswith("temp_"):
                    item = db.execute("SELECT * FROM list_items WHERE id = ? AND household_id = ?", (item_id, hh_id)).fetchone()
                    if item:
                        if item["purchased"]:
                            db.execute("UPDATE list_items SET purchased=FALSE, purchased_by=NULL, purchased_at=NULL WHERE id=?", (item_id,))
                        else:
                            db.execute("UPDATE list_items SET purchased=TRUE, purchased_by=?, purchased_at=NOW() WHERE id=?", (display_name, item_id))
                            db.execute("""
                                INSERT INTO item_purchase_stats (household_id, name, category, total_purchases, last_purchased)
                                VALUES (?, ?, ?, 1, NOW())
                                ON CONFLICT (household_id, name)
                                DO UPDATE SET total_purchases = item_purchase_stats.total_purchases + 1, last_purchased = NOW()
                            """, (hh_id, item["name"], item["category"]))
                            
                            # Auto-record a visit for this store today (for offline sync as well)
                            today = __import__('datetime').date.today().isoformat()
                            sv = db.execute(
                                "SELECT id FROM store_visits WHERE store_id = ? AND household_id = ? AND visit_date = ?",
                                (item["store_id"], hh_id, today)
                            ).fetchone()
                            if sv:
                                db.execute("UPDATE store_visits SET items_count = items_count + 1 WHERE id = ?", (sv["id"],))
                            else:
                                db.execute(
                                    "INSERT INTO store_visits (store_id, household_id, visit_date, items_count) VALUES (?, ?, ?, 1)",
                                    (item["store_id"], hh_id, today)
                                )
                            db.execute("UPDATE stores SET planned_visit_date = NULL, planned_visit_by = NULL, visit_notified_users = '' WHERE id = ? AND household_id = ?", (item["store_id"], hh_id))

                        applied_count += 1

            elif act_type == "delete":
                item_id = act_data.get("id")
                if item_id and not str(item_id).startswith("temp_"):
                    db.execute("DELETE FROM list_items WHERE id = ? AND household_id = ?", (item_id, hh_id))
                    applied_count += 1

            elif act_type == "quantity":
                item_id = act_data.get("id")
                quantity = (act_data.get("quantity") or "").strip()
                if item_id and not str(item_id).startswith("temp_"):
                    db.execute("UPDATE list_items SET quantity = ? WHERE id = ? AND household_id = ?", (quantity, item_id, hh_id))
                    applied_count += 1

            elif act_type == "move":
                item_id = act_data.get("id")
                target_store_id = act_data.get("store_id")
                if item_id and target_store_id and not str(item_id).startswith("temp_"):
                    db.execute("UPDATE list_items SET store_id = ? WHERE id = ? AND household_id = ?", (target_store_id, item_id, hh_id))
                    applied_count += 1

            elif act_type == "clear":
                db.execute("DELETE FROM list_items WHERE purchased = FALSE AND household_id = ?", (hh_id,))
                applied_count += 1

        db.commit()

        items = db.execute("""
            SELECT l.*, s.name as store_name, s.category_order as store_category_order
            FROM list_items l
            JOIN stores s ON l.store_id = s.id AND s.household_id = ?
            WHERE l.household_id = ?
            ORDER BY l.purchased ASC, CASE WHEN s.name = 'General List' THEN 0 ELSE 1 END, s.name, COALESCE(NULLIF(l.category,''),'ZZZ'), l.name
        """, (hh_id, hh_id)).fetchall()

        return jsonify({"ok": True, "synced_count": applied_count, "list": [dict(r) for r in items]})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ── store visits ───────────────────────────────────────────

@app.route("/api/stores/<int:store_id>/visit/today")
@require_user
def check_visit_today(store_id):
    """Has there been a visit to this store today?"""
    db = get_db()
    try:
        today = __import__('datetime').date.today().isoformat()
        visit = db.execute(
            "SELECT id, items_count FROM store_visits WHERE store_id = ? AND household_id = ? AND visit_date = ?",
            (store_id, _hh(), today)
        ).fetchone()
        return jsonify({"active": dict(visit) if visit else None})
    finally:
        db.close()


@app.route("/api/stores/<int:store_id>/visit", methods=["POST"])
@require_user
def mark_visit(store_id):
    """Record a store visit for today."""
    db = get_db()
    try:
        today = __import__('datetime').date.today().isoformat()
        existing = db.execute(
            "SELECT id, items_count FROM store_visits WHERE store_id = ? AND household_id = ? AND visit_date = ?",
            (store_id, _hh(), today)
        ).fetchone()
        if existing:
            db.execute("UPDATE store_visits SET items_count = items_count + 1, created_at = NOW() WHERE id = ?", (existing["id"],))
        else:
            db.execute(
                "INSERT INTO store_visits (store_id, household_id, visit_date, items_count) VALUES (?, ?, ?, 1)",
                (store_id, _hh(), today)
            )
        db.execute("UPDATE stores SET planned_visit_date = NULL, planned_visit_by = NULL, visit_notified_users = '' WHERE id = ? AND household_id = ?", (store_id, _hh()))
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


@app.route("/api/suggestions")
@require_user
def get_suggestions():
    """Suggest items based on visit history (5+ visits required)."""
    db = get_db()
    try:
        stores = db.execute("SELECT id, name FROM stores WHERE household_id = ?", (_hh(),)).fetchall()

        suggestions = {}
        for s in stores:
            sid = s["id"]
            items = db.execute("""
                SELECT li.name, li.category, COUNT(DISTINCT sv.visit_date) as visit_count,
                       MAX(sv.visit_date) as last_visit,
                       (CURRENT_DATE - MAX(sv.visit_date)) as days_since
                FROM store_visits sv
                JOIN list_items li ON li.store_id = sv.store_id
                    AND li.household_id = sv.household_id
                    AND li.purchased = TRUE
                    AND li.purchased_at >= sv.visit_date::timestamp
                    AND li.purchased_at < (sv.visit_date::timestamp + INTERVAL '1 day')
                WHERE sv.store_id = ? AND sv.household_id = ?
                GROUP BY li.name, li.category
                HAVING COUNT(DISTINCT sv.visit_date) >= 5
                ORDER BY days_since DESC
                LIMIT 6
            """, (sid, _hh())).fetchall()

            # Filter out items already on the current list
            on_list = set(
                r["name"].lower() for r in
                db.execute("SELECT name FROM list_items WHERE store_id = ? AND household_id = ? AND purchased = FALSE", (sid, _hh())).fetchall()
            )

            store_suggestions = []
            for item in items:
                if item["name"].lower() not in on_list:
                    avg_interval = max(1, (365 * 4) / item["visit_count"])  # rough: 1 visit ~ every N days
                    days_s = float(item["days_since"] or 0)
                    store_suggestions.append({
                        "name": item["name"],
                        "times": item["visit_count"],
                        "days_since": round(days_s),
                        "avg_interval": round(avg_interval),
                    })
            if store_suggestions:
                suggestions[s["name"]] = store_suggestions
        return jsonify(suggestions)
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

# ---- Google OAuth (server-side redirect flow) ----
import secrets as _secrets
import urllib.parse as _urlparse
_OAUTH_STATES = {}

@app.route("/auth/google/redirect")
def auth_google_redirect():
    """Return HTML page that redirects to Google OAuth via JS — avoids Capacitor interception."""
    redirect_uri = 'https://grocerlist.app/auth/google/callback'
    intent_id = request.args.get("intent")
    state = ("intent_" + intent_id) if intent_id else _secrets.token_hex(16)
    _OAUTH_STATES[state] = time.time()
    now = time.time()
    for s in list(_OAUTH_STATES.keys()):
        if now - _OAUTH_STATES[s] > 600:
            del _OAUTH_STATES[s]
    
    auth_url = ('https://accounts.google.com/o/oauth2/v2/auth?'
        'client_id=' + authmod.GOOGLE_CLIENT_ID +
        '&redirect_uri=' + _urlparse.quote(redirect_uri, safe='') +
        '&response_type=code' +
        '&scope=openid%20email%20profile' +
        '&state=' + state +
        '&access_type=offline')
    
    # Return an HTML page that immediately redirects via JS
    # This keeps the navigation inside the WebView
    return ('<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>' +
            '<body style="text-align:center;font-family:sans-serif;padding-top:40px;color:#888">' +
            '<p>Redirecting to Google Sign-In...</p>' +
            '<script>window.location.replace("' + auth_url + '");</script>' +
            '</body></html>')

@app.route("/auth/google/callback")
def auth_google_callback():
    """Handle Google OAuth callback — exchange code for id_token, verify, set session."""
    import sys, traceback
    from urllib.request import urlopen, Request
    from urllib.parse import quote
    
    code = request.args.get('code', '')
    state = request.args.get('state', '')
    
    if not code:
        return '<h3>Login failed</h3><p>No authorization code received.</p><a href="/login">Try again</a>', 400
    
    try:
        # Exchange code for tokens
        redirect_uri = 'https://grocerlist.app/auth/google/callback'
        client_secret = os.environ.get('SSO_GOOGLE_CLIENT_SECRET', '')
        token_url = 'https://oauth2.googleapis.com/token'
        post_data = (
            'code=' + quote(code) +
            '&client_id=' + authmod.GOOGLE_CLIENT_ID +
            '&client_secret=' + client_secret +
            '&redirect_uri=' + quote(redirect_uri) +
            '&grant_type=authorization_code'
        )
        token_resp = urlopen(Request(token_url, data=post_data.encode(),
            headers={'Content-Type': 'application/x-www-form-urlencoded'}), timeout=10).read().decode()
        token_data = json.loads(token_resp)
        
        if 'error' in token_data:
            return '<h3>Login failed</h3><p>Google error: ' + token_data.get('error_description', token_data['error']) + '</p><a href="/login">Try again</a>', 500
        
        id_token_str = token_data.get('id_token', '')
        if not id_token_str:
            return '<h3>Login failed</h3><p>No ID token received.</p><a href="/login">Try again</a>', 500
        
        # Verify id_token
        info = id_token.verify_oauth2_token(id_token_str, google_requests.Request(), authmod.GOOGLE_CLIENT_ID)
        email = info.get('email', '')
        name = info.get('name', email.split('@')[0] if email else 'User')
        
        # Get or create user
        authmod._init_schema()
        user = authmod._one(
            f"SELECT id, google_id, email, name, household_id FROM {authmod._USERS} WHERE LOWER(email) = LOWER(?)", (email,))
        if not user:
            user = authmod._one(
                f"SELECT id, google_id, email, name, household_id FROM {authmod._USERS} WHERE google_id = ?", (info['sub'],))
        
        if not user:
            authmod._run(f"INSERT INTO {authmod._USERS} (google_id, email, name, household_id) VALUES (?,?,?,0)",
                         (info['sub'], email, name))
            user = authmod._one(
                f"SELECT id, email, name, household_id, google_id FROM {authmod._USERS} WHERE google_id = ?", (info['sub'],))
        
        hh_id = user.get('household_id', 0) if user else 0
        hh_name = ''
        
        if not hh_id:
            hh_count = authmod._one(f"SELECT COUNT(*) as cnt FROM {authmod._HH}", None)
            if hh_count and hh_count.get('cnt', 0) == 0:
                code_hh = _secrets.token_hex(4).upper()
                authmod._run(f"INSERT INTO {authmod._HH} (name, invite_code) VALUES (?,?)", ("Root Household", code_hh))
                hh = authmod._one(f"SELECT id, name FROM {authmod._HH} ORDER BY id DESC LIMIT 1", None)
                hh_id = hh['id'] if hh else 1
                hh_name = hh.get('name', 'Root Household') if hh else 'Root Household'
                authmod._run(f"UPDATE {authmod._USERS} SET household_id = ? WHERE id = ?", (hh_id, user['id']))
            else:
                authmod._set(user['id'], email, name, 0, '')
                return ('<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>' +
                        '<body style="text-align:center;font-family:sans-serif;padding-top:40px">' +
                        "<script>window.location.replace(\'/login?needs_signup=1\');</script></body></html>")
        
        if hh_id and not hh_name:
            hh = authmod._one(f"SELECT name FROM {authmod._HH} WHERE id = ?", (hh_id,))
            hh_name = hh.get('name', '') if hh else ''
        

        authmod._set(user["id"], email, name, hh_id, hh_name)
        
        if state.startswith("intent_"):
            intent_id = state.split("intent_")[1]
            authmod._run("INSERT INTO login_intents (id, user_id) VALUES (?, ?)", (intent_id, user["id"]))
            return f"""<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Authentication Successful</title></head>
            <body style="text-align:center;font-family:sans-serif;padding-top:40px;background:#f0f4ed;color:#2c2c2c;">
                <h2>✅ Authentication Successful</h2>
                <p style="color:#888;margin-top:20px;">Redirecting to ListMate...</p>
                <p style="margin-top:15px;"><a href="listmate://sso_callback" style="color:#2563eb;font-weight:bold;text-decoration:underline;">Tap here if you are not automatically redirected</a></p>
                <script>
                    setTimeout(function() {{
                        try {{ window.location.href = "listmate://sso_callback"; }} catch(e) {{}}
                    }}, 100);
                </script>
            </body></html>"""
    
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return '<h3>Login failed</h3><p>Server error: ' + str(exc) + '</p><a href="/login">Try again</a>', 500


@app.route("/api/debug/migrate_owners")
def debug_migrate_owners():
    try:
        from shared.auth import _run
        _run("UPDATE auth_households SET owner_id = (SELECT id FROM auth_users WHERE auth_users.household_id = auth_households.id ORDER BY id ASC LIMIT 1) WHERE owner_id IS NULL")
        return "Migration successful!"
    except Exception as e:
        return str(e)


@app.route("/api/analytics", methods=["GET"])
@require_user
def get_analytics():
    db = get_db()
    try:
        hhid = _hh()
        # Get total trips (from store_visits)
        visits = db.execute("SELECT visit_date, items_count FROM store_visits WHERE household_id = ? AND visit_date >= CURRENT_DATE - INTERVAL '90 days' ORDER BY visit_date ASC", (hhid,)).fetchall()
        
        # Get top purchased items (from item_purchase_stats)
        top_items = db.execute("SELECT name, category, total_purchases FROM item_purchase_stats WHERE household_id = ? ORDER BY total_purchases DESC LIMIT 10", (hhid,)).fetchall()
        
        # Get top categories
        top_categories = db.execute("SELECT category, SUM(total_purchases) as count FROM item_purchase_stats WHERE household_id = ? GROUP BY category ORDER BY count DESC LIMIT 5", (hhid,)).fetchall()
        
        visits_list = []
        for v in visits:
            d = dict(v)
            if d.get("visit_date"):
                d["visit_date"] = str(d["visit_date"])
            visits_list.append(d)

        return jsonify({
            "ok": True,
            "visits": visits_list,
            "top_items": [dict(t) for t in top_items],
            "top_categories": [dict(c) for c in top_categories]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

@app.route("/api/analytics/ai", methods=["POST"])
@require_user
def get_analytics_ai():
    db = get_db()
    try:
        hhid = _hh()
        hh = authmod._one(f"SELECT is_premium FROM {authmod._HH} WHERE id = ?", (hhid,))
        is_premium = bool(hh.get("is_premium")) if hh else False
        if not is_premium:
            return jsonify({"error": "Premium required for AI insights"}), 403

        import datetime
        # Check cache
        cached = db.execute("SELECT insight_text, generated_at FROM ai_insights_cache WHERE household_id = ?", (hhid,)).fetchone()
        if cached:
            generated_at = cached["generated_at"]
            if isinstance(generated_at, str):
                try:
                    generated_at = datetime.datetime.fromisoformat(generated_at.replace("Z", "+00:00")).replace(tzinfo=None)
                except ValueError:
                    generated_at = datetime.datetime.strptime(generated_at, "%Y-%m-%d %H:%M:%S")
            if (datetime.datetime.utcnow() - generated_at).days < 7:
                next_date = (generated_at + datetime.timedelta(days=7)).strftime("%B %d, %Y")
                # Return cached content if within 7 days
                return jsonify({"ok": True, "insight": cached["insight_text"], "cached": True, "next_date": next_date})

        # Generate new insight
        recent_visits = db.execute("SELECT s.name as store, v.visit_date, v.items_count FROM store_visits v JOIN stores s ON s.id = v.store_id WHERE v.household_id = ? AND v.visit_date >= CURRENT_DATE - INTERVAL '28 days' ORDER BY v.visit_date DESC", (hhid,)).fetchall()
        top_items = db.execute("SELECT name, total_purchases FROM item_purchase_stats WHERE household_id = ? ORDER BY total_purchases DESC LIMIT 5", (hhid,)).fetchall()

        if not recent_visits and not top_items:
            insight = "Not enough data yet. Complete a few grocery trips to unlock personalized money-saving insights!"
            return jsonify({"ok": True, "insight": insight})

        prompt = """Act as a financial and household planner. Analyze the following grocery shopping trip data. Compare the household's behavior from the last 7 days against the previous 3 weeks to identify emerging trends, changes in trip frequency, or new spending habits. Provide genuine, actionable money-saving tips and shopping optimization insights based on this trend analysis. Be concise (under 300 words).

Step 1: Formulate your advice strictly on their real-world grocery habits. Highlight how their recent week compares to their historical baseline (e.g., more frequent small trips, or successfully consolidating trips).
Step 2: Review your advice against the ListMate app features below.
Step 3: You may weave in a MAXIMUM OF ONE OR TWO ListMate features into your final response, and ONLY if they naturally solve a specific problem you identified in Step 1. Do not sound like an advertisement.

ListMate Features available to mention (CHOOSE UP TO 2 MAXIMUM):
- Store-Specific Lists (organize items by store)
- Plan Trip (set a target date for your next visit)
- Recipe Planner & Chef AI (generate recipes to use up ingredients)
- Shared Households (sync with family members to avoid duplicate buying)
- Quick Add (easily drop items into lists)
- Analytics Dashboard (view shopping habits)
"""

        import datetime
        now = datetime.datetime.utcnow().date()
        last_7_days = []
        prior_weeks = []
        
        for v in recent_visits:
            v_date = v['visit_date']
            if isinstance(v_date, str):
                try:
                    v_date = datetime.datetime.strptime(v_date.split(" ")[0], "%Y-%m-%d").date()
                except:
                    v_date = now
            elif isinstance(v_date, datetime.datetime):
                v_date = v_date.date()
                
            if (now - v_date).days <= 7:
                last_7_days.append(v)
            else:
                prior_weeks.append(v)

        prompt += "\nTrips in the Last 7 Days:\n"
        if not last_7_days:
            prompt += "- No trips recorded\n"
        for v in last_7_days:
            prompt += f"- {v['visit_date']}: {v['store']} ({v['items_count']} items)\n"
            
        prompt += "\nTrips in the Prior 3 Weeks:\n"
        if not prior_weeks:
            prompt += "- No trips recorded\n"
        for v in prior_weeks:
            prompt += f"- {v['visit_date']}: {v['store']} ({v['items_count']} items)\n"
            
        prompt += "\nTop Purchased Items (All Time):\n"
        for t in top_items:
            prompt += f"- {t['name']} ({t['total_purchases']} times)\n"
        

        import os
        import json
        import urllib.request
        key = ""
        for var in ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"]:
            k = os.environ.get(var, "").strip()
            if k and not k.startswith("dev-") and not k.startswith("secret-"):
                key = k
                break
        
        if not key:
            return jsonify({"error": "Gemini API key not configured"}), 500
        
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "systemInstruction": {"role": "system", "parts": [{"text": "You are a frugal shopping expert. Your goal is to provide helpful, actionable grocery shopping insights while actively promoting the user's digital grocery list app features (like store-specific lists, recipe planning, and trip planning) over physical methods like whiteboards or paper."}]}
        }
        model_name = __import__("os").environ.get("GEMINI_MODEL_NAME", "gemini-3.1-flash-lite,gemini-flash-latest").split(",")[0].strip()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": key,
                "User-Agent": "aistudio-build"
            }
        )
        insight_text = "Analysis completed."
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                candidates = data.get("candidates", [])
                if candidates:
                    insight_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
        except Exception as e:
            print(f"[GEMINI ERROR] Call to {model_name} failed: {e}", flush=True)
            return jsonify({"error": "AI generation failed: " + str(e)}), 500

        
        # Save to cache
        db.execute("""
            INSERT INTO ai_insights_cache (household_id, insight_text, generated_at)
            VALUES (?, ?, NOW())
            ON CONFLICT (household_id)
            DO UPDATE SET insight_text = EXCLUDED.insight_text, generated_at = NOW()
        """, (hhid, insight_text))
        db.commit()
        return jsonify({"ok": True, "insight": insight_text, "cached": False})
    except Exception as e:
        return jsonify({"error": "AI generation failed: " + str(e)}), 500
    finally:
        db.close()

if __name__ == "__main__":
    from db_pg import init_db
    init_db()
    app.run(host="0.0.0.0", port=3000, debug=True)


