#!/usr/bin/env python3
"""
Store enrichment — auto-populate store cuisine + items for premium households.
Uses Gemini 3.1-flash-lite to find what each store offers.
Runs every 15 min via cron. Processes max 2 stores per run.
Rate limit: 2 Gemini calls max per run (15 min apart).
"""
import os
import sys
import json
import time
import sqlite3
import re
import urllib.request
import urllib.error
from datetime import datetime

# ── Config ──────────────────────────────────────────────────
DB_PATH = os.environ.get("DB_PATH", "listmate.db")
USE_PG = bool(os.environ.get("DATABASE_URL"))
LOG_FILE = "/var/log/store_enrich.log"

os.makedirs(os.path.dirname(LOG_FILE) if os.path.dirname(LOG_FILE) else ".", exist_ok=True)


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except IOError:
        pass


# ── Gemini client (local copy, same pattern as gemini_client.py) ──
def _load_gemini_key():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        env_path = "/opt/shared/.env"
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.strip().startswith("GEMINI_API_KEY="):
                        key = line.split("=", 1)[1].strip().strip("'\"").strip()
                        break
    return key


def gemini_generate(prompt: str, model: str = "gemini-3.1-flash-lite") -> dict:
    """Call Gemini API, return parsed JSON."""
    key = _load_gemini_key()
    if not key:
        return {"error": "No Gemini API key"}

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 1024,
        }
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        text = ""
        if "candidates" in result and len(result["candidates"]) > 0:
            parts = result["candidates"][0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)

        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text, "parse_error": True}

    except urllib.error.HTTPError as e:
        err_body = e.read().decode()[:500] if e.fp else ""
        log(f"Gemini HTTP error {e.code}: {err_body}")
        return {"error": f"HTTP {e.code}"}
    except Exception as e:
        log(f"Gemini exception: {e}")
        return {"error": str(e)}


# ── Database helpers ────────────────────────────────────────

def get_pg_connection():
    import psycopg2
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = True
    return conn


def pg_one(conn, sql, params=None):
    sql_fixed = re.sub(r'\?', '%s', sql)
    cur = conn.cursor()
    if params:
        cur.execute(sql_fixed, params)
    else:
        cur.execute(sql_fixed)
    row = cur.fetchone()
    if row is None:
        cur.close()
        return None
    cols = [d[0] for d in cur.description]
    cur.close()
    return dict(zip(cols, row))


def pg_run(conn, sql, params=None):
    sql_fixed = re.sub(r'\?', '%s', sql)
    cur = conn.cursor()
    if params:
        cur.execute(sql_fixed, params)
    else:
        cur.execute(sql_fixed)
    rows = cur.fetchall() if cur.description else []
    cols = [d[0] for d in cur.description] if cur.description else []
    cur.close()
    return [dict(zip(cols, r)) for r in rows]


def pg_exec(conn, sql, params=None):
    sql_fixed = re.sub(r'\?', '%s', sql)
    cur = conn.cursor()
    if params:
        cur.execute(sql_fixed, params)
    else:
        cur.execute(sql_fixed)
    cur.close()


# ── Main logic ──────────────────────────────────────────────

