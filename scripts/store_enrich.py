#!/usr/bin/env python3
"""Store enrichment cron job for Render.
Runs every 15 minutes to enrich stores created in the last 15 minutes or queued for premium households.
Uses Gemini 3.1 Flash Lite. Batches up to 10 pending stores into a SINGLE Gemini API call!
"""

import os
import sys
import json
import time
import re
import urllib.request
import urllib.error
from datetime import datetime

# Add root directory to sys.path so we can import categorize module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    import categorize
except Exception:
    categorize = None

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
    """Retrieve Gemini API key from GEMINI_API_KEY environment variable (or SECRET_KEY if valid Google key starting with AIza)."""
    key = os.environ.get("GEMINI_API_KEY")
    if key and key.strip():
        return key.strip()

    key = os.environ.get("SECRET_KEY")
    if key and key.strip() and key.strip().startswith("AIza"):
        return key.strip()

    try:
        for path in ["/opt/shared/.env", ".env"]:
            if os.path.exists(path):
                for line in open(path):
                    if line.strip().startswith("GEMINI_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip("'").strip('"')
                        if val:
                            return val
                    elif line.strip().startswith("SECRET_KEY="):
                        val = line.split("=", 1)[1].strip().strip("'").strip('"')
                        if val and val.startswith("AIza"):
                            return val
    except Exception:
        pass

    return ""

def gemini_query(prompt, key):
    """Query Gemini 3.1 Flash Lite API with 6000 output tokens max for multi-store batching."""
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 6000,
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
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8")
        except Exception:
            pass
        raise RuntimeError(f"HTTP Error {e.code}: {e.reason} — {err_body}")

def determine_category(item_name, gemini_cat=""):
    """Determine proper item category using categorize matcher + Gemini fallback."""
    if categorize:
        try:
            cat = categorize.categorize(item_name)
            if cat and cat.strip():
                return cat.strip()
        except Exception:
            pass

    if gemini_cat and str(gemini_cat).strip():
        gcat = str(gemini_cat).strip().title()
        if gcat.lower() not in ["gemini_auto", "auto", "unknown", "none", "null"]:
            return gcat

    return "General"

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
    log("=== Starting Store Enrichment Job (Batched Gemini API) ===")
    key = get_key()
    if not key:
        log("ERROR: No GEMINI_API_KEY found in environment")
        return

    conn = None
    cur = None
    pg = False
    try:
        conn, cur, pg = get_db()

        # Query up to 10 stores created in the last 15 minutes for premium households
        if pg:
            sql_stores = (
                "SELECT s.id AS store_id, s.name AS store_name, s.household_id, s.created_at "
                "FROM stores s "
                "JOIN auth_households h ON s.household_id = h.id "
                "WHERE s.created_at >= NOW() - INTERVAL '15 minutes' "
                "AND h.is_premium = TRUE "
                "ORDER BY s.created_at DESC LIMIT 10"
            )
        else:
            sql_stores = (
                "SELECT s.id AS store_id, s.name AS store_name, s.household_id, s.created_at "
                "FROM stores s "
                "JOIN auth_households h ON s.household_id = h.id "
                "WHERE s.created_at >= datetime('now', '-15 minutes') "
                "AND h.is_premium = 1 "
                "ORDER BY s.created_at DESC LIMIT 10"
            )

        new_stores = run_sql(cur, pg, sql_stores)
        seen_store_ids = {s["store_id"] for s in new_stores}

        # Fallback to store_enrich_queue if fewer than 10 stores returned
        if len(new_stores) < 10:
            try:
                limit_needed = 10 - len(new_stores)
                if pg:
                    sql_queue = (
                        "SELECT q.id AS queue_id, q.store_id, q.household_id "
                        "FROM store_enrich_queue q "
                        "JOIN auth_households h ON q.household_id = h.id "
                        "WHERE q.status='pending' AND h.is_premium = TRUE "
                        "ORDER BY q.created_at LIMIT %s" % limit_needed
                    )
                else:
                    sql_queue = (
                        "SELECT q.id AS queue_id, q.store_id, q.household_id "
                        "FROM store_enrich_queue q "
                        "JOIN auth_households h ON q.household_id = h.id "
                        "WHERE q.status='pending' AND h.is_premium = 1 "
                        "ORDER BY q.created_at LIMIT %d" % limit_needed
                    )
                queue_rows = run_sql(cur, pg, sql_queue)
                for q in queue_rows:
                    sid = q["store_id"]
                    if sid not in seen_store_ids:
                        st = run_sql(cur, pg, "SELECT id AS store_id, name AS store_name, household_id FROM stores WHERE id=?", (sid,))
                        if st:
                            st[0]["queue_id"] = q["queue_id"]
                            new_stores.append(st[0])
                            seen_store_ids.add(sid)
            except Exception:
                pass

        if not new_stores:
            log("No stores needing enrichment for premium households.")
            return

        log(f"Found {len(new_stores)} store(s) to enrich. Building single batched Gemini request...")

        # Gather household metadata for each store
        prompt_stores = []
        for idx, store in enumerate(new_stores, 1):
            sid = store["store_id"]
            sname = store["store_name"]
            hhid = store["household_id"]

            hh_rows = run_sql(cur, pg,
                "SELECT zip_code, country, dietary_restrictions FROM auth_households WHERE id=?", (hhid,))
            zip_code = (hh_rows[0].get("zip_code") or "").strip() if hh_rows else ""
            country = (hh_rows[0].get("country") or "USA").strip() if hh_rows else "USA"
            dietary_raw = (hh_rows[0].get("dietary_restrictions") or "").strip() if hh_rows else ""

            store["zip_code"] = zip_code
            store["country"] = country
            store["dietary_raw"] = dietary_raw

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
                dietary_note = f"Dietary restrictions: {', '.join(rlabels)}. EXCLUDE any violating items. "

            prompt_stores.append(
                f"Store #{idx}:\n"
                f"- store_id: {sid}\n"
                f"- name: \"{sname}\"\n"
                f"- location: within 15 miles of zip code \"{zip_code or 'N/A'}\", country \"{country}\"\n"
                f"- {dietary_note}".strip()
            )

        stores_block = "\n\n".join(prompt_stores)

        prompt = (
            f"Below is a list of {len(new_stores)} grocery/retail store(s) to enrich. For EACH store, identify its cuisine/store type, and list top 25 commonly bought items that strictly adhere to any specified dietary restrictions.\n\n"
            f"{stores_block}\n\n"
            f"Categorize each item under a standard category (e.g., Produce, Dairy, Bakery, Meat & Seafood, Pantry, Legumes & Grains, Spices & Seasonings, Snacks & Sweets, Beverages, Frozen, Household, Canned & Jarred, Nuts & Seeds, Dips & Spreads, Indian Specialties, General).\n"
            f"Return valid JSON ONLY as an object with a \"stores\" array containing an entry for EVERY store:\n"
            f"{{\n"
            f"  \"stores\": [\n"
            f"    {{\n"
            f"      \"store_id\": <store_id_number>,\n"
            f"      \"cuisine\": \"...\",\n"
            f"      \"items\": [\n"
            f"        {{\"name\": \"item1\", \"category\": \"Produce\"}}\n"
            f"      ]\n"
            f"    }}\n"
            f"  ]\n"
            f"}}\n"
        )

        try:
            result = gemini_query(prompt, key)
            candidates = result.get("candidates", [])
            if not candidates:
                log("  ✗ No response candidates from Gemini batch query")
                return

            text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            tokens = result.get("usageMetadata", {}).get("totalTokenCount", "?")
            log(f"  ✓ Single Gemini API call successful! ({tokens} tokens used for {len(new_stores)} stores)")

            # Clean markdown JSON block formatting if present
            text = text.strip()
            if text.startswith("```"):
                text = re.sub(r'^```(?:json)?\s*', '', text)
                text = re.sub(r'```\s*$', '', text)

            data = json.loads(text)
            stores_output = data.get("stores", [])

            # Create lookup maps by store_id and index
            store_resp_map = {}
            for s_obj in stores_output:
                if isinstance(s_obj, dict):
                    sid_val = str(s_obj.get("store_id", "")).strip()
                    if sid_val:
                        store_resp_map[sid_val] = s_obj

            # Process each store
            for idx, store in enumerate(new_stores):
                sid = store["store_id"]
                sname = store["store_name"]
                hhid = store["household_id"]
                queue_id = store.get("queue_id")

                # Retrieve response object by store_id or index fallback
                s_obj = store_resp_map.get(str(sid))
                if not s_obj and idx < len(stores_output):
                    s_obj = stores_output[idx]

                if not s_obj or not isinstance(s_obj, dict):
                    log(f"  ✗ Omitted or missing response data for store '{sname}' (id={sid})")
                    if queue_id:
                        try:
                            run_exec(cur, pg, "UPDATE store_enrich_queue SET status='failed', processed_at=NOW() WHERE id=?", (queue_id,))
                        except Exception:
                            pass
                    continue

                cuisine = (s_obj.get("cuisine") or "").strip()
                raw_items = s_obj.get("items", [])[:25]

                # Update cuisine in stores table
                try:
                    run_exec(cur, pg, "UPDATE stores SET cuisine=?, auto_populated=? WHERE id=?", (cuisine, True, sid))
                except Exception:
                    pass

                # Insert items into store_items table with proper categorization
                added = 0
                for raw_item in raw_items:
                    if isinstance(raw_item, dict):
                        item_clean = str(raw_item.get("name") or "").strip()
                        g_cat = str(raw_item.get("category") or "").strip()
                    else:
                        item_clean = str(raw_item).strip()
                        g_cat = ""

                    if not item_clean:
                        continue

                    category = determine_category(item_clean, g_cat)

                    # Check if item already exists for this store
                    existing = run_sql(cur, pg,
                        "SELECT id FROM store_items WHERE store_id=? AND LOWER(name)=LOWER(?) AND household_id=?",
                        (sid, item_clean, hhid))
                    if not existing:
                        run_exec(cur, pg,
                            "INSERT INTO store_items (store_id, name, category, household_id) VALUES (?, ?, ?, ?)",
                            (sid, item_clean, category, hhid))
                        added += 1

                # Update queue status if queue_id exists
                if queue_id:
                    try:
                        run_exec(cur, pg, "UPDATE store_enrich_queue SET status='done', processed_at=NOW() WHERE id=?", (queue_id,))
                    except Exception:
                        pass

                log(f"  ✓ Store '{sname}' (id={sid}): updated cuisine='{cuisine}', added {added} items")

            if not pg and conn:
                conn.commit()

        except Exception as e:
            log(f"  ✗ Error executing batched Gemini store enrichment: {e}")

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
