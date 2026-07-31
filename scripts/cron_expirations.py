#!/usr/bin/env python3
import os
import sys
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent directory to path to import shared modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.auth import _run, _init_schema
from email_helper import send_subscription_notice

def process_household(hh, today_date, plus_3_date):
    status = hh.get("subscription_status")
    trial_ends_at = hh.get("trial_ends_at")
    sub_ends_at = hh.get("subscription_ends_at")
    
    target_date = None
    is_trial = False
    
    if status == 'trial' and trial_ends_at:
        target_date = trial_ends_at.date() if hasattr(trial_ends_at, 'date') else trial_ends_at
        if isinstance(target_date, str):
            try:
                target_date = datetime.datetime.fromisoformat(target_date.replace('Z', '+00:00')).date()
            except ValueError:
                target_date = datetime.datetime.strptime(target_date, '%Y-%m-%d %H:%M:%S').date()
        is_trial = True
    elif status == 'premium' and sub_ends_at:
        target_date = sub_ends_at.date() if hasattr(sub_ends_at, 'date') else sub_ends_at
        if isinstance(target_date, str):
            try:
                target_date = datetime.datetime.fromisoformat(target_date.replace('Z', '+00:00')).date()
            except ValueError:
                target_date = datetime.datetime.strptime(target_date, '%Y-%m-%d %H:%M:%S').date()
    
    if not target_date:
        return False
        
    days_left = None
    if target_date == today_date:
        days_left = 0
    elif target_date == plus_3_date:
        days_left = 3
        
    if days_left is not None:
        email = hh.get("email")
        user_name = hh.get("user_name")
        print(f"Sending {days_left}-day notice to {email} (HH: {hh['household_name']}), is_trial={is_trial}")
        
        if email:
            success = send_subscription_notice(
                to_email=email,
                user_name=user_name,
                is_trial=is_trial,
                days_left=days_left
            )
            if success:
                print(f"Successfully sent notice to {email}.")
                return True
            else:
                print(f"Failed to send notice to {email}.")
                return False
    return False

def run_cron():
    _init_schema()
    
    # Optimize: Let PostgreSQL filter out only the rows that match exactly today or +3 days.
    # This prevents transferring thousands of non-expiring households to the Python process.
    query = """
    SELECT DISTINCT ON (h.id) 
        h.id as household_id, 
        h.name as household_name, 
        u.email, 
        u.name as user_name, 
        h.subscription_status,
        h.trial_ends_at, 
        h.subscription_ends_at
    FROM auth_households h
    JOIN auth_users u ON u.household_id = h.id
    WHERE 
        (h.subscription_status = 'trial' AND DATE(h.trial_ends_at) IN (CURRENT_DATE, CURRENT_DATE + INTERVAL '3 days'))
        OR 
        (h.subscription_status = 'premium' AND DATE(h.subscription_ends_at) IN (CURRENT_DATE, CURRENT_DATE + INTERVAL '3 days'))
    ORDER BY h.id, u.created_at ASC
    """
    households = _run(query)
    
    now = datetime.datetime.now(datetime.timezone.utc)
    today_date = now.date()
    plus_3_date = today_date + datetime.timedelta(days=3)
    
    # Optimize: Use a ThreadPoolExecutor to send emails concurrently.
    # Because network requests (API calls to SendGrid) are I/O bound, concurrency drastically reduces overall runtime.
    max_workers = min(32, len(households) if households else 1)
    
    if households:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_household, hh, today_date, plus_3_date) for hh in households]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    print(f"Email task generated an exception: {exc}")

if __name__ == "__main__":
    print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] Starting expiration cron...")
    run_cron()
    print("Done.")
