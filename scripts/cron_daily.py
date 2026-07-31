#!/usr/bin/env python3
import os
import sys
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent directory to path to import shared modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.auth import _run, _init_schema
from email_helper import send_subscription_notice, send_activation_notice, send_reengagement_notice

def process_expiration(hh, today_date, plus_3_date):
    status = hh.get("subscription_status")
    trial_ends_at = hh.get("trial_ends_at")
    
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
        print(f"[Expiration] Sending {days_left}-day notice to {email} (HH: {hh['household_name']}), is_trial={is_trial}")
        
        if email:
            success = send_subscription_notice(
                to_email=email,
                user_name=user_name,
                is_trial=is_trial,
                days_left=days_left
            )
            if success:
                print(f"[Expiration] Successfully sent notice to {email}.")
                return True
            else:
                print(f"[Expiration] Failed to send notice to {email}.")
                return False
    return False

def process_activation(hh):
    email = hh.get("email")
    user_name = hh.get("user_name")
    
    print(f"[Activation] Sending Day-3 notice to {email} (HH: {hh['household_name']})")
    
    if email:
        success = send_activation_notice(
            to_email=email,
            user_name=user_name
        )
        if success:
            print(f"[Activation] Successfully sent notice to {email}.")
            return True
        else:
            print(f"[Activation] Failed to send notice to {email}.")
            return False
    return False

def process_reengagement(hh):
    email = hh.get("email")
    user_name = hh.get("user_name")
    
    print(f"[Re-engagement] Sending Day-14 notice to {email} (HH: {hh['household_name']})")
    
    if email:
        success = send_reengagement_notice(
            to_email=email,
            user_name=user_name
        )
        if success:
            print(f"[Re-engagement] Successfully sent notice to {email}.")
            return True
        else:
            print(f"[Re-engagement] Failed to send notice to {email}.")
            return False
    return False


def run_cron():
    _init_schema()
    
    now = datetime.datetime.now(datetime.timezone.utc)
    today_date = now.date()
    plus_3_date = today_date + datetime.timedelta(days=3)
    
    # --- 1. Expirations ---
    print("\n--- Processing Expirations ---")
    query_expirations = """
    SELECT DISTINCT ON (h.id) 
        h.id as household_id, 
        h.name as household_name, 
        u.email, 
        u.name as user_name, 
        h.subscription_status,
        h.trial_ends_at
    FROM auth_households h
    JOIN auth_users u ON u.household_id = h.id
    WHERE 
        (h.subscription_status = 'trial' AND DATE(h.trial_ends_at) IN (CURRENT_DATE, CURRENT_DATE + INTERVAL '3 days'))
    ORDER BY h.id, u.created_at ASC
    """
    households_expiring = _run(query_expirations)
    
    if households_expiring:
        with ThreadPoolExecutor(max_workers=min(32, len(households_expiring))) as executor:
            futures = [executor.submit(process_expiration, hh, today_date, plus_3_date) for hh in households_expiring]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    print(f"Expiration task generated an exception: {exc}")
    else:
        print("No expirations to process today.")

    # --- 2. Activations (Day 3, 0 items) ---
    print("\n--- Processing Activations ---")
    query_activations = """
    SELECT DISTINCT ON (h.id) 
        h.id as household_id, 
        h.name as household_name, 
        u.email, 
        u.name as user_name
    FROM auth_households h
    JOIN auth_users u ON u.household_id = h.id
    LEFT JOIN list_items l ON h.id = l.household_id
    WHERE DATE(h.created_at) = CURRENT_DATE - INTERVAL '3 days'
    GROUP BY h.id, u.email, u.name, u.created_at
    HAVING COUNT(l.id) = 0
    ORDER BY h.id, u.created_at ASC
    """
    households_activation = _run(query_activations)
    
    if households_activation:
        with ThreadPoolExecutor(max_workers=min(32, len(households_activation))) as executor:
            futures = [executor.submit(process_activation, hh) for hh in households_activation]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    print(f"Activation task generated an exception: {exc}")
    else:
        print("No activations to process today.")

    # --- 3. Re-engagement (Day 14 since last item added) ---
    print("\n--- Processing Re-engagement ---")
    query_reengagement = """
    SELECT DISTINCT ON (h.id) 
        h.id as household_id, 
        h.name as household_name, 
        u.email, 
        u.name as user_name,
        MAX(l.added_at) as last_active
    FROM auth_households h
    JOIN auth_users u ON u.household_id = h.id
    JOIN list_items l ON h.id = l.household_id
    GROUP BY h.id, u.email, u.name, u.created_at
    HAVING DATE(MAX(l.added_at)) = CURRENT_DATE - INTERVAL '14 days'
    ORDER BY h.id, u.created_at ASC
    """
    households_reengagement = _run(query_reengagement)
    
    if households_reengagement:
        with ThreadPoolExecutor(max_workers=min(32, len(households_reengagement))) as executor:
            futures = [executor.submit(process_reengagement, hh) for hh in households_reengagement]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    print(f"Re-engagement task generated an exception: {exc}")
    else:
        print("No re-engagements to process today.")


if __name__ == "__main__":
    print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] Starting daily cron jobs...")
    run_cron()
    print("Done.")
