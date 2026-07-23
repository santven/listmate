#!/usr/bin/env python3
"""Store enrichment for premium households. Runs every 15 min. Max 2 stores per run."""
import os, sys, json, time, re, urllib.request, urllib.error
from datetime import datetime

LOG_FILE = "/var/log/store_enrich.log"
os.makedirs(os.path.dirname(LOG_FILE) or ".", exist_ok=True)

def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try: open(LOG_FILE,"a").write(line+"\n")
    except IOError: pass

def get_key():
    try:
        for line in open("/opt/shared/.env"):
            if line.strip().startswith("GEMINI_API_KEY="):
                return line.split("=",1)[1].strip().strip("'\"")
    except: pass
    return os.environ.get("GEMINI_API_KEY","")

def gemini(prompt, key):
    body = {"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"maxOutputTokens":500,"temperature":0.3}}
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent",
        data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","x-goog-api-key":key})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())

def get_db():
    """Connect to DB — PostgreSQL on Render, SQLite locally."""
    dburi = os.environ.get("DATABASE_URL")
    if dburi:
        import psycopg2, psycopg2.extras
        conn = psycopg2.connect(dburi)
        conn.autocommit = True
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        pg = True
    else:
        import sqlite3
        conn = sqlite3.connect(os.environ.get("DB_PATH","listmate.db"))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        cur = conn
        pg = False
    return conn, cur, pg

def run_sql(cur, pg, sql, params=None):
    if pg:
        # Convert ? to %s for Postgres
        sql = re.sub(r'\?', '%s', sql)
        cur.execute(sql, params)
        try: return [dict(r) for r in cur.fetchall()] if cur.description else []
        except: return []
    else:
        if params:
            rows = cur.execute(sql, params).fetchall()
        else:
            rows = cur.execute(sql).fetchall()
        return [dict(r) for r in rows]

def run_exec(cur, pg, sql, params=None):
    if pg:
        sql = re.sub(r'\?', '%s', sql)
        cur.execute(sql, params)
    else:
        cur.execute(sql, params or ())

def main():
    log("=== Store enrichment ===")
    key = get_key()
    if not key: log("No API key"); return
    
    conn, cur, pg = get_db()
    try:
        # Get pending stores
        pending = run_sql(cur, pg,
            "SELECT id, store_id, household_id, zip_code, country FROM store_enrich_queue "
            "WHERE status='pending' ORDER BY created_at LIMIT 2")
        
        if not pending:
            log("No pending stores")
            return
        
        log(f"Processing {len(pending)} stores")
        
        for pq in pending:
            sid = pq["store_id"]
            hhid = pq["household_id"]
            
            # Get store name
            stores = run_sql(cur, pg, "SELECT name FROM stores WHERE id=?", (sid,))
            if not stores:
                log(f"  Store {sid} not found"); continue
            store_name = stores[0]["name"]
            
            # Get household dietary
            hh_rows = run_sql(cur, pg,
                "SELECT zip_code, country, dietary_restrictions FROM auth_households WHERE id=?", (hhid,))
            zip_code = hh_rows[0].get("zip_code","") if hh_rows else ""
            country = hh_rows[0].get("country","USA") if hh_rows else "USA"
            dietary_raw = (hh_rows[0].get("dietary_restrictions") or "") if hh_rows else ""
            
            # Build dietary note
            dietary_note = ""
            if dietary_raw:
                restrictions = [d.strip() for d in dietary_raw.split(",") if d.strip()]
                labels = {
                    "vegetarian": "vegetarian (no meat/fish/seafood)",
                    "vegan": "vegan (no animal products)",
                    "gluten_free": "gluten-free (no wheat/barley/rye)",
                    "halal": "halal (no pork/alcohol/non-halal meat)"
                }
                rlabels = [labels.get(r, r) for r in restrictions]
                dietary_note = f"CRITICAL: Household is {', '.join(rlabels)}. EXCLUDE any items violating this. "
            
            prompt = (
                f"Find stores matching '{store_name}' in zip code '{zip_code}' in country '{country}'. "
                f"What cuisine type? What are the top 25 items people commonly buy? "
                f"{dietary_note}"
                f"Return valid JSON only: {{\"cuisine\":\"...\",\"items\":[\"item1\",...]}}"
            )
            
            log(f"  {store_name} (zip={zip_code}) | dietary={dietary_raw or 'none'}")
            
            try:
                result = gemini(prompt, key)
                text = result["candidates"][0]["content"]["parts"][0]["text"]
                tokens = result.get("usageMetadata",{}).get("totalTokenCount","?")
                log(f"  Gemini: {tokens} tokens")
                
                # Parse JSON
                text = text.strip()
                if text.startswith("```"):
                    text = re.sub(r'^```(?:json)?\s*','',text)
                    text = re.sub(r'```\s*$','',text)
                data = json.loads(text)
                
                cuisine = (data.get("cuisine") or "").strip()
                items = data.get("items",[])[:25]
                
                # Save cuisine
                run_exec(cur, pg, "UPDATE stores SET cuisine=?, auto_populated=? WHERE id=?",
                         (cuisine, True, sid))
                
                # Insert items
                added = 0
                for name in items:
                    if not name or not name.strip(): continue
                    run_exec(cur, pg,
                        "INSERT INTO store_items (store_id,name,category,household_id) VALUES (?,?,?,?)",
                        (sid, name.strip(), "gemini_auto", hhid))
                    added += 1
                
                # Mark done
                run_exec(cur, pg, "UPDATE store_enrich_queue SET status='done', processed_at=NOW() WHERE id=?",
                         (pq["id"],))
                if not pg: conn.commit()
                
                log(f"  ✓ {added} items | cuisine={cuisine}")
                
            except Exception as e:
                log(f"  ✗ ERROR: {e}")
                run_exec(cur, pg, "UPDATE store_enrich_queue SET status='failed', processed_at=NOW() WHERE id=?",
                         (pq["id"],))
                if not pg: conn.commit()
            
            time.sleep(30)  # Rate limit between calls
            
    finally:
        if not pg and conn: conn.close()
    
    log("Done")

if __name__ == "__main__":
    main()
