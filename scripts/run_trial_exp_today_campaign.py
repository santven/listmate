#!/usr/bin/env python3
"""
Script to execute the Trial Expiration Today Campaign ('trial_exp_today').
Delivers trial expiration emails to all households whose free trial expires today.

Usage:
    python3 scripts/run_trial_exp_today_campaign.py [options]

Options:
    --dry-run          Preview households to be notified without sending emails.
    --force            Send email even if 'trial_exp_today' was already logged in email_events.
    --household-id ID  Target a specific household ID (e.g. --household-id 58).
"""

import os
import sys
import argparse
import datetime

# Add repository root directory to Python path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SCRIPT_DIR)
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

try:
    from shared.auth import _run, is_email_suppressed
    from email_helper import send_subscription_notice
except ImportError:
    # Fallback for running from parent directory
    sys.path.insert(0, os.path.join(REPO_DIR, "listmate_repo"))
    from shared.auth import _run, is_email_suppressed
    from email_helper import send_subscription_notice


def get_extension_info(hh):
    """
    Determine if a household is eligible to claim a trial extension at trial expiry
    and return (can_extend: bool, extension_tier: str).
    """
    c_15d = hh.get("trial_ext_15d_claimed_at") or hh.get("trial_extension_claimed_at")
    c_7d = hh.get("trial_ext_7d_claimed_at")
    created_at = hh.get("created_at")
    trial_ends_at = hh.get("trial_ends_at")

    is_legacy_30d = False
    if not c_15d and created_at and trial_ends_at:
        try:
            c_dt = created_at
            if isinstance(c_dt, str):
                c_dt = (
                    datetime.datetime.fromisoformat(c_dt.replace("Z", "+00:00"))
                    if "T" in c_dt
                    else datetime.datetime.strptime(c_dt, "%Y-%m-%d %H:%M:%S")
                )
            t_dt = trial_ends_at
            if isinstance(t_dt, str):
                t_dt = (
                    datetime.datetime.fromisoformat(t_dt.replace("Z", "+00:00"))
                    if "T" in t_dt
                    else datetime.datetime.strptime(t_dt, "%Y-%m-%d %H:%M:%S")
                )

            if getattr(c_dt, "tzinfo", None) and getattr(t_dt, "tzinfo", None) is None:
                c_dt = c_dt.replace(tzinfo=None)
            elif getattr(t_dt, "tzinfo", None) and getattr(c_dt, "tzinfo", None) is None:
                t_dt = t_dt.replace(tzinfo=None)

            if (t_dt - c_dt).total_seconds() >= 20 * 86400:
                is_legacy_30d = True
        except Exception:
            pass

    if is_legacy_30d:
        # Legacy 30d households capped at 37 days max
        if not c_7d:
            return True, "7d"
        else:
            return False, "7d"
    else:
        if not c_15d:
            return True, "15d"
        elif not c_7d:
            return True, "7d"
        else:
            return False, "7d"


