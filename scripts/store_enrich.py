#!/usr/bin/env python3
"""
Store enrichment cron job for Render.
Runs every 15 minutes to enrich stores created in the last 15 minutes or queued for premium households.
Uses Gemini 3.1 Flash Lite. Batches up to 10 pending stores into a SINGLE Gemini API call!
"""

import os
import sys
import json
import time
import re
import traceback
import urllib.request
import urllib.error
from datetime import datetime

# Add root directory to sys.path so we can import db_pg, db, and categorize modules
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

def get_db_conn():
    """Connect to DB using standard app modules (db_pg for PostgreSQL on Render, db for SQLite)."""
    dburi = os.environ.get("DATABASE_URL")
    if dburi:
        import db_pg
        return db_pg.get_db(), True
    else:
        import db
        return db.get_db(), False

def query_all(db, sql, params=None):
    res = db.execute(sql, params or ())
    if hasattr(res, "fetchall"):
        return res.fetchall()
    elif hasattr(db, "fetchall"):
        return db.fetchall()
    return []

def exec_sql(db, sql, params=None):
    db.execute(sql, params or ())

def main():
    log("=== Starting Store Enrichment Job (Batched Gemini API) ===")
    key = get_key()
    if not key:
        log("ERROR: No GEMINI_API_KEY found in environment")
        return

    db = None
    try:
        db, is_pg = get_db_conn()
        log(f"Database connected successfully (PostgreSQL={is_pg})")

        # 1. Query stores created in the last 15 minutes for premium households
        if is_pg:
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

        new_stores = query_all(db, sql_stores)
        seen_store_ids = {s["store_id"] for s in new_stores}

        # 2. Fallback to store_enrich_queue if fewer than 10 stores returned
        if len(new_stores) < 10:
            try:
                limit_needed = 10 - len(new_stores)
                if is_pg:
                    sql_queue = (
                        "SELECT q.id AS queue_id, q.store_id, q.household_id "
                        "FROM store_enrich_queue q "
                        "JOIN auth_households h ON q.household_id = h.id "
                        "WHERE q.status='pending' AND h.is_premium = TRUE "
                        "ORDER BY q.created_at LIMIT " + str(limit_needed)
                    )
                else:
                    sql_queue = (
                        "SELECT q.id AS queue_id, q.store_id, q.household_id "
                        "FROM store_enrich_queue q "
                        "JOIN auth_households h ON q.household_id = h.id "
                        "WHERE q.status='pending' AND h.is_premium = 1 "
                        "ORDER BY q.created_at LIMIT " + str(limit_needed)
                    )
                queue_rows = query_all(db, sql_queue)
                for q in queue_rows:
                    sid = q["store_id"]
                    if sid not in seen_store_ids:
                        st = query_all(db, "SELECT id AS store_id, name AS store_name, household_id FROM stores WHERE id=?", (sid,))
                        if st:
                            st[0]["queue_id"] = q["queue_id"]
                            new_stores.append(st[0])
                            seen_store_ids.add(sid)
                    else:
                        for st in new_stores:
                            if st["store_id"] == sid and "queue_id" not in st:
                                st["queue_id"] = q["queue_id"]
            except Exception as q_err:
                log(f"Warning querying store_enrich_queue: {q_err}")

        if not new_stores:
            log("No stores needing enrichment for premium households.")
            return

        store_names = [s["store_name"] for s in new_stores]
        log(f"Found {len(new_stores)} store(s) to enrich: {store_names}. Building single batched Gemini request...")

        # Gather household metadata for each store
        prompt_stores = []
        for idx, store in enumerate(new_stores, 1):
            sid = store["store_id"]
            sname = store["store_name"]
            hhid = store["household_id"]

            hh_rows = query_all(db, "SELECT zip_code, country, dietary_restrictions FROM auth_households WHERE id=?", (hhid,))
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
            f"Include an optimal physical aisle/walking order ('category_order') array for a shopper traversing this store (e.g. ['Produce', 'Bakery', 'Deli', 'Pantry', 'Dairy', 'Frozen', 'Household']).\n"
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

        result = gemini_query(prompt, key)
        candidates = result.get("candidates", [])
        if not candidates:
            log("  ✗ No response candidates from Gemini batch query")
            return

        text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        tokens = result.get("usageMetadata", {}).get("totalTokenCount", "?")
        log(f"  ✓ Single Gemini API call successful! ({tokens} tokens used for {len(new_stores)} stores)")

        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'```\s*$', '', text)

        data = json.loads(text)
        stores_output = data.get("stores", [])

        store_resp_map = {}
        for s_obj in stores_output:
            if isinstance(s_obj, dict):
                sid_val = str(s_obj.get("store_id", "")).strip()
                if sid_val:
                    store_resp_map[sid_val] = s_obj

        for idx, store in enumerate(new_stores):
            sid = store["store_id"]
            sname = store["store_name"]
            hhid = store["household_id"]
            queue_id = store.get("queue_id")

            log(f"--> Processing enrichment results for store '{sname}' (id={sid}, queue_id={queue_id}, household_id={hhid})...")

            s_obj = store_resp_map.get(str(sid))
            if not s_obj and idx < len(stores_output):
                s_obj = stores_output[idx]

            if not s_obj or not isinstance(s_obj, dict):
                log(f"  ✗ Omitted or missing response data for store '{sname}' (id={sid})")
                try:
                    exec_sql(db, "UPDATE store_enrich_queue SET status='failed', processed_at=CURRENT_TIMESTAMP WHERE store_id=? AND status='pending'", (sid,))
                    if queue_id:
                        exec_sql(db, "UPDATE store_enrich_queue SET status='failed', processed_at=CURRENT_TIMESTAMP WHERE id=?", (queue_id,))
                    if hasattr(db, "commit"):
                        db.commit()
                except Exception as ex_fail:
                    log(f"  ✗ Exception updating queue failure: {ex_fail}")
                continue

            cuisine = (s_obj.get("cuisine") or "").strip()
            raw_items = s_obj.get("items", [])[:25]

            # Update stores table
            try:
                cat_order_list = s_obj.get("category_order", [])
                if isinstance(cat_order_list, list):
                    cat_order_str = ",".join([str(c).strip() for c in cat_order_list if str(c).strip()])
                else:
                    cat_order_str = str(cat_order_list or "").strip()
                exec_sql(db, "UPDATE stores SET cuisine=?, auto_populated=?, category_order=? WHERE id=?", (cuisine, True, cat_order_str, sid))
                log(f"  [DB] Updated stores table for store_id={sid}")
            except Exception as e_st:
                log(f"  ✗ Error updating stores table for '{sname}' (id={sid}): {e_st}")

            # Insert items into store_items table
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

                try:
                    existing = query_all(db, "SELECT id, category FROM store_items WHERE store_id=? AND LOWER(name)=LOWER(?) AND household_id=?", (sid, item_clean, hhid))
                    if not existing:
                        exec_sql(db, "INSERT INTO store_items (store_id, name, category, household_id) VALUES (?, ?, ?, ?)", (sid, item_clean, category, hhid))
                        added += 1
                    else:
                        old_cat = (existing[0].get("category") or "").strip()
                        if (not old_cat or old_cat.lower() in ["general", "auto", "gemini_auto"]) and category and category.lower() not in ["general", "auto", "gemini_auto"]:
                            exec_sql(db, "UPDATE store_items SET category=? WHERE id=?", (category, existing[0]["id"]))
                except Exception as e_item:
                    log(f"  ✗ Error inserting item '{item_clean}' for store_id={sid}: {e_item}")

            # Update store_enrich_queue status
            try:
                exec_sql(db, "UPDATE store_enrich_queue SET status='done', processed_at=CURRENT_TIMESTAMP WHERE store_id=? AND status='pending'", (sid,))
                if queue_id:
                    exec_sql(db, "UPDATE store_enrich_queue SET status='done', processed_at=CURRENT_TIMESTAMP WHERE id=?", (queue_id,))
                log(f"  [DB] Updated store_enrich_queue status='done' for store_id={sid}")
            except Exception as e_q:
                log(f"  ✗ Error updating store_enrich_queue to done for store {sid}: {e_q}")

            # Commit explicitly after store processing
            if hasattr(db, "commit"):
                try:
                    db.commit()
                    log(f"  [DB] Explicit commit completed for store_id={sid}")
                except Exception as e_cm:
                    log(f"  ✗ Error committing store_id={sid}: {e_cm}")

            # Post-commit verification query
            try:
                st_items = query_all(db, "SELECT COUNT(*) as cnt FROM store_items WHERE store_id=?", (sid,))
                item_cnt = st_items[0]["cnt"] if st_items else 0
                q_status_rows = query_all(db, "SELECT status FROM store_enrich_queue WHERE store_id=? ORDER BY id DESC LIMIT 1", (sid,))
                q_status = q_status_rows[0]["status"] if q_status_rows else "no queue row"
                log(f"  ✓ Store '{sname}' (id={sid}): updated cuisine='{cuisine}', added {added} items. Verification -> store_items in DB: {item_cnt}, queue status: '{q_status}'")
            except Exception as e_ver:
                log(f"  Warning during post-commit verification for store_id={sid}: {e_ver}")

    except Exception as e:
        log(f"  ✗ Error executing store enrichment job: {e}")
        log(traceback.format_exc())
    finally:
        if db and hasattr(db, "close"):
            try:
                db.close()
            except Exception:
                pass
    log("=== Store Enrichment Job Complete ===")

if __name__ == "__main__":
    main()
