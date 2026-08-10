#!/usr/bin/env python3
import os
import sys
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent directory to path to import shared modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.auth import _run, _init_schema
from email_helper import send_subscription_notice, send_activation_notice, send_reengagement_notice, send_combined_notice

def process_email_events(email, user_name, events, user_id=0):
    if not email:
        return False
        
    # If there is only one event, use the specific email template
    if len(events) == 1:
        if 'expiration' in events:
            is_trial = events['expiration']['is_trial']
            days_left = events['expiration']['days_left']
            print(f"[{email}] Sending specific expiration notice ({days_left} days).")
            return send_subscription_notice(email, user_name, is_trial, days_left, user_id)
        elif 'activation' in events:
            print(f"[{email}] Sending specific activation notice.")
            return send_activation_notice(email, user_name, user_id)
        elif 'reengagement' in events:
            print(f"[{email}] Sending specific re-engagement notice.")
            return send_reengagement_notice(email, user_name, user_id)
            
    # If there are multiple events, send the combined template
    print(f"[{email}] Sending COMBINED notice for multiple events: {list(events.keys())}")
    return send_combined_notice(email, user_name, events, user_id)

def run_cron():
    _init_schema()
    
    now = datetime.datetime.now(datetime.timezone.utc)
    today_date = now.date()
    plus_3_date = today_date + datetime.timedelta(days=3)
    
    # Dictionary to aggregate events per user email
    # Format: { 'user@email.com': { 'user_name': 'John', 'events': { 'expiration': {'days_left': 3, 'is_trial': True}, 'activation': True } } }
    users_to_notify = {}
    
    def add_user_event(email, name, event_name, event_data=True, user_id=0):
        if not email: return
        if email not in users_to_notify:
            users_to_notify[email] = {'user_name': name, 'events': {}, 'user_id': user_id}
        users_to_notify[email]['events'][event_name] = event_data

    # --- 1. Expirations ---
    print("Fetching Expirations...")
    query_expirations = """
    SELECT DISTINCT ON (h.id) 
        h.id as household_id, 
        h.name as household_name, 
        u.id as user_id,
        u.email, 
        u.name as user_name, 
        h.subscription_status,
        h.trial_ends_at
    FROM auth_households h
    JOIN auth_users u ON u.household_id = h.id
    JOIN auth_household_members ahm ON ahm.user_id = u.id AND ahm.household_id = h.id
    WHERE 
        (h.subscription_status = 'trial' AND DATE(h.trial_ends_at) IN (CURRENT_DATE, CURRENT_DATE + INTERVAL '3 days'))
        AND ahm.marketing_opt_in = TRUE
    ORDER BY h.id, u.created_at ASC
    """
    households_expiring = _run(query_expirations)
    for hh in households_expiring:
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
            
        if target_date:
            days_left = None
            if target_date == today_date:
                days_left = 0
            elif target_date == plus_3_date:
                days_left = 3
                
            if days_left is not None:
                add_user_event(hh.get("email"), hh.get("user_name"), 'expiration', {'is_trial': is_trial, 'days_left': days_left}, hh.get("user_id"))

    # --- 2. Activations (Day 3, 0 items) ---
    print("Fetching Activations...")
    query_activations = """
    SELECT DISTINCT ON (h.id) 
        h.id as household_id, 
        u.id as user_id,
        u.email, 
        u.name as user_name
    FROM auth_households h
    JOIN auth_users u ON u.household_id = h.id
    JOIN auth_household_members ahm ON ahm.user_id = u.id AND ahm.household_id = h.id
    LEFT JOIN list_items l ON h.id = l.household_id
    WHERE DATE(h.created_at) = CURRENT_DATE - INTERVAL '3 days'
      AND ahm.marketing_opt_in = TRUE
    GROUP BY h.id, u.id, u.email, u.name, u.created_at
    HAVING COUNT(l.id) = 0
    ORDER BY h.id, u.created_at ASC
    """
    households_activation = _run(query_activations)
    for hh in households_activation:
        add_user_event(hh.get("email"), hh.get("user_name"), 'activation', True, hh.get("user_id"))

    # --- 3. Re-engagement (Day 14 since last item added) ---
    print("Fetching Re-engagements...")
    query_reengagement = """
    SELECT DISTINCT ON (h.id) 
        h.id as household_id, 
        u.id as user_id,
        u.email, 
        u.name as user_name,
        MAX(l.added_at) as last_active
    FROM auth_households h
    JOIN auth_users u ON u.household_id = h.id
    JOIN auth_household_members ahm ON ahm.user_id = u.id AND ahm.household_id = h.id
    JOIN list_items l ON h.id = l.household_id
    WHERE ahm.marketing_opt_in = TRUE
    GROUP BY h.id, u.id, u.email, u.name, u.created_at
    HAVING DATE(MAX(l.added_at)) = CURRENT_DATE - INTERVAL '14 days'
    ORDER BY h.id, u.created_at ASC
    """
    households_reengagement = _run(query_reengagement)
    for hh in households_reengagement:
        add_user_event(hh.get("email"), hh.get("user_name"), 'reengagement', True, hh.get("user_id"))

    print(f"\nFound {len(users_to_notify)} unique users to notify.")
    
    if users_to_notify:
        with ThreadPoolExecutor(max_workers=min(32, len(users_to_notify))) as executor:
            futures = []
            for email, data in users_to_notify.items():
                futures.append(executor.submit(process_email_events, email, data['user_name'], data['events'], data.get('user_id', 0)))
                
            for future in as_completed(futures):
                try:
                    success = future.result()
                    if not success:
                        print("An email failed to send.")
                except Exception as exc:
                    print(f"Task generated an exception: {exc}")
    else:
        print("No emails to send today.")

if __name__ == "__main__":
    print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] Starting daily cron jobs...")
    run_cron()
    print("Done.")
