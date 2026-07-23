#!/usr/bin/env python3
"""
Trip detector wrapper — runs at 23:00 GMT (6pm CT) for 1 hour.
Processes max 5 premium households per iteration, 60 iterations.
Only processes households WHERE is_premium = TRUE.
"""
import sqlite3
import json
import os
import sys
import time
from datetime import datetime, timedelta

# Add shared module path
sys.path.insert(0, "/opt/shared")
sys.path.insert(0, "/tmp/listmate")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trip_detector import detect_and_record_trips

DB_PATH = os.environ.get("DB_PATH", "listmate.db")
AUTH_DB = os.environ.get("AUTH_DB", "listmate_auth.db")
LOG_FILE = "/var/log/trip_detector.log"

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


def get_premium_households():
    """Get all premium household IDs."""
    db = sqlite3.connect(AUTH_DB)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT id, name, member_limit FROM auth_households WHERE is_premium = 1 ORDER BY id"
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def main():
    # Check GMT hour
    now_utc = datetime.utcnow()
    gmt_hour = now_utc.hour
    
    if gmt_hour != 23:
        log(f"GMT hour is {gmt_hour}, not 23. Exiting.")
        return
    
    log("Starting trip detector window (23:00-23:59 GMT / 6pm-7pm CT)")
    
    premium_households = get_premium_households()
    log(f"Found {len(premium_households)} premium households")
    
    if not premium_households:
        log("No premium households — nothing to do")
        return
    
    # Process in batches of 5 per iteration, for up to 60 iterations
    for iteration in range(60):
        # Check if we're still in the 23:xx GMT window
        now_utc = datetime.utcnow()
        if now_utc.hour != 23:
            log(f"GMT hour changed to {now_utc.hour}, stopping.")
            break
        
        # Get batch (5 households per iteration, cycling through all premium)
        batch_start = (iteration * 5) % len(premium_households)
        batch = premium_households[batch_start:batch_start + 5]
        
        for hh in batch:
            hh_id = hh["id"]
            hh_name = hh["name"]
            try:
                trips = detect_and_record_trips(DB_PATH, hh_id)
                log(f"  hh {hh_id} ({hh_name}): found {len(trips)} trips total")
            except Exception as e:
                log(f"  hh {hh_id} ({hh_name}): ERROR {e}")
        
        log(f"Iteration {iteration + 1}/60 complete")
        
        # Sleep 60 seconds between iterations
        if iteration < 59:
            time.sleep(60)
    
    log("Trip detector window complete")


if __name__ == "__main__":
    main()