def run_trial_exp_today_campaign(dry_run=False, force=False, target_hhid=None):
    print("==========================================================")
    print(" Running Trial Expiration Today ('trial_exp_today') Campaign")
    print("==========================================================")
    print(f" Dry Run Mode : {dry_run}")
    print(f" Force Mode   : {force}")
    print(f" Target HH ID : {target_hhid if target_hhid else 'All Households'}")
    print("----------------------------------------------------------")

    # Base WHERE clause
    where_conditions = [
        "h.subscription_status = 'trial'",
        "(DATE(h.trial_ends_at) = CURRENT_DATE OR h.trial_ends_at BETWEEN NOW() - INTERVAL '12 hours' AND NOW() + INTERVAL '24 hours')",
        "NOT EXISTS (SELECT 1 FROM email_suppressions es WHERE LOWER(es.email) = LOWER(u.email))",
    ]

    if target_hhid:
        where_conditions.append(f"h.id = {int(target_hhid)}")

    if not force:
        where_conditions.append("""
            NOT EXISTS (
                SELECT 1 FROM email_events ee 
                WHERE ee.household_id = h.id 
                  AND ee.campaign = 'trial_exp_today' 
                  AND ee.event_type = 'sent'
            )
        """)

    query = f"""
    SELECT DISTINCT ON (h.id) 
        h.id as household_id, 
        h.name as household_name, 
        u.id as user_id, 
        u.email, 
        u.name as user_name, 
        h.subscription_status,
        h.trial_ends_at,
        h.created_at,
        h.trial_extension_claimed_at,
        h.trial_ext_15d_claimed_at,
        h.trial_ext_7d_claimed_at
    FROM auth_households h
    JOIN auth_users u ON u.id = COALESCE(
        h.owner_id, 
        (SELECT ahm2.user_id FROM auth_household_members ahm2 WHERE ahm2.household_id = h.id ORDER BY (CASE WHEN ahm2.role = 'owner' THEN 0 ELSE 1 END), ahm2.joined_at ASC LIMIT 1), 
        (SELECT u2.id FROM auth_users u2 WHERE u2.household_id = h.id ORDER BY u2.id ASC LIMIT 1)
    )
    WHERE {" AND ".join(where_conditions)}
    ORDER BY h.id, u.id ASC
    """

    try:
        candidates = _run(query)
    except Exception as e:
        print(f"Error querying database: {e}")
        return

    print(f"Found {len(candidates)} household(s) expiring today eligible for notification.")
    if not candidates:
        print("No households to notify.")
        return

    success_count = 0
    failure_count = 0

    for hh in candidates:
        hh_id = hh.get("household_id")
        user_id = hh.get("user_id")
        email = hh.get("email")
        user_name = hh.get("user_name") or "there"
        trial_ends_at = hh.get("trial_ends_at")

        if is_email_suppressed(email):
            print(f"[HH #{hh_id}] Skipping suppressed email: {email}")
            continue

        can_extend, extension_tier = get_extension_info(hh)

        print(f"\n-> Household #{hh_id} ({hh.get('household_name')})")
        print(f"   Recipient: {user_name} <{email}> (User ID: {user_id})")
        print(f"   Trial Ends At: {trial_ends_at}")
        print(f"   Can Extend: {can_extend} | Tier: {extension_tier}")

        if dry_run:
            print(f"   [DRY RUN] Would send 'trial_exp_today' email to {email}")
            success_count += 1
            continue

        # Dispatch Email
        sent = send_subscription_notice(
            to_email=email,
            user_name=user_name,
            is_trial=True,
            days_left=0,
            user_id=user_id,
            household_id=hh_id,
            can_extend=can_extend,
            extension_tier=extension_tier,
        )

        if sent:
            print(f"   [SUCCESS] Email sent to {email}")
            # Record in email_events table
            try:
                _run(
                    """
                    INSERT INTO email_events (
                        email, event_type, campaign, user_id, household_id, event_timestamp, created_at
                    ) VALUES (%s, 'sent', 'trial_exp_today', %s, %s, NOW(), NOW())
                    """,
                    (email, user_id or None, hh_id or None),
                )
                print(f"   [LOGGED] Recorded 'trial_exp_today' event in email_events")
            except Exception as exc:
                print(f"   [WARNING] Could not insert email_events record: {exc}")
            success_count += 1
        else:
            print(f"   [FAILURE] Failed to send email to {email}")
            failure_count += 1

    print("\n----------------------------------------------------------")
    print(f"Campaign Run Summary: Total: {len(candidates)} | Success: {success_count} | Failed: {failure_count}")
    print("==========================================================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Trial Expiration Today Email Campaign")
    parser.add_argument("--dry-run", action="store_true", help="Preview recipients without sending emails")
    parser.add_argument("--force", action="store_true", help="Send email even if previously logged in email_events")
    parser.add_argument("--household-id", type=int, help="Target a specific household ID")

    args = parser.parse_args()
    run_trial_exp_today_campaign(
        dry_run=args.dry_run,
        force=args.force,
        target_hhid=args.household_id,
    )
