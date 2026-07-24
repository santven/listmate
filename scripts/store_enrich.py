#!/usr/bin/env python3
"""
Store enrichment cron job for Render.
Runs every 15 minutes to enrich stores created in the last 15 minutes with items and cuisine metadata via Gemini AI.
Uses Gemini 3.1 Flash Lite and limits API calls to max 5 calls per minute (minimum 12 seconds between calls).
"""

import os
import sys
import json
import time
import re
import urllib.request
import urllib.error
from datetime import datetime

LOG_FILE = "/var/log/store_enrich.log"
try:
    os.makedirs(os.path.dirname(LOG_FILE) or ".", exist_ok=True)
except Exception:
    LOG_FILE = "store_enrich.log"

def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

def get_key():
    """Retrieve Gemini API key from SECRET_KEY environment variable (set in Render)."""
    key = os.environ.get("SECRET_KEY")
    if key and key.strip():
        return key.strip()

    key = os.environ.get("GEMINI_API_KEY")
    if key and key.strip():
        return key.strip()

    try:
        for path in ["/opt/shared/.env", ".env"]:
            if os.path.exists(path):
                for line in open(path):
                    if line.strip().startswith("SECRET_KEY="):
                        return line.split("=", 1)[1].strip().strip("'\"")
                    elif line.strip().startswith("GEMINI_API_KEY="):
                        return line.split("=", 1)[1].strip().strip("'\"")
    except Exception:
        pass

    return ""

# Rate Limiter State: Ensure max 5 calls per minute (at least 12s between calls)
MAX_CALLS_PER_MINUTE = 5
MIN_CALL_INTERVAL = 60.0 / MAX_CALLS_PER_MINUTE  # 12.0 seconds
_last_call_timestamp = 0.0

def gemini_query(prompt, key):
    """Query Gemini 3.1 Flash Lite API with strict rate limiting (max 5 calls/min)."""
    global _last_call_timestamp

    now = time.time()
    elapsed = now - _last_call_timestamp
    if elapsed < MIN_CALL_INTERVAL:
        sleep_needed = MIN_CALL_INTERVAL - elapsed
        log(f"Rate limiting: waiting {sleep_needed:.2f}s before Gemini call...")
        time.sleep(sleep_needed)

    _last_call_timestamp = time.time()

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 800,
            "temperature": 0.3
        }
    }

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": key
        }
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

def get_db():
    """Connect to DB — PostgreSQL on Render, SQLite locally."""
    dburi = os.environ.get("DATABASE_URL")
    if dburi:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(dburi)
        conn.autocommit = True
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        pg = True
    else:
        import sqlite3
        conn = sqlite3.connect(os.environ.get("DB_PATH", "listmate.db"))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        cur = conn
        pg = False
    return conn, cur, pg

def run_sql(cur, pg, sql, params=None):
    if pg:
        sql = re.sub(r'\?', '%s', sql)
        cur.execute(sql, params or ())
        try:
            return [dict(r) for r in cur.fetchall()] if cur.description else []
        except Exception:
            return []
    else:
        if params:
            rows = cur.execute(sql, params).fetchall()
        else:
            rows = cur.execute(sql).fetchall()
        return [dict(r) for r in rows]

def run_exec(cur, pg, sql, params=None):
    if pg:
        sql = re.sub(r'\?', '%s', sql)
        cur.execute(sql, params or ())
    else:
        cur.execute(sql, params or ())

