#!/usr/bin/env python3
import os
import sys
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent directory to path to import shared modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.auth import _run, _init_schema
from email_helper import (
    send_subscription_notice,
    send_solo_nudge_notice,
    send_trial_week1_checkin,
    send_trial_week3_checkin,
    send_activation_notice,
    send_reengagement_notice,
    send_combined_notice,
)

def process_email_events(email, user_name, events, user_id=0, household_id=0):
    if not email:
        return False

    sent = False
    # If there is only one event, use the specific email template
    if len(events) == 1:
        if 'expiration' in events:
            is_trial = events['expiration']['is_trial']
            days_left = events['expiration']['days_left']
            print(f"[{email}] Sending specific expiration notice ({days_left} days).")
            sent = send_subscription_notice(email, user_name, is_trial, days_left, user_id)
        elif 'solo_nudge' in events:
            print(f"[{email}] Sending specific solo owner nudge notice.")
            sent = send_solo_nudge_notice(email, user_name, user_id)
        elif 'trial_week1' in events:
            print(f"[{email}] Sending specific trial week 1 check-in.")
            sent = send_trial_week1_checkin(email, user_name, user_id)
        elif 'trial_week3' in events:
            print(f"[{email}] Sending specific trial week 3 check-in.")
            sent = send_trial_week3_checkin(email, user_name, user_id)
        elif 'activation' in events:
            print(f"[{email}] Sending specific activation notice.")
            sent = send_activation_notice(email, user_name, user_id)
        elif 'reengagement' in events:
            print(f"[{email}] Sending specific re-engagement notice.")
            sent = send_reengagement_notice(email, user_name, user_id)
    else:
        # If there are multiple events, send the combined template
        print(f"[{email}] Sending COMBINED notice for multiple events: {list(events.keys())}")
        sent = send_combined_notice(email, user_name, events, user_id)

    # Record email sent timestamp in the database for tracking
    if sent and household_id:
        updates = []
        if 'expiration' in events:
            days_left = events['expiration']['days_left']
            is_trial = events['expiration']['is_trial']
            if is_trial:
                if days_left == 0:
                    updates.append("email_trial_exp_today_sent_at = NOW()")
                elif days_left == 3:
                    updates.append("email_trial_exp_3days_sent_at = NOW()")
            else:
                if days_left == 0:
                    updates.append("email_sub_exp_today_sent_at = NOW()")
                elif days_left == 3:
                    updates.append("email_sub_exp_3days_sent_at = NOW()")

        if 'solo_nudge' in events:
            updates.append("email_solo_nudge_sent_at = NOW()")
        if 'trial_week1' in events:
            updates.append("email_trial_week1_sent_at = NOW()")
        if 'trial_week3' in events:
            updates.append("email_trial_week3_sent_at = NOW()")
        if 'activation' in events:
            updates.append("email_activation_sent_at = NOW()")
        if 'reengagement' in events:
            updates.append("email_reengagement_sent_at = NOW()")

        if updates:
            try:
                update_sql = f"UPDATE auth_households SET {', '.join(updates)} WHERE id = %s"
                _run(update_sql, (household_id,))
                print(f"[{email}] Updated tracking timestamps for household {household_id}: {updates}")
            except Exception as e:
                print(f"[{email}] Error updating tracking timestamps for household {household_id}: {e}")

    return sent


