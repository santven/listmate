#!/usr/bin/env python3
"""Listmate auth module — Google SSO + household management.
Self-contained: no dependencies on external paths or services."""

import os, sqlite3, json
from urllib.parse import urlencode
from functools import wraps

from flask import request, jsonify, session, redirect, current_app, send_from_directory
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

# ── Config ──────────────────────────────────────────────────
AUTH_DB = os.environ.get("AUTH_DB", "listmate_auth.db")
GOOGLE_CLIENT_ID = os.environ.get("SSO_GOOGLE_CLIENT_ID",
    "526061928190-8si99s2n17u7onf8mo2uapfjphtopnc1.apps.googleusercontent.com")
COOKIE_NAME = "listmate_session"
COOKIE_SECURE = False

# ── DB helpers ──────────────────────────────────────────────

def _get_db():
    db = sqlite3.connect(AUTH_DB)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def _init_db():
    db = _get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            google_id TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL,
            name TEXT NOT NULL,
            household_id INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS households (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            invite_code TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS feature_flags (
            user_id INTEGER NOT NULL,
            feature TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, feature),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
        CREATE INDEX IF NOT EXISTS idx_users_household ON users(household_id);
    """)
    db.commit()
    db.close()

_init_db()

# ── Session helpers ─────────────────────────────────────────

def install(app, cookie_name="family_session", cookie_secure=False):
    """Install auth on a Flask app — set cookie config."""
    global COOKIE_NAME, COOKIE_SECURE
    COOKIE_NAME = cookie_name
    COOKIE_SECURE = cookie_secure
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-in-production")
    app.config["PERMANENT_SESSION_LIFETIME"] = __import__("datetime").timedelta(days=30)


def _set_session(user_id, email, name, household_id, household_name):
    session[COOKIE_NAME] = {
        "user_id": user_id,
        "email": email,
        "name": name,
        "household_id": household_id,
        "household_name": household_name,
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
    if not uid:
        return False
    db = _get_db()
    row = db.execute(
        "SELECT enabled FROM feature_flags WHERE user_id = ? AND feature = ?",
        (uid, feature_name),
    ).fetchone()
    db.close()
    return bool(row and row["enabled"])


def require_feature(feature_name):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not is_logged_in():
                return jsonify({"error": "Login required"}), 401
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
            info = id_token.verify_oauth2_token(
                credential, google_requests.Request(), GOOGLE_CLIENT_ID
            )
        except Exception as e:
            return jsonify({"error": f"Invalid token: {str(e)}"}), 401

        google_id = info["sub"]
        email = info.get("email", "")
        name = info.get("name", email.split("@")[0])

        db = _get_db()
        user = db.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone()

        if not user:
            db.execute(
                "INSERT INTO users (google_id, email, name, household_id) VALUES (?, ?, ?, 0)",
                (google_id, email, name),
            )
            db.commit()
            user = db.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone()
            db.close()
            _set_session(user["id"], email, name, 0, "")
            return jsonify({"ok": True, "new_user": True, "needs_signup": True})

        db.close()

        hh_name = ""
        if user["household_id"]:
            hh = _get_db().execute(
                "SELECT name FROM households WHERE id = ?", (user["household_id"],)
            ).fetchone()
            hh_name = hh["name"] if hh else ""

        _set_session(user["id"], email, name, user["household_id"], hh_name)
        return jsonify({
            "ok": True, "name": name, "email": email,
            "household_id": user["household_id"], "household_name": hh_name,
        })

    # Alias: login pages call /api/auth/login
    @app.route("/api/auth/login", methods=["POST"])
    def auth_login():
        return auth_google()

    # Config endpoint — returns client_id and current user
    @app.route("/api/auth/config")
    def auth_config():
        resp = {"client_id": GOOGLE_CLIENT_ID}
        if is_logged_in():
            resp["display_name"] = get_display_name()
            resp["user"] = get_display_name().split(" ")[0].lower()  # "venkat" or "preethi"
            resp["user_info"] = {
                "id": get_user_id(),
                "name": get_display_name(),
                "email": get_email(),
                "household_id": get_household_id(),
                "household_name": get_household_name(),
            }
            # Feature flags
            uid = get_user_id()
            if uid:
                db = _get_db()
                flags = db.execute(
                    "SELECT feature, enabled FROM feature_flags WHERE user_id = ?",
                    (uid,)
                ).fetchall()
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
        if not is_logged_in():
            return jsonify({"error": "Login required"}), 401
        data = request.get_json(silent=True) or {}
        household_name = (data.get("household_name") or "").strip()
        invite_code = (data.get("invite_code") or "").strip()
        uid = get_user_id()

        db = _get_db()
        user = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if not user:
            db.close()
            return jsonify({"error": "User not found"}), 404
        if user["household_id"] != 0:
            db.close()
            return jsonify({"error": "Already in a household"}), 400

        if invite_code:
            hh = db.execute("SELECT * FROM households WHERE invite_code = ?", (invite_code,)).fetchone()
            if not hh:
                db.close()
                return jsonify({"error": "Invalid invite code"}), 404
            db.execute("UPDATE users SET household_id = ? WHERE id = ?", (hh["id"], uid))
            db.commit()
            db.close()
            _set_session(uid, user["email"], user["name"], hh["id"], hh["name"])
            return jsonify({"ok": True, "household_id": hh["id"], "household_name": hh["name"]})

        if not household_name:
            db.close()
            return jsonify({"error": "household_name or invite_code required"}), 400

        import secrets
        code = secrets.token_hex(4).upper()
        db.execute("INSERT INTO households (name, invite_code) VALUES (?, ?)", (household_name, code))
        hhid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("UPDATE users SET household_id = ? WHERE id = ?", (hhid, uid))
        db.commit()
        db.close()
        _set_session(uid, user["email"], user["name"], hhid, household_name)
        return jsonify({"ok": True, "household_id": hhid, "household_name": household_name, "invite_code": code})

    @app.route("/api/auth/household")
    def auth_household():
        if not is_logged_in():
            return jsonify({"error": "Login required"}), 401
        hhid = get_household_id()
        uid = get_user_id()
        if not hhid:
            return jsonify({"error": "No household"}), 404
        db = _get_db()
        hh = db.execute("SELECT * FROM households WHERE id = ?", (hhid,)).fetchone()
        members = db.execute("SELECT id, name, email FROM users WHERE household_id = ?", (hhid,)).fetchall()
        db.close()
        return jsonify({
            "ok": True,
            "household": {
                "id": hh["id"],
                "name": hh["name"],
                "invite_code": hh["invite_code"],
            },
            "members": [
                {
                    "user_id": m["id"],
                    "email": m["email"],
                    "display_name": m["name"],
                    "role": "owner" if m["id"] == uid else "member",
                }
                for m in members
            ],
            "current_user_id": uid,
            "is_owner": True,  # First member is always owner for now
        })

    @app.route("/api/auth/household/members", methods=["POST"])
    def auth_add_member():
        if not is_logged_in():
            return jsonify({"error": "Login required"}), 401
        hhid = get_household_id()
        if not hhid:
            return jsonify({"error": "No household"}), 400

        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        if not email:
            return jsonify({"error": "Email required"}), 400

        db = _get_db()
        # Find user by email
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user:
            # Pre-create a placeholder — they'll link Google ID on first login
            db.execute(
                "INSERT INTO users (google_id, email, name, household_id) VALUES (?, ?, ?, ?)",
                (f"pending:{email}", email, email.split("@")[0], hhid),
            )
        else:
            if user["household_id"] == hhid:
                db.close()
                return jsonify({"ok": True, "already_added": True})
            db.execute("UPDATE users SET household_id = ? WHERE id = ?", (hhid, user["id"]))

        db.commit()
        db.close()
        return jsonify({"ok": True})
