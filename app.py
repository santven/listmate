#!/usr/bin/env python3
"""Listmate — store-specific grocery list for households.
Each household's data is completely isolated by household_id on every query.
Uses SQLite locally; switches to PostgreSQL when DATABASE_URL is set."""
import os, json, sys
from functools import wraps

from flask import Flask, request, jsonify, session, redirect, send_from_directory

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
import sys, json as _json
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
    return send_from_directory("static", "signup.html")


@app.route("/settings")
@require_user
def settings_page():
    return send_from_directory("static", "settings.html")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


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
            "SELECT * FROM stores WHERE household_id = %s ORDER BY name", (hh,)
        ).fetchall()
        # Auto-seed if empty
        if not stores and hh:
            names = ["Costco","Whole Foods","Valli","Patel / IndiaCo","Jewel","Amazon"]
            for name in names:
                db.execute(
                    "INSERT INTO stores (household_id, name) VALUES (%s,%s)", (hh, name)
                )
            db.commit()
            stores = db.execute(
                "SELECT * FROM stores WHERE household_id = %s ORDER BY name", (hh,)
            ).fetchall()
        return jsonify(stores)
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