def run_cron():
    _init_schema()

    now = datetime.datetime.now(datetime.timezone.utc)
    today_date = now.date()
    plus_3_date = today_date + datetime.timedelta(days=3)

    # Dictionary to aggregate events per user email
    # Format: { 'user@email.com': { 'user_name': 'John', 'user_id': 1, 'household_id': 2, 'events': { ... } } }
    users_to_notify = {}

    def add_user_event(email, name, event_name, event_data=True, user_id=0, household_id=0):
        if not email:
            return
        if email not in users_to_notify:
            users_to_notify[email] = {
                'user_name': name,
                'events': {},
                'user_id': user_id,
                'household_id': household_id,
            }
        users_to_notify[email]['events'][event_name] = event_data
        if household_id and not users_to_notify[email].get('household_id'):
            users_to_notify[email]['household_id'] = household_id

    # --- 1. Expirations (Transactional: Sent to all expiring households with untracked status) ---
    print("Fetching Expirations...")
    query_expirations = """
    SELECT DISTINCT ON (h.id) 
        h.id as household_id, 
        h.name as household_name, 
        u.id as user_id,
        u.email, 
        u.name as user_name, 
        h.subscription_status,
        h.trial_ends_at,
        h.subscription_ends_at,
        h.email_trial_exp_3days_sent_at,
        h.email_trial_exp_today_sent_at,
        h.email_sub_exp_3days_sent_at,
        h.email_sub_exp_today_sent_at
    FROM auth_households h
    JOIN auth_users u ON u.id = COALESCE(h.owner_id, (SELECT ahm2.user_id FROM auth_household_members ahm2 WHERE ahm2.household_id = h.id AND ahm2.role = 'owner' LIMIT 1), (SELECT u2.id FROM auth_users u2 WHERE u2.household_id = h.id ORDER BY u2.id ASC LIMIT 1))
    JOIN auth_household_members ahm ON ahm.user_id = u.id AND ahm.household_id = h.id
    WHERE 
        (
            (h.subscription_status = 'trial' AND (
                (DATE(h.trial_ends_at) = CURRENT_DATE + INTERVAL '3 days' AND h.email_trial_exp_3days_sent_at IS NULL)
                OR
                (DATE(h.trial_ends_at) = CURRENT_DATE AND h.email_trial_exp_today_sent_at IS NULL)
            ))
            OR
            (h.subscription_status IN ('premium', 'active') AND h.subscription_ends_at IS NOT NULL AND (
                (DATE(h.subscription_ends_at) = CURRENT_DATE + INTERVAL '3 days' AND h.email_sub_exp_3days_sent_at IS NULL)
                OR
                (DATE(h.subscription_ends_at) = CURRENT_DATE AND h.email_sub_exp_today_sent_at IS NULL)
            ))
        )
    ORDER BY h.id, u.created_at ASC
    """
    households_expiring = _run(query_expirations)
    for hh in households_expiring:
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
        elif status in ('premium', 'active') and sub_ends_at:
            target_date = sub_ends_at.date() if hasattr(sub_ends_at, 'date') else sub_ends_at
            if isinstance(target_date, str):
                try:
                    target_date = datetime.datetime.fromisoformat(target_date.replace('Z', '+00:00')).date()
                except ValueError:
                    target_date = datetime.datetime.strptime(target_date, '%Y-%m-%d %H:%M:%S').date()
            is_trial = False

        if target_date:
            days_left = None
            if target_date == today_date:
                days_left = 0
            elif target_date == plus_3_date:
                days_left = 3

            if days_left is not None:
                add_user_event(
                    hh.get("email"),
                    hh.get("user_name"),
                    'expiration',
                    {'is_trial': is_trial, 'days_left': days_left},
                    hh.get("user_id"),
                    hh.get("household_id"),
                )

    # --- 2. Solo Household Nudge (Day 3+, only 1 owner/member in household) ---
    print("Fetching Solo Household Nudges...")
    query_solo_nudge = """
    SELECT DISTINCT ON (h.id) 
        h.id as household_id, 
        u.id as user_id,
        u.email, 
        u.name as user_name
    FROM auth_households h
    JOIN auth_users u ON u.id = COALESCE(h.owner_id, (SELECT ahm2.user_id FROM auth_household_members ahm2 WHERE ahm2.household_id = h.id AND ahm2.role = 'owner' LIMIT 1), (SELECT u2.id FROM auth_users u2 WHERE u2.household_id = h.id ORDER BY u2.id ASC LIMIT 1))
    JOIN auth_household_members ahm ON ahm.user_id = u.id AND ahm.household_id = h.id
    WHERE DATE(h.created_at) <= CURRENT_DATE - INTERVAL '3 days'
      AND h.email_solo_nudge_sent_at IS NULL
      AND ahm.marketing_opt_in = TRUE
      AND (SELECT COUNT(*) FROM auth_household_members WHERE household_id = h.id) = 1
    ORDER BY h.id, u.created_at ASC
    """
    households_solo = _run(query_solo_nudge)
    for hh in households_solo:
        add_user_event(
            hh.get("email"),
            hh.get("user_name"),
            'solo_nudge',
            True,
            hh.get("user_id"),
            hh.get("household_id"),
        )

    # --- 3. Trial Week 1 Check-in (Day 7+) ---
    print("Fetching Trial Week 1 Check-ins...")
    query_week1 = """
    SELECT DISTINCT ON (h.id) 
        h.id as household_id, 
        u.id as user_id,
        u.email, 
        u.name as user_name
    FROM auth_households h
    JOIN auth_users u ON u.id = COALESCE(h.owner_id, (SELECT ahm2.user_id FROM auth_household_members ahm2 WHERE ahm2.household_id = h.id AND ahm2.role = 'owner' LIMIT 1), (SELECT u2.id FROM auth_users u2 WHERE u2.household_id = h.id ORDER BY u2.id ASC LIMIT 1))
    JOIN auth_household_members ahm ON ahm.user_id = u.id AND ahm.household_id = h.id
    WHERE h.subscription_status = 'trial'
      AND DATE(h.created_at) <= CURRENT_DATE - INTERVAL '7 days'
      AND h.email_trial_week1_sent_at IS NULL
      AND ahm.marketing_opt_in = TRUE
    ORDER BY h.id, u.created_at ASC
    """
    households_week1 = _run(query_week1)
    for hh in households_week1:
        add_user_event(
            hh.get("email"),
            hh.get("user_name"),
            'trial_week1',
            True,
            hh.get("user_id"),
            hh.get("household_id"),
        )

    # --- 4. Trial Week 3 Check-in (Day 21+) ---
    print("Fetching Trial Week 3 Check-ins...")
    query_week3 = """
    SELECT DISTINCT ON (h.id) 
        h.id as household_id, 
        u.id as user_id,
        u.email, 
        u.name as user_name
    FROM auth_households h
    JOIN auth_users u ON u.id = COALESCE(h.owner_id, (SELECT ahm2.user_id FROM auth_household_members ahm2 WHERE ahm2.household_id = h.id AND ahm2.role = 'owner' LIMIT 1), (SELECT u2.id FROM auth_users u2 WHERE u2.household_id = h.id ORDER BY u2.id ASC LIMIT 1))
    JOIN auth_household_members ahm ON ahm.user_id = u.id AND ahm.household_id = h.id
    WHERE h.subscription_status = 'trial'
      AND DATE(h.created_at) <= CURRENT_DATE - INTERVAL '21 days'
      AND h.email_trial_week3_sent_at IS NULL
      AND ahm.marketing_opt_in = TRUE
    ORDER BY h.id, u.created_at ASC
    """
    households_week3 = _run(query_week3)
    for hh in households_week3:
        add_user_event(
            hh.get("email"),
            hh.get("user_name"),
            'trial_week3',
            True,
            hh.get("user_id"),
            hh.get("household_id"),
        )

    # --- 5. Activations (Day 3+, 0 items) ---
    print("Fetching Activations...")
    query_activations = """
    SELECT DISTINCT ON (h.id) 
        h.id as household_id, 
        u.id as user_id,
        u.email, 
        u.name as user_name
    FROM auth_households h
    JOIN auth_users u ON u.id = COALESCE(h.owner_id, (SELECT ahm2.user_id FROM auth_household_members ahm2 WHERE ahm2.household_id = h.id AND ahm2.role = 'owner' LIMIT 1), (SELECT u2.id FROM auth_users u2 WHERE u2.household_id = h.id ORDER BY u2.id ASC LIMIT 1))
    JOIN auth_household_members ahm ON ahm.user_id = u.id AND ahm.household_id = h.id
    LEFT JOIN list_items l ON h.id = l.household_id
    WHERE DATE(h.created_at) <= CURRENT_DATE - INTERVAL '3 days'
      AND h.email_activation_sent_at IS NULL
      AND ahm.marketing_opt_in = TRUE
    GROUP BY h.id, u.id, u.email, u.name, u.created_at
    HAVING COUNT(l.id) = 0
    ORDER BY h.id, u.created_at ASC
    """
    households_activation = _run(query_activations)
    for hh in households_activation:
        add_user_event(
            hh.get("email"),
            hh.get("user_name"),
            'activation',
            True,
            hh.get("user_id"),
            hh.get("household_id"),
        )

    # --- 6. Re-engagement (Day 14+ since last item added) ---
    print("Fetching Re-engagements...")
    query_reengagement = """
    SELECT DISTINCT ON (h.id) 
        h.id as household_id, 
        u.id as user_id,
        u.email, 
        u.name as user_name,
        MAX(l.added_at) as last_active
    FROM auth_households h
    JOIN auth_users u ON u.id = COALESCE(h.owner_id, (SELECT ahm2.user_id FROM auth_household_members ahm2 WHERE ahm2.household_id = h.id AND ahm2.role = 'owner' LIMIT 1), (SELECT u2.id FROM auth_users u2 WHERE u2.household_id = h.id ORDER BY u2.id ASC LIMIT 1))
    JOIN auth_household_members ahm ON ahm.user_id = u.id AND ahm.household_id = h.id
    JOIN list_items l ON h.id = l.household_id
    WHERE ahm.marketing_opt_in = TRUE
      AND (h.email_reengagement_sent_at IS NULL OR DATE(h.email_reengagement_sent_at) <= CURRENT_DATE - INTERVAL '30 days')
    GROUP BY h.id, u.id, u.email, u.name, u.created_at
    HAVING DATE(MAX(l.added_at)) <= CURRENT_DATE - INTERVAL '14 days'
    ORDER BY h.id, u.created_at ASC
    """
    households_reengagement = _run(query_reengagement)
    for hh in households_reengagement:
        add_user_event(
            hh.get("email"),
            hh.get("user_name"),
            'reengagement',
            True,
            hh.get("user_id"),
            hh.get("household_id"),
        )

    print(f"\nFound {len(users_to_notify)} unique users to notify.")

    if users_to_notify:
        with ThreadPoolExecutor(max_workers=min(32, len(users_to_notify))) as executor:
            futures = []
            for email, data in users_to_notify.items():
                futures.append(
                    executor.submit(
                        process_email_events,
                        email,
                        data['user_name'],
                        data['events'],
                        data.get('user_id', 0),
                        data.get('household_id', 0),
                    )
                )

            for future in as_completed(futures):
                try:
                    success = future.result()
                    if not success:
                        print("An email failed to send.")
                except Exception as exc:
                    print(f"Task generated an exception: {exc}")
    else:
        print("No emails to send today.")

    # Auto-categorize any uncategorized items
    try:
        from categorize import backfill_uncategorized_items
        stats = backfill_uncategorized_items()
        print(f"Auto-categorization sweep complete: {stats}")
    except Exception as exc:
        print(f"Auto-categorization sweep failed: {exc}")

if __name__ == "__main__":
    print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] Starting daily cron jobs...")
    run_cron()
    print("Done.")
