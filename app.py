#!/usr/bin/env python3
"""Listmate — store-specific grocery list for households.
Each household's data is completely isolated by household_id on every query.
Uses SQLite locally; switches to PostgreSQL when DATABASE_URL is set."""
import os, json, sys, time
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

app = Flask(__name__, static_folder="static")
install_auth(app, cookie_name="listmate_session", cookie_secure=False)

CLIENT_ID = os.environ.get("SSO_GOOGLE_CLIENT_ID",
                           "526061928190-8si99s2n17u7onf8mo2uapfjphtopnc1.apps.googleusercontent.com")
DB_PATH = os.environ.get("DB_PATH", "listmate.db")

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

@app.route("/login")
def login_page():
    html = open(os.path.join(os.path.dirname(__file__), "static", "login.html")).read()
    return html.replace("CLIENT_ID_PLACEHOLDER", CLIENT_ID)


@app.route("/signup")
def signup_page():
    return redirect("/login")
@app.route("/privacy")
def privacy_page():
    return send_from_directory("static", "privacy.html")


@app.route("/settings")
@require_user
def settings_page():
    return send_from_directory("static", "settings.html")


@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "db": "pg" if _use_pg else "sqlite",
        "db_url_set": bool(_DATABASE_URL),
        "db_url_prefix": _DATABASE_URL[:25] + "..." if _DATABASE_URL else "EMPTY",
        "render_hostname": os.environ.get("RENDER_EXTERNAL_HOSTNAME", "not set"),
    })


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

@app.route("/api/stores")
@require_user
def list_stores():
    db = get_db()
    try:
        hh = _hh()
        stores = db.execute(
            "SELECT * FROM stores WHERE household_id = ? ORDER BY name", (hh,)
        ).fetchall()
        return jsonify(stores)
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
    db = get_db()
    try:
        db.execute(
            "INSERT OR IGNORE INTO stores (household_id, name) VALUES (?, ?)",
            (_hh(), name),
        )
        db.commit()
    finally:
        db.close()
    return jsonify({"ok": True})


# ── store items (household-scoped) ──

@app.route("/api/stores/<int:store_id>/items")
@require_user
def list_store_items(store_id):
    db = get_db()
    # Verify store belongs to this household
    store = db.execute(
        "SELECT id FROM stores WHERE id = ? AND household_id = ?",
        (store_id, _hh()),
    ).fetchone()
    if not store:
        db.close()
        return jsonify({"error": "not found"}), 404

    items = db.execute(
        "SELECT * FROM store_items WHERE store_id = ? AND household_id = ? ORDER BY COALESCE(NULLIF(category,''),'ZZZ'), name",
        (store_id, _hh()),
    ).fetchall()
    db.close()
    resp = jsonify([dict(r) for r in items])
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


