#!/usr/bin/env python3
import os
import sys
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent directory to path to import shared modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.auth import _run, _init_schema, is_email_suppressed
from email_helper import (
    BASE_URL,
    send_subscription_notice,
    send_solo_nudge_notice,
    send_trial_week1_checkin,
    send_trial_week3_checkin,
    send_store_nudge_notice,
    send_activation_notice,
    send_reengagement_notice,
    send_combined_notice,
    send_invite_reminder,
    send_invite_expired_notice,
    send_signup_abandon_day2,
    send_signup_abandon_day5,
    send_signup_abandon_day7,
)

def process_email_events(email, user_name, events, user_id=0, household_id=0):
    if not email or is_email_suppressed(email):
        print(f"[{email}] Skipping email dispatch — address is suppressed.")
        return False

    sent = False
    campaign_names = []
    db_updates = []

    # Priority 1: Invite Reminder (time-sensitive, highly specific action)
    if 'invite_reminder' in events:
        inv_data = events['invite_reminder']
        days_rem = inv_data.get('days_remaining', 5)
        campaign = f"invite_reminder_{'day5' if days_rem <= 2 else 'day2'}"
        campaign_names.append(campaign)
        print(f"[{email}] Priority: Sending invite reminder notice ({days_rem} days remaining, campaign: {campaign}).")
        sent = send_invite_reminder(
            email,
            inv_data['invite_link'],
            inv_data['household_name'],
            inv_data.get('inviter_name', ''),
            inv_data.get('invite_code', ''),
            days_rem,
            user_id,
            household_id
        )
        if sent:
            db_updates.append(("UPDATE invites SET reminder_count = %s, last_reminded_at = NOW() WHERE id = %s", (inv_data['new_reminder_count'], inv_data['invite_id'])))
        
        # Suppress generic signup abandon emails since the invite reminder acts as their setup path
        events.pop('signup_abandon_day2', None)
        events.pop('signup_abandon_day5', None)
        events.pop('signup_abandon_day7', None)
        events.pop('invite_reminder')

    # Priority 2: Invite Expired Notice (sent to inviter, completely disjoint from abandonment)
    if 'invite_expired' in events:
        inv_data = events['invite_expired']
        campaign_names.append('invite_expired_inviter')
        print(f"[{email}] Priority: Sending invite expired notice to inviter for invitee {inv_data.get('invitee_email')}.")
        sent_inv = send_invite_expired_notice(
            email,
            user_name,
            inv_data.get('invitee_email', ''),
            inv_data.get('household_name', 'your household'),
            user_id,
            household_id
        )
        sent = sent or sent_inv 
        if sent_inv:
            db_updates.append(("UPDATE invites SET inviter_notified_at = NOW() WHERE id = %s", (inv_data['invite_id'],)))
        events.pop('invite_expired')

    # Priority 3: Signup Abandonment Flow (cannot co-occur with nudges or expiration due to household_id = 0)
    if 'signup_abandon_day7' in events:
        campaign_names.append('signup_abandon_day7')
        print(f"[{email}] Priority: Sending Day 7 final signup abandonment notice.")
        sent_sa = send_signup_abandon_day7(email, user_name, user_id)
        sent = sent or sent_sa
        events.pop('signup_abandon_day7')
    elif 'signup_abandon_day5' in events:
        campaign_names.append('signup_abandon_day5')
        print(f"[{email}] Priority: Sending Day 5 signup abandonment reminder.")
        sent_sa = send_signup_abandon_day5(email, user_name, user_id)
        sent = sent or sent_sa
        events.pop('signup_abandon_day5')
    elif 'signup_abandon_day2' in events:
        campaign_names.append('signup_abandon_day2')
        print(f"[{email}] Priority: Sending Day 2 signup abandonment reminder.")
        sent_sa = send_signup_abandon_day2(email, user_name, user_id)
        sent = sent or sent_sa
        events.pop('signup_abandon_day2')

    # If there are still events left (expiration, trial nudges, store nudges), process them
    if events:
        if len(events) == 1:
            if 'expiration' in events:
                is_trial = events['expiration']['is_trial']
                days_left = events['expiration']['days_left']
                campaign = f"{'trial' if is_trial else 'sub'}_exp_{'today' if days_left == 0 else f'{days_left}days'}"
                campaign_names.append(campaign)
                print(f"[{email}] Sending specific expiration notice ({days_left} days, campaign: {campaign}).")
                sent_rem = send_subscription_notice(email, user_name, is_trial, days_left, user_id, household_id)
                sent = sent or sent_rem
            elif 'trial_week1' in events:
                campaign_names.append('trial_week1')
                print(f"[{email}] Sending specific trial week 1 check-in.")
                sent_rem = send_trial_week1_checkin(email, user_name, user_id, household_id)
                sent = sent or sent_rem
            elif 'trial_week3' in events:
                campaign_names.append('trial_week3')
                print(f"[{email}] Sending specific trial week 3 check-in.")
                sent_rem = send_trial_week3_checkin(email, user_name, user_id, household_id)
                sent = sent or sent_rem
            elif 'store_nudge' in events:
                campaign_names.append('store_nudge')
                print(f"[{email}] Sending specific store nudge notice.")
                sent_rem = send_store_nudge_notice(email, user_name, user_id, household_id)
                sent = sent or sent_rem
            elif 'solo_nudge' in events:
                campaign_names.append('solo_nudge')
                print(f"[{email}] Sending specific solo owner nudge notice.")
                sent_rem = send_solo_nudge_notice(email, user_name, user_id, household_id)
                sent = sent or sent_rem
            elif 'activation' in events:
                campaign_names.append('activation')
                print(f"[{email}] Sending specific activation notice.")
                sent_rem = send_activation_notice(email, user_name, user_id, household_id)
                sent = sent or sent_rem
            elif 'reengagement' in events:
                campaign_names.append('reengagement')
                print(f"[{email}] Sending specific re-engagement notice.")
                sent_rem = send_reengagement_notice(email, user_name, user_id, household_id)
                sent = sent or sent_rem
        else:
            # If there are multiple events, send the combined template
            print(f"[{email}] Sending COMBINED notice for remaining events: {list(events.keys())}")
            sent_rem = send_combined_notice(email, user_name, events, user_id, household_id)
            sent = sent or sent_rem
            for ev_key, ev_val in events.items():
                if ev_key == 'expiration':
                    is_trial = ev_val.get('is_trial', False)
                    days_left = ev_val.get('days_left', 0)
                    campaign_names.append(f"{'trial' if is_trial else 'sub'}_exp_{'today' if days_left == 0 else f'{days_left}days'}")
                else:
                    campaign_names.append(ev_key)

    # Record email sent timestamp in the email_events table and execute DB updates
    if sent:
        for sql, params in db_updates:
            try:
                _run(sql, params)
            except Exception as e:
                print(f"[{email}] Error executing DB update after email send: {e}")

        for cname in campaign_names:
            try:
                insert_sql = """
                    INSERT INTO email_events (
                        email, event_type, campaign, user_id, household_id, event_timestamp, created_at
                    ) VALUES (%s, 'sent', %s, %s, %s, NOW(), NOW())
                """
                _run(insert_sql, (email, cname, user_id or None, household_id or None))
                print(f"[{email}] Logged sent email event in email_events: campaign='{cname}', user_id={user_id}, household_id={household_id}")
            except Exception as e:
                print(f"[{email}] Error logging sent event for campaign '{cname}': {e}")

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
        if not email or is_email_suppressed(email):
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

    print("--- Diagnostic Scan ---")
    recent_hhs = _run("""
        SELECT h.id, h.name, h.created_at, h.subscription_status,
               (SELECT u.email FROM auth_users u WHERE u.id = h.owner_id OR u.household_id = h.id LIMIT 1) as user_email,
               (SELECT COUNT(*) FROM list_items l WHERE l.household_id = h.id OR l.store_id IN (SELECT s.id FROM stores s WHERE s.household_id = h.id)) as item_count,
               (SELECT COUNT(*) FROM stores s WHERE s.household_id = h.id AND TRIM(LOWER(s.name)) NOT IN ('general list', 'general', '')) as custom_stores_count
        FROM auth_households h 
        ORDER BY h.id DESC 
        LIMIT 10
    """)
    for rh in recent_hhs:
        print(f"  HH #{rh.get('id')} ({rh.get('name')}): user={rh.get('user_email')}, created={rh.get('created_at')}, items={rh.get('item_count')}, custom_stores={rh.get('custom_stores_count')}")
    print("-----------------------")

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
        h.subscription_ends_at
    FROM auth_households h
    JOIN auth_users u ON u.id = COALESCE(
        h.owner_id, 
        (SELECT ahm2.user_id FROM auth_household_members ahm2 WHERE ahm2.household_id = h.id ORDER BY (CASE WHEN ahm2.role = 'owner' THEN 0 ELSE 1 END), ahm2.joined_at ASC LIMIT 1), 
        (SELECT u2.id FROM auth_users u2 WHERE u2.household_id = h.id ORDER BY u2.id ASC LIMIT 1)
    )
    LEFT JOIN auth_household_members ahm ON ahm.user_id = u.id AND ahm.household_id = h.id
    WHERE 
        NOT EXISTS (
            SELECT 1 FROM email_suppressions es WHERE LOWER(es.email) = LOWER(u.email)
        )
        AND (
            (h.subscription_status = 'trial' AND (
                (DATE(h.trial_ends_at) = CURRENT_DATE + INTERVAL '3 days' AND NOT EXISTS (
                    SELECT 1 FROM email_events ee WHERE ee.household_id = h.id AND ee.campaign = 'trial_exp_3days' AND ee.event_type = 'sent'
                ))
                OR
                (DATE(h.trial_ends_at) = CURRENT_DATE AND NOT EXISTS (
                    SELECT 1 FROM email_events ee WHERE ee.household_id = h.id AND ee.campaign = 'trial_exp_today' AND ee.event_type = 'sent'
                ))
            ))
            OR
            (h.subscription_status IN ('premium', 'active') AND h.subscription_ends_at IS NOT NULL AND (
                (DATE(h.subscription_ends_at) = CURRENT_DATE + INTERVAL '3 days' AND NOT EXISTS (
                    SELECT 1 FROM email_events ee WHERE ee.household_id = h.id AND ee.campaign = 'sub_exp_3days' AND ee.event_type = 'sent'
                ))
                OR
                (DATE(h.subscription_ends_at) = CURRENT_DATE AND NOT EXISTS (
                    SELECT 1 FROM email_events ee WHERE ee.household_id = h.id AND ee.campaign = 'sub_exp_today' AND ee.event_type = 'sent'
                ))
            ))
        )
    ORDER BY h.id, u.id ASC
    """
    households_expiring = _run(query_expirations)
    print(f"  -> Found {len(households_expiring)} household(s) eligible for expiration notice.")
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
    JOIN auth_users u ON u.id = COALESCE(
        h.owner_id, 
        (SELECT ahm2.user_id FROM auth_household_members ahm2 WHERE ahm2.household_id = h.id ORDER BY (CASE WHEN ahm2.role = 'owner' THEN 0 ELSE 1 END), ahm2.joined_at ASC LIMIT 1), 
        (SELECT u2.id FROM auth_users u2 WHERE u2.household_id = h.id ORDER BY u2.id ASC LIMIT 1)
    )
    LEFT JOIN auth_household_members ahm ON ahm.user_id = u.id AND ahm.household_id = h.id
    WHERE (DATE(h.created_at) <= CURRENT_DATE - INTERVAL '3 days' OR h.created_at <= NOW() - INTERVAL '3 days')
      AND NOT EXISTS (
          SELECT 1 FROM email_suppressions es WHERE LOWER(es.email) = LOWER(u.email)
      )
      AND NOT EXISTS (
          SELECT 1 FROM email_events ee WHERE (ee.household_id = h.id OR ee.email = u.email) AND ee.campaign = 'solo_nudge' AND ee.event_type = 'sent'
      )
      AND COALESCE(ahm.marketing_opt_in, TRUE) = TRUE
      AND COALESCE((SELECT COUNT(*) FROM auth_household_members WHERE household_id = h.id), 1) <= 1
    ORDER BY h.id, u.id ASC
    """
    households_solo = _run(query_solo_nudge)
    print(f"  -> Found {len(households_solo)} household(s) eligible for solo nudge.")
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
    JOIN auth_users u ON u.id = COALESCE(
        h.owner_id, 
        (SELECT ahm2.user_id FROM auth_household_members ahm2 WHERE ahm2.household_id = h.id ORDER BY (CASE WHEN ahm2.role = 'owner' THEN 0 ELSE 1 END), ahm2.joined_at ASC LIMIT 1), 
        (SELECT u2.id FROM auth_users u2 WHERE u2.household_id = h.id ORDER BY u2.id ASC LIMIT 1)
    )
    LEFT JOIN auth_household_members ahm ON ahm.user_id = u.id AND ahm.household_id = h.id
    WHERE h.subscription_status = 'trial'
      AND (DATE(h.created_at) <= CURRENT_DATE - INTERVAL '7 days' OR h.created_at <= NOW() - INTERVAL '7 days')
      AND NOT EXISTS (
          SELECT 1 FROM email_suppressions es WHERE LOWER(es.email) = LOWER(u.email)
      )
      AND NOT EXISTS (
          SELECT 1 FROM email_events ee WHERE (ee.household_id = h.id OR ee.email = u.email) AND ee.campaign = 'trial_week1' AND ee.event_type = 'sent'
      )
      AND COALESCE(ahm.marketing_opt_in, TRUE) = TRUE
    ORDER BY h.id, u.id ASC
    """
    households_week1 = _run(query_week1)
    print(f"  -> Found {len(households_week1)} household(s) eligible for trial week 1 check-in.")
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
    JOIN auth_users u ON u.id = COALESCE(
        h.owner_id, 
        (SELECT ahm2.user_id FROM auth_household_members ahm2 WHERE ahm2.household_id = h.id ORDER BY (CASE WHEN ahm2.role = 'owner' THEN 0 ELSE 1 END), ahm2.joined_at ASC LIMIT 1), 
        (SELECT u2.id FROM auth_users u2 WHERE u2.household_id = h.id ORDER BY u2.id ASC LIMIT 1)
    )
    LEFT JOIN auth_household_members ahm ON ahm.user_id = u.id AND ahm.household_id = h.id
    WHERE h.subscription_status = 'trial'
      AND (DATE(h.created_at) <= CURRENT_DATE - INTERVAL '21 days' OR h.created_at <= NOW() - INTERVAL '21 days')
      AND NOT EXISTS (
          SELECT 1 FROM email_suppressions es WHERE LOWER(es.email) = LOWER(u.email)
      )
      AND NOT EXISTS (
          SELECT 1 FROM email_events ee WHERE (ee.household_id = h.id OR ee.email = u.email) AND ee.campaign = 'trial_week3' AND ee.event_type = 'sent'
      )
      AND COALESCE(ahm.marketing_opt_in, TRUE) = TRUE
    ORDER BY h.id, u.id ASC
    """
    households_week3 = _run(query_week3)
    print(f"  -> Found {len(households_week3)} household(s) eligible for trial week 3 check-in.")
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
    JOIN auth_users u ON u.id = COALESCE(
        h.owner_id, 
        (SELECT ahm2.user_id FROM auth_household_members ahm2 WHERE ahm2.household_id = h.id ORDER BY (CASE WHEN ahm2.role = 'owner' THEN 0 ELSE 1 END), ahm2.joined_at ASC LIMIT 1), 
        (SELECT u2.id FROM auth_users u2 WHERE u2.household_id = h.id ORDER BY u2.id ASC LIMIT 1)
    )
    LEFT JOIN auth_household_members ahm ON ahm.user_id = u.id AND ahm.household_id = h.id
    WHERE (DATE(h.created_at) <= CURRENT_DATE - INTERVAL '3 days' OR h.created_at <= NOW() - INTERVAL '3 days')
      AND NOT EXISTS (
          SELECT 1 FROM email_suppressions es WHERE LOWER(es.email) = LOWER(u.email)
      )
      AND NOT EXISTS (
          SELECT 1 FROM email_events ee WHERE (ee.household_id = h.id OR ee.email = u.email) AND ee.campaign = 'activation' AND ee.event_type = 'sent'
      )
      AND COALESCE(ahm.marketing_opt_in, TRUE) = TRUE
      AND NOT EXISTS (
          SELECT 1 FROM list_items l 
          WHERE l.household_id = h.id 
             OR l.store_id IN (SELECT s2.id FROM stores s2 WHERE s2.household_id = h.id)
      )
    ORDER BY h.id, u.id ASC
    """
    households_activation = _run(query_activations)
    print(f"  -> Found {len(households_activation)} household(s) eligible for activation notice.")
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
        u.name as user_name
    FROM auth_households h
    JOIN auth_users u ON u.id = COALESCE(
        h.owner_id, 
        (SELECT ahm2.user_id FROM auth_household_members ahm2 WHERE ahm2.household_id = h.id ORDER BY (CASE WHEN ahm2.role = 'owner' THEN 0 ELSE 1 END), ahm2.joined_at ASC LIMIT 1), 
        (SELECT u2.id FROM auth_users u2 WHERE u2.household_id = h.id ORDER BY u2.id ASC LIMIT 1)
    )
    LEFT JOIN auth_household_members ahm ON ahm.user_id = u.id AND ahm.household_id = h.id
    WHERE COALESCE(ahm.marketing_opt_in, TRUE) = TRUE
      AND NOT EXISTS (
          SELECT 1 FROM email_suppressions es WHERE LOWER(es.email) = LOWER(u.email)
      )
      AND NOT EXISTS (
          SELECT 1 FROM email_events ee 
          WHERE (ee.household_id = h.id OR ee.email = u.email) 
            AND ee.campaign = 'reengagement' 
            AND ee.event_type = 'sent' 
            AND ee.event_timestamp >= CURRENT_DATE - INTERVAL '30 days'
      )
      AND EXISTS (
          SELECT 1 FROM list_items l 
          WHERE (l.household_id = h.id OR l.store_id IN (SELECT s2.id FROM stores s2 WHERE s2.household_id = h.id))
      )
      AND (
          SELECT MAX(l2.added_at) FROM list_items l2 
          WHERE (l2.household_id = h.id OR l2.store_id IN (SELECT s3.id FROM stores s3 WHERE s3.household_id = h.id))
      ) <= NOW() - INTERVAL '14 days'
    ORDER BY h.id, u.id ASC
    """
    households_reengagement = _run(query_reengagement)
    print(f"  -> Found {len(households_reengagement)} household(s) eligible for re-engagement notice.")
    for hh in households_reengagement:
        add_user_event(
            hh.get("email"),
            hh.get("user_name"),
            'reengagement',
            True,
            hh.get("user_id"),
            hh.get("household_id"),
        )

    # --- 7. Store Nudge (Day 3+, 0 custom stores, has items) ---
    print("Fetching Store Nudges...")
    query_store_nudge = """
    SELECT DISTINCT ON (h.id) 
        h.id as household_id, 
        u.id as user_id, 
        u.email, 
        u.name as user_name
    FROM auth_households h
    JOIN auth_users u ON u.id = COALESCE(
        h.owner_id, 
        (SELECT ahm2.user_id FROM auth_household_members ahm2 WHERE ahm2.household_id = h.id ORDER BY (CASE WHEN ahm2.role = 'owner' THEN 0 ELSE 1 END), ahm2.joined_at ASC LIMIT 1), 
        (SELECT u2.id FROM auth_users u2 WHERE u2.household_id = h.id ORDER BY u2.id ASC LIMIT 1)
    )
    LEFT JOIN auth_household_members ahm ON ahm.user_id = u.id AND ahm.household_id = h.id
    WHERE (DATE(h.created_at) <= CURRENT_DATE - INTERVAL '3 days' OR h.created_at <= NOW() - INTERVAL '3 days')
      AND COALESCE(ahm.marketing_opt_in, TRUE) = TRUE
      AND NOT EXISTS (
          SELECT 1 FROM email_suppressions es WHERE LOWER(es.email) = LOWER(u.email)
      )
      AND NOT EXISTS (
          SELECT 1 FROM email_events ee 
          WHERE (ee.household_id = h.id OR ee.email = u.email) 
            AND ee.campaign = 'store_nudge' 
            AND ee.event_type = 'sent'
      )
      AND NOT EXISTS (
          SELECT 1 FROM stores s 
          WHERE s.household_id = h.id 
            AND TRIM(LOWER(s.name)) NOT IN ('general list', 'general', '')
      )
      AND EXISTS (
          SELECT 1 FROM list_items l 
          WHERE l.household_id = h.id 
             OR l.store_id IN (SELECT s2.id FROM stores s2 WHERE s2.household_id = h.id)
      )
    ORDER BY h.id, u.id ASC
    """
    households_store_nudge = _run(query_store_nudge)
    print(f"  -> Found {len(households_store_nudge)} household(s) eligible for store nudge.")
    for hh in households_store_nudge:
        add_user_event(
            hh.get("email"),
            hh.get("user_name"),
            'store_nudge',
            True,
            hh.get("user_id"),
            hh.get("household_id"),
        )

    # --- 8A. Pending Invites: Day 2 Gentle Reminder (Sent to Invitee) ---
    print("Fetching Pending Invites for Day 2 Reminder...")
    query_invites_day2 = """
    SELECT 
        i.id as invite_id,
        i.token,
        i.email as invitee_email,
        i.household_id,
        h.name as household_name,
        u.name as inviter_name,
        i.created_at,
        i.expires_at,
        COALESCE(i.reminder_count, 0) as reminder_count
    FROM invites i
    JOIN auth_households h ON h.id = i.household_id
    LEFT JOIN auth_users u ON u.id = i.created_by
    WHERE i.used_by IS NULL
      AND i.email IS NOT NULL AND TRIM(i.email) != ''
      AND (i.expires_at IS NULL OR i.expires_at > NOW())
      AND (DATE(i.created_at) <= CURRENT_DATE - INTERVAL '2 days' OR i.created_at <= NOW() - INTERVAL '48 hours')
      AND COALESCE(i.reminder_count, 0) = 0
      AND NOT EXISTS (
          SELECT 1 FROM email_suppressions es WHERE LOWER(es.email) = LOWER(i.email)
      )
      AND NOT EXISTS (
          SELECT 1 FROM email_events ee 
          WHERE ee.email = i.email 
            AND ee.campaign = 'invite_reminder_day2' 
            AND ee.event_type = 'sent'
            AND ee.created_at >= i.created_at
      )
    ORDER BY i.id ASC
    """
    invites_day2 = _run(query_invites_day2)
    print(f"  -> Found {len(invites_day2)} pending invite(s) eligible for Day 2 reminder.")
    for inv in invites_day2:
        invite_link = f"{BASE_URL}/login?token={inv['token']}"
        add_user_event(
            inv.get("invitee_email"),
            "",
            'invite_reminder',
            {
                'invite_id': inv.get("invite_id"),
                'invite_link': invite_link,
                'household_name': inv.get("household_name") or "the household",
                'inviter_name': inv.get("inviter_name") or "",
                'invite_code': inv.get("token"),
                'days_remaining': 5,
                'new_reminder_count': 1,
            },
            household_id=inv.get("household_id"),
        )

    # --- 8B. Pending Invites: Day 5 Final Urgency Reminder (Sent to Invitee) ---
    print("Fetching Pending Invites for Day 5 Reminder...")
    query_invites_day5 = """
    SELECT 
        i.id as invite_id,
        i.token,
        i.email as invitee_email,
        i.household_id,
        h.name as household_name,
        u.name as inviter_name,
        i.created_at,
        i.expires_at,
        COALESCE(i.reminder_count, 0) as reminder_count
    FROM invites i
    JOIN auth_households h ON h.id = i.household_id
    LEFT JOIN auth_users u ON u.id = i.created_by
    WHERE i.used_by IS NULL
      AND i.email IS NOT NULL AND TRIM(i.email) != ''
      AND (i.expires_at IS NULL OR i.expires_at > NOW())
      AND (DATE(i.created_at) <= CURRENT_DATE - INTERVAL '5 days' OR i.created_at <= NOW() - INTERVAL '120 hours')
      AND COALESCE(i.reminder_count, 0) < 2
      AND (i.last_reminded_at IS NULL OR i.last_reminded_at <= NOW() - INTERVAL '48 hours')
      AND NOT EXISTS (
          SELECT 1 FROM email_suppressions es WHERE LOWER(es.email) = LOWER(i.email)
      )
      AND NOT EXISTS (
          SELECT 1 FROM email_events ee 
          WHERE ee.email = i.email 
            AND ee.campaign = 'invite_reminder_day5' 
            AND ee.event_type = 'sent'
            AND ee.created_at >= i.created_at
      )
    ORDER BY i.id ASC
    """
    invites_day5 = _run(query_invites_day5)
    print(f"  -> Found {len(invites_day5)} pending invite(s) eligible for Day 5 reminder.")
    for inv in invites_day5:
        invite_link = f"{BASE_URL}/login?token={inv['token']}"
        add_user_event(
            inv.get("invitee_email"),
            "",
            'invite_reminder',
            {
                'invite_id': inv.get("invite_id"),
                'invite_link': invite_link,
                'household_name': inv.get("household_name") or "the household",
                'inviter_name': inv.get("inviter_name") or "",
                'invite_code': inv.get("token"),
                'days_remaining': 2,
                'new_reminder_count': 2,
            },
            household_id=inv.get("household_id"),
        )

    # --- 8C. Expired Invites: Day 7 Notice to Inviter/Owner ---
    print("Fetching Expired Invites for Inviter Notice...")
    query_invites_expired = """
    SELECT 
        i.id as invite_id,
        i.token,
        i.email as invitee_email,
        i.household_id,
        h.name as household_name,
        u.id as inviter_id,
        u.email as inviter_email,
        u.name as inviter_name
    FROM invites i
    JOIN auth_households h ON h.id = i.household_id
    JOIN auth_users u ON u.id = COALESCE(
        i.created_by,
        h.owner_id,
        (SELECT ahm.user_id FROM auth_household_members ahm WHERE ahm.household_id = h.id ORDER BY (CASE WHEN ahm.role = 'owner' THEN 0 ELSE 1 END), ahm.joined_at ASC LIMIT 1),
        (SELECT u2.id FROM auth_users u2 WHERE u2.household_id = h.id ORDER BY u2.id ASC LIMIT 1)
    )
    WHERE i.used_by IS NULL
      AND i.expires_at <= NOW()
      AND i.inviter_notified_at IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM email_suppressions es WHERE LOWER(es.email) = LOWER(u.email)
      )
      AND NOT EXISTS (
          SELECT 1 FROM email_events ee 
          WHERE (ee.email = u.email OR ee.user_id = u.id)
            AND ee.campaign = 'invite_expired_inviter' 
            AND ee.event_type = 'sent'
            AND ee.created_at >= i.created_at
      )
    ORDER BY i.id ASC
    """
    invites_expired = _run(query_invites_expired)
    print(f"  -> Found {len(invites_expired)} expired invite(s) requiring inviter notification.")
    for inv in invites_expired:
        add_user_event(
            inv.get("inviter_email"),
            inv.get("inviter_name") or "",
            'invite_expired',
            {
                'invite_id': inv.get("invite_id"),
                'invitee_email': inv.get("invitee_email"),
                'household_name': inv.get("household_name") or "your household",
            },
            user_id=inv.get("inviter_id"),
            household_id=inv.get("household_id"),
        )

    # 9A. Signup Abandonment - Day 2 Gentle Reminder (users registered 2+ days ago with household_id=0)
    print("Checking for Day 2 signup abandonment users...")
    query_abandon_day2 = """
    SELECT u.id AS user_id, u.email, u.name
    FROM auth_users u
    WHERE (u.household_id IS NULL OR u.household_id = 0)
      AND NOT EXISTS (
          SELECT 1 FROM auth_household_members ahm WHERE ahm.user_id = u.id
      )
      AND NOT EXISTS (
          SELECT 1 FROM auth_households h WHERE h.owner_id = u.id
      )
      AND (DATE(u.created_at) <= CURRENT_DATE - INTERVAL '2 days' OR u.created_at <= NOW() - INTERVAL '48 hours')
      AND (DATE(u.created_at) >= CURRENT_DATE - INTERVAL '14 days' OR u.created_at >= NOW() - INTERVAL '336 hours')
      AND NOT EXISTS (
          SELECT 1 FROM email_events ee 
          WHERE (ee.user_id = u.id OR ee.email = u.email)
            AND ee.campaign = 'signup_abandon_day2' 
            AND ee.event_type = 'sent'
      )
      AND NOT EXISTS (
          SELECT 1 FROM email_suppressions es WHERE LOWER(es.email) = LOWER(u.email)
      )
    ORDER BY u.id ASC
    """
    abandon_day2_users = _run(query_abandon_day2)
    print(f"  -> Found {len(abandon_day2_users)} Day 2 signup abandonment user(s).")
    for u in abandon_day2_users:
        add_user_event(
            u.get("email"),
            u.get("name") or "",
            'signup_abandon_day2',
            {},
            user_id=u.get("user_id"),
            household_id=0,
        )

    # 9B. Signup Abandonment - Day 5 Value & Guidance (users registered 5+ days ago with household_id=0)
    print("Checking for Day 5 signup abandonment users...")
    query_abandon_day5 = """
    SELECT u.id AS user_id, u.email, u.name
    FROM auth_users u
    WHERE (u.household_id IS NULL OR u.household_id = 0)
      AND NOT EXISTS (
          SELECT 1 FROM auth_household_members ahm WHERE ahm.user_id = u.id
      )
      AND NOT EXISTS (
          SELECT 1 FROM auth_households h WHERE h.owner_id = u.id
      )
      AND (DATE(u.created_at) <= CURRENT_DATE - INTERVAL '5 days' OR u.created_at <= NOW() - INTERVAL '120 hours')
      AND (DATE(u.created_at) >= CURRENT_DATE - INTERVAL '14 days' OR u.created_at >= NOW() - INTERVAL '336 hours')
      AND NOT EXISTS (
          SELECT 1 FROM email_events ee 
          WHERE (ee.user_id = u.id OR ee.email = u.email)
            AND ee.campaign = 'signup_abandon_day5' 
            AND ee.event_type = 'sent'
      )
      AND NOT EXISTS (
          SELECT 1 FROM email_suppressions es WHERE LOWER(es.email) = LOWER(u.email)
      )
    ORDER BY u.id ASC
    """
    abandon_day5_users = _run(query_abandon_day5)
    print(f"  -> Found {len(abandon_day5_users)} Day 5 signup abandonment user(s).")
    for u in abandon_day5_users:
        add_user_event(
            u.get("email"),
            u.get("name") or "",
            'signup_abandon_day5',
            {},
            user_id=u.get("user_id"),
            household_id=0,
        )

    # 9C. Signup Abandonment - Day 7 Final Urgency Notice (users registered 7+ days ago with household_id=0)
    print("Checking for Day 7 signup abandonment users...")
    query_abandon_day7 = """
    SELECT u.id AS user_id, u.email, u.name
    FROM auth_users u
    WHERE (u.household_id IS NULL OR u.household_id = 0)
      AND NOT EXISTS (
          SELECT 1 FROM auth_household_members ahm WHERE ahm.user_id = u.id
      )
      AND NOT EXISTS (
          SELECT 1 FROM auth_households h WHERE h.owner_id = u.id
      )
      AND (DATE(u.created_at) <= CURRENT_DATE - INTERVAL '7 days' OR u.created_at <= NOW() - INTERVAL '168 hours')
      AND (DATE(u.created_at) >= CURRENT_DATE - INTERVAL '14 days' OR u.created_at >= NOW() - INTERVAL '336 hours')
      AND NOT EXISTS (
          SELECT 1 FROM email_events ee 
          WHERE (ee.user_id = u.id OR ee.email = u.email)
            AND ee.campaign = 'signup_abandon_day7' 
            AND ee.event_type = 'sent'
      )
      AND NOT EXISTS (
          SELECT 1 FROM email_suppressions es WHERE LOWER(es.email) = LOWER(u.email)
      )
    ORDER BY u.id ASC
    """
    abandon_day7_users = _run(query_abandon_day7)
    print(f"  -> Found {len(abandon_day7_users)} Day 7 signup abandonment user(s).")
    for u in abandon_day7_users:
        add_user_event(
            u.get("email"),
            u.get("name") or "",
            'signup_abandon_day7',
            {},
            user_id=u.get("user_id"),
            household_id=0,
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

    # 10. Engagement-Aware Signup Abandonment Cleanup (Day 10+ unattached registrations)
    try:
        cleanup_abandoned_signups()
    except Exception as exc:
        print(f"Signup abandonment cleanup routine failed: {exc}")

    # Auto-categorize any uncategorized items
    try:
        from categorize import backfill_uncategorized_items
        stats = backfill_uncategorized_items()
        print(f"Auto-categorization sweep complete: {stats}")
    except Exception as exc:
        print(f"Auto-categorization sweep failed: {exc}")


def cleanup_abandoned_signups():
    """Prune unattached user registrations (Day 10+, no household) with engagement protection.
    
    Engagement Protection Rules:
    - Never delete if user clicked any email in the last 14 days.
    - Never delete if user opened any email in the last 7 days.
    - User must have received the final Day 7 notice (or be older than 30 days).
    """
    print("Checking for stale signup-abandoned registrations to clean up...")
    query = """
    SELECT u.id, u.email, u.name, u.created_at
    FROM auth_users u
    WHERE (u.household_id IS NULL OR u.household_id = 0)
      AND NOT EXISTS (
          SELECT 1 FROM auth_household_members ahm WHERE ahm.user_id = u.id
      )
      AND NOT EXISTS (
          SELECT 1 FROM auth_households h WHERE h.owner_id = u.id
      )
      AND (DATE(u.created_at) <= CURRENT_DATE - INTERVAL '10 days' OR u.created_at <= NOW() - INTERVAL '240 hours')
      AND (
          EXISTS (
              SELECT 1 FROM email_events ee 
              WHERE (ee.user_id = u.id OR ee.email = u.email)
                AND ee.campaign = 'signup_abandon_day7' 
                AND ee.event_type = 'sent'
          )
          OR (DATE(u.created_at) <= CURRENT_DATE - INTERVAL '30 days')
      )
      AND NOT EXISTS (
          SELECT 1 FROM email_events ee 
          WHERE (ee.user_id = u.id OR ee.email = u.email)
            AND ee.event_type = 'click'
            AND ee.event_timestamp >= NOW() - INTERVAL '14 days'
      )
      AND NOT EXISTS (
          SELECT 1 FROM email_events ee 
          WHERE (ee.user_id = u.id OR ee.email = u.email)
            AND ee.event_type = 'open'
            AND ee.event_timestamp >= NOW() - INTERVAL '7 days'
      )
    ORDER BY u.id ASC
    LIMIT 100
    """
    candidates = _run(query)
    deleted_count = 0
    for cand in candidates:
        uid = cand.get('id')
        uemail = cand.get('email')
        try:
            # 1. Clear feature flags
            _run("DELETE FROM auth_feature_flags WHERE user_id = %s", (uid,))
            # 2. Clear user aliases
            _run("DELETE FROM auth_user_aliases WHERE user_id = %s", (uid,))
            # 3. Clear login intents
            _run("DELETE FROM login_intents WHERE user_id = %s", (uid,))
            # 4. Delete unattached user (email_events has ON DELETE SET NULL on user_id)
            _run("DELETE FROM auth_users WHERE id = %s", (uid,))
            deleted_count += 1
            print(f"  [Cleanup] Deleted stale abandoned user #{uid} ({uemail}, created {cand.get('created_at')}).")
        except Exception as exc:
            print(f"  [Cleanup] Error deleting stale user #{uid}: {exc}")
    print(f"Stale signup abandonment cleanup complete: {deleted_count} user(s) removed.")
    return deleted_count


if __name__ == "__main__":
    print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] Starting daily cron jobs...")
    run_cron()
    print("Done.")