def main():
    log("=== Starting Store Enrichment Job (Gemini 3.1 Flash Lite) ===")

    key = get_key()
    if not key:
        log("ERROR: No SECRET_KEY or GEMINI_API_KEY found in environment")
        return

    conn = None
    cur = None
    pg = False

    try:
        conn, cur, pg = get_db()

        # Query stores created in the last 15 minutes
        if pg:
            sql_stores = (
                "SELECT s.id AS store_id, s.name AS store_name, s.household_id, s.created_at "
                "FROM stores s "
                "WHERE s.created_at >= NOW() - INTERVAL '15 minutes' "
                "ORDER BY s.created_at DESC LIMIT 5"
            )
        else:
            sql_stores = (
                "SELECT s.id AS store_id, s.name AS store_name, s.household_id, s.created_at "
                "FROM stores s "
                "WHERE s.created_at >= datetime('now', '-15 minutes') "
                "ORDER BY s.created_at DESC LIMIT 5"
            )

        new_stores = run_sql(cur, pg, sql_stores)

        # Fallback to store_enrich_queue if table exists and no stores returned by created_at
        if not new_stores:
            try:
                queue_rows = run_sql(cur, pg,
                    "SELECT id AS queue_id, store_id, household_id FROM store_enrich_queue "
                    "WHERE status='pending' ORDER BY created_at LIMIT 5")
                for q in queue_rows:
                    st = run_sql(cur, pg, "SELECT id AS store_id, name AS store_name, household_id FROM stores WHERE id=?", (q["store_id"],))
                    if st:
                        st[0]["queue_id"] = q["queue_id"]
                        new_stores.append(st[0])
            except Exception:
                pass

        if not new_stores:
            log("No stores created in the last 15 minutes.")
            return

        log(f"Found {len(new_stores)} store(s) created in last 15 minutes to enrich.")

        for store in new_stores:
            sid = store["store_id"]
            sname = store["store_name"]
            hhid = store["household_id"]
            queue_id = store.get("queue_id")

            # Fetch zip_code, country, and dietary_restrictions for household
            hh_rows = run_sql(cur, pg,
                "SELECT zip_code, country, dietary_restrictions FROM auth_households WHERE id=?", (hhid,))

            zip_code = (hh_rows[0].get("zip_code") or "").strip() if hh_rows else ""
            country = (hh_rows[0].get("country") or "USA").strip() if hh_rows else "USA"
            dietary_raw = (hh_rows[0].get("dietary_restrictions") or "").strip() if hh_rows else ""

            # Format dietary restrictions note
            dietary_note = ""
            if dietary_raw:
                restrictions = [d.strip() for d in dietary_raw.split(",") if d.strip()]
                labels = {
                    "vegetarian": "vegetarian (no meat/fish/seafood)",
                    "vegan": "vegan (no animal products)",
                    "gluten_free": "gluten-free (no wheat/barley/rye)",
                    "halal": "halal (no pork/alcohol/non-halal meat)",
                    "kosher": "kosher",
                    "nut_free": "nut-free"
                }
                rlabels = [labels.get(r.lower(), r) for r in restrictions]
                dietary_note = f"CRITICAL: Household has dietary restrictions: {', '.join(rlabels)}. EXCLUDE any items violating these restrictions. "

            # Build Gemini prompt including 15 miles radius and intelligence for duplicate store names
            prompt = (
                f"Find stores named '{sname}' within 15 miles of zip code '{zip_code}' in country '{country}'. "
                f"If there are more than one store with the name '{sname}' within 15 miles, use your intelligence and provide a response for the most relevant store location. "
                f"What cuisine or store type is it? What are the top 25 items commonly bought at this store? "
                f"{dietary_note}"
                f"Return valid JSON only in this exact format: {{\"cuisine\": \"...\", \"items\": [\"item1\", \"item2\", ...]}}"
            )

            log(f"Processing store '{sname}' (id={sid}, zip={zip_code or 'N/A'}, country={country}, dietary={dietary_raw or 'none'})")

            try:
                result = gemini_query(prompt, key)
                candidates = result.get("candidates", [])
                if not candidates:
                    log(f"  ✗ No response candidates for '{sname}'")
                    continue

                text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                tokens = result.get("usageMetadata", {}).get("totalTokenCount", "?")
                log(f"  Gemini response received ({tokens} tokens)")

                # Clean markdown JSON block formatting if present
                text = text.strip()
                if text.startswith("```"):
                    text = re.sub(r'^```(?:json)?\s*', '', text)
                    text = re.sub(r'```\s*$', '', text)

                data = json.loads(text)
                cuisine = (data.get("cuisine") or "").strip()
                items = data.get("items", [])[:25]

                # Update cuisine in stores table if column exists
                try:
                    run_exec(cur, pg, "UPDATE stores SET cuisine=?, auto_populated=? WHERE id=?", (cuisine, True, sid))
                except Exception:
                    pass

                # Insert items into store_items table and link to correct store & household
                added = 0
                for item_name in items:
                    item_clean = str(item_name).strip()
                    if not item_clean:
                        continue

                    # Check if item already exists for this store to prevent duplicate seeding
                    existing = run_sql(cur, pg,
                        "SELECT id FROM store_items WHERE store_id=? AND LOWER(name)=LOWER(?) AND household_id=?",
                        (sid, item_clean, hhid))

                    if not existing:
                        run_exec(cur, pg,
                            "INSERT INTO store_items (store_id, name, category, household_id) VALUES (?, ?, ?, ?)",
                            (sid, item_clean, "gemini_auto", hhid))
                        added += 1

                # Update queue status if queue_id exists
                if queue_id:
                    try:
                        run_exec(cur, pg, "UPDATE store_enrich_queue SET status='done', processed_at=NOW() WHERE id=?", (queue_id,))
                    except Exception:
                        pass

                if not pg and conn:
                    conn.commit()

                log(f"  ✓ Added {added} items to store_items for store '{sname}' (cuisine='{cuisine}')")

            except Exception as e:
                log(f"  ✗ Error processing store '{sname}': {e}")
                if queue_id:
                    try:
                        run_exec(cur, pg, "UPDATE store_enrich_queue SET status='failed', processed_at=NOW() WHERE id=?", (queue_id,))
                    except Exception:
                        pass
                if not pg and conn:
                    conn.commit()

    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        log("=== Store Enrichment Job Complete ===")

if __name__ == "__main__":
    main()