@app.route("/api/stores/<int:store_id>/items", methods=["POST"])
@require_user
def add_store_item(store_id):
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    category = (data.get("category") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    db = get_db()
    # Verify store ownership
    store = db.execute(
        "SELECT id FROM stores WHERE id = ? AND household_id = ?",
        (store_id, _hh()),
    ).fetchone()
    if not store:
        db.close()
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
        db.close()
        return jsonify({"ok": True, "existing": True, "id": existing["id"]})

    # Auto-categorize if not provided
    if not category:
        category = categorize(name)

    db.execute(
        "INSERT INTO store_items (household_id, store_id, name, category) VALUES (?, ?, ?, ?)",
        (_hh(), store_id, name, category),
    )
    db.commit()
    rowid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.close()
    return jsonify({"ok": True, "id": rowid})


# ── grocery list (household-scoped) ──

@app.route("/api/list")
@require_user
def list_grocery():
    db = get_db()
    items = db.execute("""
        SELECT l.*, s.name as store_name
        FROM list_items l
        JOIN stores s ON l.store_id = s.id AND s.household_id = ?
        WHERE l.household_id = ?
        ORDER BY l.purchased ASC, s.name, COALESCE(NULLIF(l.category,''),'ZZZ'), l.name
    """, (_hh(), _hh())).fetchall()
    db.close()
    return jsonify([dict(r) for r in items])


@app.route("/api/list", methods=["POST"])
@require_user
def add_to_list():
    data = request.get_json(silent=True) or {}
    store_id = data.get("store_id")
    name = (data.get("name") or "").strip()
    if not name or not store_id:
        return jsonify({"error": "store_id and name required"}), 400
    db = get_db()

    # Verify store ownership
    store = db.execute(
        "SELECT id FROM stores WHERE id = ? AND household_id = ?",
        (store_id, _hh()),
    ).fetchone()
    if not store:
        db.close()
        return jsonify({"error": "store not found"}), 404

    existing = db.execute(
        "SELECT id FROM list_items WHERE store_id = ? AND household_id = ? AND LOWER(name) = LOWER(?) AND purchased = 0",
        (store_id, _hh(), name),
    ).fetchone()
    if existing:
        db.close()
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
        db.execute(
            "INSERT INTO store_items (household_id, store_id, name, category) VALUES (?, ?, ?, ?)",
            (_hh(), store_id, name, cat),
        )
        existing_category = cat

    try:
        db.execute(
            "INSERT INTO list_items (household_id, store_id, name, category, added_by) VALUES (?, ?, ?, ?, ?)",
            (_hh(), store_id, name, existing_category, get_display_name()),
        )
    except Exception:
        import traceback
        traceback.print_exc()
        db.close()
        return jsonify({"error": "Database error"}), 500
    db.commit()
    rowid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.close()
    return jsonify({"ok": True, "id": rowid})


@app.route("/api/list/<int:item_id>/toggle", methods=["POST"])
@require_user
def toggle_list_item(item_id):
    db = get_db()
    item = db.execute(
        "SELECT * FROM list_items WHERE id = ? AND household_id = ?",
        (item_id, _hh()),
    ).fetchone()
    if not item:
        db.close()
        return jsonify({"error": "not found"}), 404
    if item["purchased"]:
        db.execute("UPDATE list_items SET purchased=0, purchased_by=NULL, purchased_at=NULL WHERE id=?", (item_id,))
    else:
        db.execute(
            "UPDATE list_items SET purchased=1, purchased_by=?, purchased_at=datetime('now') WHERE id=?",
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
    db.close()
    return jsonify({"ok": True})


@app.route("/api/list/<int:item_id>", methods=["DELETE"])
@require_user
def delete_list_item(item_id):
    db = get_db()
    db.execute(
        "DELETE FROM list_items WHERE id = ? AND household_id = ?",
        (item_id, _hh()),
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/list/<int:item_id>/move", methods=["PUT"])
@require_user
def move_list_item(item_id):
    data = request.get_json(silent=True) or {}
    target_store_id = data.get("store_id")
    if not target_store_id:
        return jsonify({"error": "store_id required"}), 400

    db = get_db()
    # Verify item belongs to this household
    item = db.execute(
        "SELECT * FROM list_items WHERE id = ? AND household_id = ?",
        (item_id, _hh()),
    ).fetchone()
    if not item:
        db.close()
        return jsonify({"error": "not found"}), 404

    # Verify target store belongs to this household
    target = db.execute(
        "SELECT id FROM stores WHERE id = ? AND household_id = ?",
        (target_store_id, _hh()),
    ).fetchone()
    if not target:
        db.close()
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
        pass  # already exists

    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/list/clear", methods=["POST"])
@require_user
def clear_list():
    db = get_db()
    db.execute(
        "DELETE FROM list_items WHERE purchased = 0 AND household_id = ?",
        (_hh(),),
    )
    db.commit()
    db.close()
    return jsonify({"ok": True})


# ── store visits ───────────────────────────────────────────

@app.route("/api/stores/<int:store_id>/visit/today")
@require_user
def check_visit_today(store_id):
    """Has there been a visit to this store today?"""
    db = get_db()
    today = __import__('datetime').date.today().isoformat()
    visit = db.execute(
        "SELECT id, items_count FROM store_visits WHERE store_id = ? AND household_id = ? AND visit_date = ?",
        (store_id, _hh(), today)
    ).fetchone()
    db.close()
    return jsonify({"active": dict(visit) if visit else None})


@app.route("/api/stores/<int:store_id>/visit", methods=["POST"])
@require_user
def mark_visit(store_id):
    """Record a store visit for today."""
    db = get_db()
    today = __import__('datetime').date.today().isoformat()
    existing = db.execute(
        "SELECT id, items_count FROM store_visits WHERE store_id = ? AND household_id = ? AND visit_date = ?",
        (store_id, _hh(), today)
    ).fetchone()
    if existing:
        db.execute("UPDATE store_visits SET items_count = items_count + 1, created_at = datetime('now') WHERE id = ?", (existing["id"],))
    else:
        db.execute(
            "INSERT INTO store_visits (store_id, household_id, visit_date, items_count) VALUES (?, ?, ?, 1)",
            (store_id, _hh(), today)
        )
    db.commit()
    db.close()
    return jsonify({"ok": True})


@app.route("/api/suggestions")
@require_user
def get_suggestions():
    """Suggest items based on visit history (5+ visits required)."""
    db = get_db()
    stores = db.execute("SELECT id, name FROM stores WHERE household_id = ?", (_hh(),)).fetchall()

    suggestions = {}
    for s in stores:
        sid = s["id"]
        # Find items bought in >5 visits
        items = db.execute("""
            SELECT li.name, li.category, COUNT(DISTINCT sv.visit_date) as visit_count,
                   MAX(sv.visit_date) as last_visit,
                   julianday('now') - julianday(MAX(sv.visit_date)) as days_since
            FROM store_visits sv
            JOIN list_items li ON li.store_id = sv.store_id
                AND li.household_id = sv.household_id
                AND li.purchased = 1
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
            db.execute("SELECT name FROM list_items WHERE store_id = ? AND household_id = ? AND purchased = 0", (sid, _hh())).fetchall()
        )

        store_suggestions = []
        for item in items:
            if item["name"].lower() not in on_list:
                avg_interval = max(1, (365 * 4) / item["visit_count"])  # rough: 1 visit ~ every N days
                store_suggestions.append({
                    "name": item["name"],
                    "times": item["visit_count"],
                    "days_since": round(item["days_since"]),
                    "avg_interval": round(avg_interval),
                })

        if store_suggestions:
            suggestions[s["name"]] = store_suggestions

    db.close()
    return jsonify(suggestions)


if __name__ == "__main__":
    from db import init_db
    init_db()
    app.run(host="127.0.0.1", port=5003, debug=True)
# ---- Google OAuth (server-side redirect flow) ----
import secrets as _secrets
import urllib.parse as _urlparse
_OAUTH_STATES = {}

@app.route("/auth/google/redirect")
def auth_google_redirect():
    """Return HTML page that redirects to Google OAuth via JS — avoids Capacitor interception."""
    redirect_uri = 'https://grocerlist.app/auth/google/callback'
    state = _secrets.token_hex(16)
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
        return ('<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>' +
                '<body style="text-align:center;font-family:sans-serif;padding-top:40px">' +
                '<h2>&#x1F44D; Signed in</h2><p>Loading...</p>' +
                "<script>window.location.replace(\'/\');</script></body></html>")
    
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return '<h3>Login failed</h3><p>Server error: ' + str(exc) + '</p><a href="/login">Try again</a>', 500