def process_queue():
    """Process up to 2 pending store enrich queue items."""
    if USE_PG:
        conn = get_pg_connection()
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row

    try:
        # Get pending items
        if USE_PG:
            items = pg_run(conn,
                "SELECT * FROM store_enrich_queue WHERE status = 'pending' ORDER BY created_at LIMIT 2")
        else:
            items = [dict(r) for r in conn.execute(
                "SELECT * FROM store_enrich_queue WHERE status = 'pending' ORDER BY created_at LIMIT 2").fetchall()]

        if not items:
            log("No pending enrich items")
            return

        log(f"Processing {len(items)} queue item(s)")

        for item in items:
            qid = item["id"]
            store_id = item["store_id"]
            city = (item.get("city") or "").strip()
            state = (item.get("state") or "").strip()
            country = (item.get("country") or "").strip()

            # Get store name
            if USE_PG:
                store = pg_one(conn,
                    "SELECT name FROM stores WHERE id = ? AND household_id = ?",
                    (store_id, item["household_id"]))
            else:
                store = conn.execute(
                    "SELECT name FROM stores WHERE id = ? AND household_id = ?",
                    (store_id, item["household_id"])).fetchone()
                store = dict(store) if store else None

            if not store:
                log(f"Store {store_id} not found — marking queue item {qid} as failed")
                if USE_PG:
                    pg_exec(conn,
                        "UPDATE store_enrich_queue SET status = 'failed', processed_at = NOW() WHERE id = ?",
                        (qid,))
                else:
                    conn.execute(
                        "UPDATE store_enrich_queue SET status = 'failed', processed_at = datetime('now') WHERE id = ?",
                        (qid,))
                    conn.commit()
                continue

            store_name = store["name"]
            location = ", ".join(filter(bool, [city, state, country])) or "unknown location"

            prompt = (
                f"Find stores matching '{store_name}' in {location}. "
                f"What cuisine type do they serve? What 25 items do people commonly buy from this store? "
                f"Return strictly valid JSON with no markdown fences: "
                f'{{"cuisine": "...", "items": ["item1", "item2", ...]}}'
            )

            log(f"Calling Gemini for store '{store_name}' (qid={qid})")
            result = gemini_generate(prompt, model="gemini-3.1-flash-lite")

            if "error" in result:
                log(f"Gemini error for store {store_id}: {result['error']}")
                if USE_PG:
                    pg_exec(conn,
                        "UPDATE store_enrich_queue SET status = 'failed', processed_at = NOW() WHERE id = ?",
                        (qid,))
                else:
                    conn.execute(
                        "UPDATE store_enrich_queue SET status = 'failed', processed_at = datetime('now') WHERE id = ?",
                        (qid,))
                    conn.commit()
                continue

            cuisine = (result.get("cuisine") or "").strip()
            items = result.get("items", [])

            if isinstance(items, list) and len(items) > 0:
                log(f"Got cuisine='{cuisine}', {len(items)} items for '{store_name}'")

                # Update store cuisine
                if cuisine:
                    if USE_PG:
                        pg_exec(conn,
                            "UPDATE stores SET cuisine = ?, auto_populated = TRUE WHERE id = ?",
                            (cuisine, store_id))
                    else:
                        conn.execute(
                            "UPDATE stores SET cuisine = ?, auto_populated = 1 WHERE id = ?",
                            (cuisine, store_id))

                # Insert items
                inserted = 0
                for item_name in items:
                    name = str(item_name).strip()
                    if not name or len(name) > 100:
                        continue
                    try:
                        if USE_PG:
                            pg_exec(conn,
                                "INSERT INTO store_items (household_id, store_id, name, category) VALUES (?, ?, ?, 'gemini_auto') "
                                "ON CONFLICT DO NOTHING",
                                (item["household_id"], store_id, name))
                        else:
                            conn.execute(
                                "INSERT OR IGNORE INTO store_items (household_id, store_id, name, category) VALUES (?, ?, ?, 'gemini_auto')",
                                (item["household_id"], store_id, name))
                        inserted += 1
                    except Exception:
                        pass

                if not USE_PG:
                    conn.commit()
                log(f"Inserted {inserted} items for store '{store_name}'")
            else:
                log(f"No items returned for store '{store_name}', raw: {result.get('raw', result)[:200]}")

            # Mark as done
            if USE_PG:
                pg_exec(conn,
                    "UPDATE store_enrich_queue SET status = 'done', processed_at = NOW() WHERE id = ?",
                    (qid,))
            else:
                conn.execute(
                    "UPDATE store_enrich_queue SET status = 'done', processed_at = datetime('now') WHERE id = ?",
                    (qid,))
                conn.commit()

            log(f"Completed qid={qid} for store '{store_name}'")

            # Rate limit: ~30s between Gemini calls (max 2 per run)
            time.sleep(2)

    except Exception as e:
        log(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if USE_PG:
            conn.close()
        else:
            conn.close()


if __name__ == "__main__":
    log("Store enrich run starting")
    process_queue()
    log("Store enrich run complete")
