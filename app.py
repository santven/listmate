#!/usr/bin/env python3
"""Listmate — store-specific grocery list for households.
Each household's data is completely isolated by household_id on every query.
Uses SQLite locally; switches to PostgreSQL when DATABASE_URL is set."""
import os, json, sys, time, re, urllib.request
from functools import wraps
from urllib.parse import quote, urlencode

from flask import Flask, request, jsonify, session, redirect, send_from_directory
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

import shared.auth as authmod
from shared.auth import (
    install as install_auth, register_auth_routes,
    require_user, get_user_id, get_display_name,
    get_household_id, get_household_name, get_email, is_logged_in,
)

from categorize import categorize

from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__, static_folder="static")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)
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
        prem_type = "BOOLEAN DEFAULT FALSE" if _use_pg else "INTEGER DEFAULT 0"
        
        for col, ctype in [
            ("dietary_restrictions", col_type),
            ("zip_code", col_type),
            ("country", col_type),
            ("is_premium", prem_type)
        ]:
            try:
                if _use_pg:
                    authmod._exec(f"ALTER TABLE {authmod._HH} ADD COLUMN IF NOT EXISTS {col} {ctype}")
                else:
                    authmod._exec(f"ALTER TABLE {authmod._HH} ADD COLUMN {col} {ctype}")
            except Exception:
                pass

        store_tables = [
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
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_stores_hh_name ON stores(household_id, name)""",
            """CREATE INDEX IF NOT EXISTS idx_li_store ON list_items(store_id, household_id, purchased)""",
            """CREATE INDEX IF NOT EXISTS idx_sv_store ON store_visits(store_id, household_id, visit_date)""",
            """CREATE INDEX IF NOT EXISTS idx_si_store_name ON store_items(household_id, store_id, name)""",
        ]
        for stmt in store_tables:
            try: authmod._exec(stmt)
            except Exception: pass

        try:
            from db_pg import init_db as init_store_db
            init_store_db()
        except Exception:
            pass
    except Exception:
        pass

@app.before_request
def _check_migration():
    _ensure_schema()

# Database: PostgreSQL on Render (DATABASE_URL), SQLite locally
_DATABASE_URL = os.environ.get("DATABASE_URL") or ""
_use_pg = "postgres" in _DATABASE_URL.lower() or "RENDER" in os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
if _use_pg:
    import db_pg as dbmod
else:
    import db as dbmod


def get_db():
    return dbmod.get_db()


def close_db(conn):
    if _DATABASE_URL:
        dbmod.close_db(conn)
    else:
        conn.close()


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
                    if email:
                        user = authmod._one(f"SELECT id, google_id, email, name, household_id FROM {authmod._USERS} WHERE LOWER(email) = LOWER(?)", (email,))
                    if not user:
                        user = authmod._one(f"SELECT id, google_id, email, name, household_id FROM {authmod._USERS} WHERE google_id = ?", (gid_alias,))
                        
                    if not user:
                        authmod._run(f"INSERT INTO {authmod._USERS} (google_id, email, name, household_id) VALUES (?,?,?,0)", (gid_alias, email, name))
                        user = authmod._one(f"SELECT id, email, name, household_id, google_id FROM {authmod._USERS} WHERE google_id = ?", (gid_alias,))
                    
                    if user:
                        hh_id = user.get("household_id", 0)
                        hh_name = ""
                        if not hh_id:
                            hh_count = authmod._one(f"SELECT COUNT(*) as cnt FROM {authmod._HH}", None)
                            if hh_count and hh_count.get("cnt", 0) == 0:
                                code = secrets.token_hex(4).upper()
                                prem_val = True if _use_pg else 1
                                authmod._exec(f"INSERT INTO {authmod._HH} (name, invite_code, is_premium, subscription_status) VALUES (?,?,?,?)", ("Root Household", code, prem_val, "premium"))
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
    return f"""<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Authentication Successful</title></head><body style="text-align:center;font-family:sans-serif;padding-top:40px;background:#f0f4ed;color:#2c2c2c;"><h2>✅ Authentication Successful</h2><p style="color:#888;margin-top:20px;">Redirecting to ListMate...</p><script>function proceed(){{window.location.replace("{target_url}");}}if(window.opener && window.opener !== window){{try{{window.close();}}catch(e){{}}setTimeout(proceed, 500);}}else{{proceed();}}</script></body></html>"""


@app.route("/login_google_native", methods=["POST"])
def login_google_native():
    c = request.form.get("credential")
    intent_id = request.form.get("intent")
    try:
        from google.oauth2 import id_token
        import google.auth.transport.requests as google_requests
        info = id_token.verify_oauth2_token(c, google_requests.Request(), CLIENT_ID)
        gid = info["sub"]
        email = info.get("email", "")
        name = info.get("name") or (email.split("@")[0] if email else "User")
        
        import shared.auth as authmod
        authmod._init_schema()
        user = authmod._one(f"SELECT id, google_id, email, name, household_id FROM {authmod._USERS} WHERE LOWER(email) = LOWER(?)", (email,))
        if not user:
            user = authmod._one(f"SELECT id, google_id, email, name, household_id FROM {authmod._USERS} WHERE google_id = ?", (gid,))
        if not user:
            authmod._run(f"INSERT INTO {authmod._USERS} (google_id, email, name, household_id) VALUES (?,?,?,0)", (gid, email, name))
            user = authmod._one(f"SELECT id, email, name, household_id, google_id FROM {authmod._USERS} WHERE google_id = ?", (gid,))
            
        if user:
            if user.get("google_id") != gid:
                authmod._run(f"UPDATE {authmod._USERS} SET google_id = ? WHERE id = ?", (gid, user["id"]))
            
            hh_id = user.get("household_id", 0)
            hh_name = ""
            if not hh_id:
                hh_count = authmod._one(f"SELECT COUNT(*) as cnt FROM {authmod._HH}", None)
                if hh_count and hh_count.get("cnt", 0) == 0:
                    import secrets
                    code = secrets.token_hex(4).upper()
                    prem_val = True if _use_pg else 1
                    authmod._exec(f"INSERT INTO {authmod._HH} (name, invite_code, is_premium, subscription_status) VALUES (?,?,?,?)", ("Root Household", code, prem_val, 'premium'))
                    hh = authmod._one(f"SELECT id, name FROM {authmod._HH} ORDER BY id DESC LIMIT 1", None)
                    hh_id = hh["id"] if hh else 1
                    hh_name = hh["name"] if hh else "Root Household"
                    authmod._run(f"UPDATE {authmod._USERS} SET household_id = ? WHERE id = ?", (hh_id, user["id"]))
            
            if hh_id and not hh_name:
                hh = authmod._one(f"SELECT name FROM {authmod._HH} WHERE id = ?", (hh_id,))
                hh_name = hh.get("name", "") if hh else ""
            
            authmod._set(user["id"], email, name, hh_id, hh_name)
            if intent_id:
                authmod._run("INSERT INTO login_intents (id, user_id) VALUES (?, ?)", (intent_id, user["id"]))
                
            if hh_id == 0:
                return '''<!DOCTYPE html><html><head></head><body><script>window.location.replace('/login?needs_signup=1');</script></body></html>'''
                
            return '''<!DOCTYPE html><html><head></head><body><script>window.location.replace('/');</script></body></html>'''
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f'''<!DOCTYPE html><html><head></head><body><script>alert("Login failed"); window.location.replace('/login');</script></body></html>'''

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
@require_user
def settings_page():
    return send_from_directory("static", "settings.html")


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


@app.route("/api/webhooks/revenuecat", methods=["POST"])
def revenuecat_webhook():
    """Handle RevenueCat webhooks for downgrades on cancellation."""
    expected_token = os.environ.get("REVENUECAT_WEBHOOK_SECRET")
    if expected_token:
        auth_header = request.headers.get("Authorization")
        if auth_header not in [expected_token, f"Bearer {expected_token}"]:
            return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    event = data.get("event", {})
    evt_type = event.get("type")

    # If the user cancels or their subscription expires, downgrade them
    if evt_type in ["CANCELLATION", "EXPIRATION"]:
        uid = event.get("app_user_id")
        if uid:
            try:
                uid_int = int(uid)
                user = authmod._one(f"SELECT household_id FROM {authmod._USERS} WHERE id = ?", (uid_int,))
                if user and user.get("household_id"):
                    hhid = user["household_id"]
                    val = False if authmod._use_pg else 0
                    authmod._run(f"UPDATE {authmod._HH} SET is_premium = ?, subscription_status = ? WHERE id = ?", (val, "free", hhid))
                    print(f"[Webhook] Downgraded household {hhid} due to {evt_type}")
            except Exception as e:
                print(f"[Webhook] Error processing downgrade: {e}")
                
    # If the user purchases or renews, upgrade them
    elif evt_type in ["INITIAL_PURCHASE", "RENEWAL", "UNCANCELLATION", "NON_RENEWING_PURCHASE"]:
        uid = event.get("app_user_id")
        if uid and uid.isdigit():  # Ensure it's not an anonymous ID
            try:
                uid_int = int(uid)
                user = authmod._one(f"SELECT household_id FROM {authmod._USERS} WHERE id = ?", (uid_int,))
                if user and user.get("household_id"):
                    hhid = user["household_id"]
                    val = True if authmod._use_pg else 1
                    authmod._run(f"UPDATE {authmod._HH} SET is_premium = ?, subscription_status = ? WHERE id = ?", (val, "premium", hhid))
                    print(f"[Webhook] Upgraded household {hhid} due to {evt_type}")
            except Exception as e:
                print(f"[Webhook] Error processing upgrade: {e}")

    return jsonify({"ok": True})

@app.route("/api/settings/premium", methods=["GET", "POST"])
@require_user
def premium_settings():
    """Get or set household premium status."""
    hhid = _hh()
    if not hhid:
        return jsonify({"error": "No household"}), 400
    authmod._init_schema()

    if request.method == "GET":
        hh = authmod._one(f"SELECT is_premium, subscription_status, trial_ends_at FROM {authmod._HH} WHERE id = ?", (hhid,))
        is_prem = bool(hh.get("is_premium")) if hh else False
        is_early = bool(hhid and int(hhid) <= 100)
        sub_status = hh.get("subscription_status", "free") if hh else "free"
        trial_ends_at = hh.get("trial_ends_at") if hh else None
        if trial_ends_at and hasattr(trial_ends_at, 'isoformat'):
            trial_ends_at = trial_ends_at.isoformat()
            
        if is_early and not is_prem:
            is_prem = True
            sub_status = "premium"
            val = True if _use_pg else 1
            authmod._run(f"UPDATE {authmod._HH} SET is_premium = ?, subscription_status = ? WHERE id = ?", (val, "premium", hhid))
        return jsonify({
            "is_premium": is_prem,
            "household_id": hhid,
            "is_early_adopter": is_early,
            "subscription_status": sub_status,
            "trial_ends_at": trial_ends_at
        })

    data = request.get_json(silent=True) or {}
    is_premium = bool(data.get("is_premium", False))
    val = is_premium if _use_pg else (1 if is_premium else 0)
    status = "active" if is_premium else "free"
    authmod._run(f"UPDATE {authmod._HH} SET is_premium = ?, subscription_status = ? WHERE id = ?", (val, status, hhid))
    is_early = bool(hhid and int(hhid) <= 100)
    return jsonify({
        "ok": True,
        "is_premium": is_premium or is_early,
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
    models_to_try = ["gemini-3.1-flash-lite", "gemini-flash-latest"]

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
        if _use_pg:
            db.execute("CREATE TABLE IF NOT EXISTS recipe_generations (id SERIAL PRIMARY KEY, household_id INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMP NOT NULL DEFAULT NOW())")
            row = db.execute("SELECT COUNT(*) as cnt FROM recipe_generations WHERE household_id = ? AND created_at >= ?", (hhid, start_of_week)).fetchone()
        else:
            db.execute("CREATE TABLE IF NOT EXISTS recipe_generations (id INTEGER PRIMARY KEY AUTOINCREMENT, household_id INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            if not _use_pg:
                db.commit()
            row = db.execute("SELECT COUNT(*) as cnt FROM recipe_generations WHERE household_id = ? AND created_at >= ?", (hhid, start_str)).fetchone()
        return row["cnt"] if row else 0
    except Exception as e:
        print(f"Error checking weekly recipe count: {e}")
        return 0


def _record_recipe_generation(db, hhid):
    try:
        if _use_pg:
            db.execute("INSERT INTO recipe_generations (household_id) VALUES (?)", (hhid,))
        else:
            db.execute("INSERT INTO recipe_generations (household_id) VALUES (?)", (hhid,))
            db.commit()
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
        return jsonify({
            "ok": True,
            "used": used,
            "limit": 7,
            "remaining": max(0, 7 - used)
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
    hh = authmod._one(f"SELECT is_premium, dietary_restrictions FROM {authmod._HH} WHERE id = ?", (hhid,))
    is_prem = bool(hh.get("is_premium")) if hh else False
    is_early = bool(hhid and int(hhid) <= 100)
    if not (is_prem or is_early):
        return jsonify({
            "error": "Recipe Planner is a Premium feature. Please upgrade to Premium in Settings.",
            "code": "PREMIUM_REQUIRED"
        }), 403

    db = get_db()
    try:
        used = _get_weekly_recipe_count(db, hhid)
        if used >= 7:
            return jsonify({
                "error": "Weekly limit reached (7 of 7 recipes generated this week). Quota resets on Sunday.",
                "code": "WEEKLY_LIMIT_REACHED",
                "used": used,
                "limit": 7,
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
                    "limit": 7,
                    "remaining": max(0, 7 - new_used)
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

        if _use_pg:
            cur = db.execute(
                "INSERT INTO recipes (household_id, title, description, prep_time, cook_time, servings, cuisine, dietary_tags, instructions, ingredients) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                (hhid, title, desc, prep, cook, servings, cuisine, tags_json, instr_json, ingr_json)
            )
            recipe_id = cur.fetchall()[0]["id"]
        else:
            cur = db.execute(
                "INSERT INTO recipes (household_id, title, description, prep_time, cook_time, servings, cuisine, dietary_tags, instructions, ingredients) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (hhid, title, desc, prep, cook, servings, cuisine, tags_json, instr_json, ingr_json)
            )
            db.commit()
            recipe_id = cur.lastrowid

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
        if not _use_pg:
            db.commit()
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
            quantity = (item.get("amount") or item.get("quantity") or "").strip()

            # Ensure store item exists for auto-complete, and copy its category
            cat_row = db.execute(
                "SELECT category FROM store_items WHERE store_id = ? AND household_id = ? AND LOWER(name) = LOWER(?)",
                (store_id, hhid, name),
            ).fetchone()

            if cat_row:
                category = cat_row["category"] if isinstance(cat_row, dict) else cat_row[0]
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
                "SELECT id, quantity, recipe_tag FROM list_items WHERE household_id = ? AND store_id = ? AND LOWER(name) = LOWER(?) AND purchased = FALSE",
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
                if not _use_pg:
                    db.commit()
                added_count += 1
            else:
                if _use_pg:
                    db.execute(
                        "INSERT INTO list_items (store_id, name, category, added_by, quantity, household_id, recipe_tag) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (store_id, name, category, user_name, quantity, hhid, recipe_title)
                    )
                else:
                    db.execute(
                        "INSERT INTO list_items (store_id, name, category, added_by, quantity, household_id, recipe_tag) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (store_id, name, category, user_name, quantity, hhid, recipe_title)
                    )
                    db.commit()
                added_count += 1
        return jsonify({"ok": True, "added_count": added_count, "recipe_title": recipe_title})
    finally:
        db.close()

@app.route("/logout")
def logout_page():
    """Log the user out and redirect to login."""
    session.clear()
    return redirect("/login")

@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "db": "pg" if _use_pg else "sqlite",
        "db_url_set": bool(_DATABASE_URL),
        "db_url_prefix": _DATABASE_URL[:25] + "..." if _DATABASE_URL else "EMPTY",
        "render_hostname": os.environ.get("RENDER_EXTERNAL_HOSTNAME", "not set"),
    })


@app.route("/<path:filename>")
def root_files(filename):
    if filename in ["sw.js", "manifest.json", "robots.txt"] or filename.startswith("icon-") or filename.endswith(".png"):
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
    try:
        stores = db.execute("SELECT * FROM stores WHERE household_id = ? ORDER BY name", (hh,)).fetchall()
        list_items = db.execute('''
            SELECT l.*, s.name as store_name, s.category_order as store_category_order
            FROM list_items l
            JOIN stores s ON l.store_id = s.id AND s.household_id = ?
            WHERE l.household_id = ?
            ORDER BY l.purchased ASC, s.name, COALESCE(NULLIF(l.category,''),'ZZZ'), l.name
        ''', (hh, hh)).fetchall()
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

        return jsonify({
            "stores": [dict(s) for s in stores],
            "list": [dict(r) for r in list_items],
            "recipes": recipes
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
            "SELECT * FROM stores WHERE household_id = ? ORDER BY name", (hh,)
        ).fetchall()
        return jsonify([dict(s) for s in stores])
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
            "SELECT id FROM store_items WHERE store_id = ? AND household_id = ? AND LOWER(name) = LOWER(?)",
            (store_id, _hh(), name),
        ).fetchone()
        if existing:
            # Update category if provided
            if category:
                db.execute("UPDATE store_items SET category = ? WHERE id = ?", (category, existing["id"]))
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

        row = db.execute("SELECT id FROM store_items WHERE store_id = ? AND household_id = ? AND LOWER(name) = LOWER(?)",
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
            ORDER BY l.purchased ASC, s.name, COALESCE(NULLIF(l.category,''),'ZZZ'), l.name
        """, (_hh(), _hh())).fetchall()
        return jsonify([dict(r) for r in items])
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
            "SELECT id FROM list_items WHERE store_id = ? AND household_id = ? AND LOWER(name) = LOWER(?) AND purchased = FALSE",
            (store_id, _hh(), name),
        ).fetchone()
        if existing:
            return jsonify({"ok": False, "duplicate": True, "existing_id": existing["id"]})

        # Ensure store item exists for auto-complete, and copy its category
        cat_row = db.execute(
            "SELECT category FROM store_items WHERE store_id = ? AND household_id = ? AND LOWER(name) = LOWER(?)",
            (store_id, _hh(), name),
        ).fetchone()
        existing_category = (cat_row["category"] if cat_row else "")

        if not cat_row:
            # Auto-categorize new item
            cat = categorize(name)
            try:
                db.execute(
                    "INSERT INTO store_items (household_id, store_id, name, category) VALUES (?, ?, ?, ?)",
                    (_hh(), store_id, name, cat),
                )
            except Exception:
                pass
            existing_category = cat

        quantity = (data.get("quantity") or "").strip()
        db.execute(
            "INSERT INTO list_items (household_id, store_id, name, category, quantity, added_by) VALUES (?, ?, ?, ?, ?, ?)",
            (_hh(), store_id, name, existing_category, quantity, get_display_name()),
        )
        db.commit()

        row = db.execute("SELECT id FROM list_items WHERE store_id = ? AND household_id = ? AND LOWER(name) = LOWER(?) AND purchased = FALSE ORDER BY id DESC LIMIT 1",
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

        # Move the item
        db.execute(
            "UPDATE list_items SET store_id = ? WHERE id = ? AND household_id = ?",
            (target_store_id, item_id, _hh()),
        )

        # Also ensure the item exists in the target store's catalog for autocomplete
        try:
            db.execute(
                "INSERT INTO store_items (household_id, store_id, name) VALUES (?, ?, ?)",
                (_hh(), target_store_id, item["name"]),
            )
        except Exception:
            pass

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
                            "SELECT id FROM list_items WHERE store_id = ? AND household_id = ? AND LOWER(name) = LOWER(?) AND purchased = FALSE",
                            (store_id, hh_id, name)
                        ).fetchone()
                        if not existing:
                            cat_row = db.execute(
                                "SELECT category FROM store_items WHERE store_id = ? AND household_id = ? AND LOWER(name) = LOWER(?)",
                                (store_id, hh_id, name)
                            ).fetchone()
                            existing_category = cat_row["category"] if cat_row else categorize(name)
                            db.execute(
                                "INSERT INTO list_items (household_id, store_id, name, category, quantity, added_by) VALUES (?, ?, ?, ?, ?, ?)",
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
            ORDER BY l.purchased ASC, s.name, COALESCE(NULLIF(l.category,''),'ZZZ'), l.name
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
            if _use_pg:
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
            else:
                items = db.execute("""
                    SELECT li.name, li.category, COUNT(DISTINCT sv.visit_date) as visit_count,
                           MAX(sv.visit_date) as last_visit,
                           julianday('now') - julianday(MAX(sv.visit_date)) as days_since
                    FROM store_visits sv
                    JOIN list_items li ON li.store_id = sv.store_id
                        AND li.household_id = sv.household_id
                        AND li.purchased = TRUE
                        AND li.purchased_at >= datetime(sv.visit_date)
                        AND li.purchased_at < datetime(sv.visit_date, '+1 day')
                    WHERE sv.store_id = ? AND sv.household_id = ?
                    GROUP BY LOWER(li.name)
                    HAVING visit_count >= 5
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
                authmod._exec(f"INSERT INTO {authmod._HH} (name, invite_code) VALUES (?,?)", ("Root Household", code_hh))
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

if __name__ == "__main__":
    from db import init_db
    init_db()
    app.run(host="0.0.0.0", port=3000, debug=True)


