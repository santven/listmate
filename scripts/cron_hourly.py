#!/usr/bin/env python3
"""
ListMate Unified Hourly Automation Engine (`scripts/cron_hourly.py`)

Designed to run hourly on Render Cron (`0 * * * *`).
Orchestrates time-sensitive recurring tasks, such as timezone-aware push
notifications, ephemeral cleanup, and future hourly background jobs.
"""

import os
import sys
import argparse
import datetime
import logging
import traceback

# Ensure root directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s UTC] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("cron_hourly")

from shared.auth import _init_schema, _run, _one


def safe_execute_task(task_name: str, task_fn, *args, **kwargs):
    """
    Executes a scheduled sub-task inside an isolated try/except block.
    Guarantees that a failure in one hourly task does not abort subsequent tasks.
    """
    logger.info(f"▶ Starting task: {task_name}")
    start_time = datetime.datetime.now(datetime.timezone.utc)
    try:
        result = task_fn(*args, **kwargs)
        duration_ms = (datetime.datetime.now(datetime.timezone.utc) - start_time).total_seconds() * 1000
        logger.info(f"✔ Completed task: {task_name} in {duration_ms:.1f}ms")
        return {"status": "success", "result": result, "duration_ms": duration_ms}
    except Exception as exc:
        duration_ms = (datetime.datetime.now(datetime.timezone.utc) - start_time).total_seconds() * 1000
        logger.error(f"✖ Failed task: {task_name} after {duration_ms:.1f}ms: {exc}")
        logger.error(traceback.format_exc())
        return {"status": "error", "error": str(exc), "duration_ms": duration_ms}


def check_store_plan_push_reminders(threshold_n: int = None, dry_run: bool = False, force_send: bool = False):
    """
    Store Plan Push Reminders (Hourly Cron Evaluation):
    If a store has >= threshold_n items on the active list (default 5, configurable via
    STORE_PLAN_REMINDER_THRESHOLD) and has NO planned visit date, send a push reminder
    once in a 24-hour period to active members of the household.
    Restricted to premium, trial, and active households.
    """
    _init_schema()
    from push_helper import send_push_to_household

    if threshold_n is None:
        threshold_n = int(os.environ.get("STORE_PLAN_REMINDER_THRESHOLD", 5))

    print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] Checking store plan push reminders (threshold={threshold_n}, dry_run={dry_run}, force_send={force_send})...")

    # Query for stores that have >= threshold_n uncompleted list items and NO plan date
    # Only for premium, trial (unexpired), and active households
    query = """
        SELECT 
            s.id AS store_id,
            s.name AS store_name,
            s.household_id,
            COUNT(li.id) AS items_count
        FROM stores s
        JOIN auth_households h ON h.id = s.household_id
        JOIN list_items li ON li.store_id = s.id AND li.household_id = s.household_id
        WHERE li.purchased = FALSE
          AND s.planned_visit_date IS NULL
          AND LOWER(s.name) != 'general list'
          AND (
              h.is_premium = TRUE 
              OR h.subscription_status IN ('premium', 'active')
              OR (
                  h.subscription_status = 'trial' 
                  AND (h.trial_ends_at IS NULL OR h.trial_ends_at >= NOW())
              )
          )
        GROUP BY s.id, s.name, s.household_id
        HAVING COUNT(li.id) >= %(threshold)s
        ORDER BY s.household_id ASC, items_count DESC
    """
    try:
        candidates = _run(query, {"threshold": threshold_n})
    except Exception as e:
        print(f"[check_store_plan_push_reminders] Query error: {e}", flush=True)
        return {"ok": False, "error": str(e), "dispatched": 0, "candidates": 0}

    print(f"  -> Found {len(candidates)} candidate store(s) with >= {threshold_n} items and no plan date for push.")

    dispatched_count = 0
    skipped_24h = 0
    results = []

    for cand in candidates:
        store_id = cand["store_id"]
        store_name = cand["store_name"]
        hh_id = cand["household_id"]
        items_count = cand["items_count"]

        # 24-hour deduplication check in push_notifications_log
        if not force_send:
            try:
                dedup_check = _one("""
                    SELECT 1 FROM push_notifications_log
                    WHERE ((target_type = 'household' AND target_id = %s) OR (custom_data->>'household_id' = %s))
                      AND custom_data->>'type' = 'store_plan_reminder'
                      AND custom_data->>'store_id' = %s
                      AND created_at >= NOW() - INTERVAL '24 hours'
                """, (hh_id, str(hh_id), str(store_id)))
            except Exception as d_err:
                print(f"  [Warning] Deduplication check failed for Store #{store_id}: {d_err}")
                dedup_check = None

            if dedup_check:
                skipped_24h += 1
                continue

        p_title = f"📅 Plan your trip to {store_name}"
        p_body = f"You have {items_count} items on your {store_name} list. Pick a date to plan your shopping trip!"
        p_data = {
            "type": "store_plan_reminder",
            "action": "open_store",
            "store_id": str(store_id),
            "store_name": store_name,
            "household_id": str(hh_id),
            "campaign": f"store_plan_reminder_{store_id}",
            "url": f"/?store_id={store_id}&action=plan"
        }

        if dry_run:
            print(f"  [DRY-RUN] Would send store plan push to HH #{hh_id} for Store '{store_name}' ({items_count} items): {p_title}")
            dispatched_count += 1
            results.append({
                "household_id": hh_id,
                "store_id": store_id,
                "status": "dry_run",
                "title": p_title,
                "body": p_body
            })
        else:
            try:
                res = send_push_to_household(hh_id, p_title, p_body, p_data)
                sent_cnt = res.get("sent", 0)
                mock_mode = res.get("mock", False)
                if sent_cnt > 0 or mock_mode:
                    print(f"  ✔ Sent plan reminder push to HH #{hh_id} for Store #{store_id} ({store_name}) (sent={sent_cnt}, mock={mock_mode})")
                    dispatched_count += 1
                    status_str = "sent"
                else:
                    msg = res.get("message") or res.get("error") or "No active tokens for household"
                    print(f"  ℹ Skipped plan reminder push to HH #{hh_id} for Store #{store_id} ({store_name}): {msg} (sent=0)")
                    status_str = "skipped_no_tokens"
                results.append({
                    "household_id": hh_id,
                    "store_id": store_id,
                    "status": status_str,
                    "result": res
                })
            except Exception as send_err:
                print(f"  [Error] Failed to send push to HH #{hh_id} for Store #{store_id}: {send_err}")
                results.append({
                    "household_id": hh_id,
                    "store_id": store_id,
                    "status": "error",
                    "error": str(send_err)
                })

    return {
        "ok": True,
        "dispatched": dispatched_count,
        "candidates": len(candidates),
        "skipped_24h": skipped_24h,
        "results": results,
        "dry_run": dry_run
    }


def run_hourly_pipeline(dry_run: bool = False, force_send: bool = False, target_hour: int = 8, now_utc: datetime.datetime = None):
    """
    Main hourly pipeline coordinating all hourly jobs.
    """
    if now_utc is None:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
    logger.info(f"═══════════════════════════════════════════════════════════════════════")
    logger.info(f" ListMate Hourly Cron Pipeline - {now_utc.isoformat()}")
    logger.info(f" Configuration: dry_run={dry_run}, force_send={force_send}, target_hour={target_hour}")
    logger.info(f"═══════════════════════════════════════════════════════════════════════")

    pipeline_results = {}

    # Task 1: Timezone-aware Pro Trial Expiration Push Reminders (8:00 AM local time)
    from scripts.cron_daily import check_trial_expiration_pushes
    pipeline_results["trial_expiration_pushes"] = safe_execute_task(
        "Pro Trial Expiration Push Reminders",
        check_trial_expiration_pushes,
        target_hour=target_hour,
        dry_run=dry_run,
        force_send=force_send
    )

    # Task 2: Still Good AI Shelf-Life Batch Estimator (Runs 4x daily at 12a, 6a, 12p, 6p GMT / 00:00, 06:00, 12:00, 18:00 UTC)
    if now_utc.hour in (0, 6, 12, 18) or force_send:
        try:
            from still_good_ai import enhance_still_good_shelf_life_batch
            pipeline_results["still_good_ai"] = safe_execute_task(
                "Still Good AI Shelf-Life Batch Estimator (12a/6a/12p/6p GMT)",
                enhance_still_good_shelf_life_batch,
                limit=50
            )
        except Exception as exc:
            logger.error(f"Still Good AI task failed to launch: {exc}")

    # Task 3: Still Good Morning Fridge Lunch Push Reminder (7:00 AM local time)
    from scripts.cron_daily import check_still_good_fridge_lunch_pushes
    pipeline_results["still_good_lunch_pushes"] = safe_execute_task(
        "Still Good Morning Fridge Lunch Push Reminder (7:00 AM local)",
        check_still_good_fridge_lunch_pushes,
        target_hour=7,
        dry_run=dry_run,
        force_send=force_send
    )

    # Task 4: Still Good Fresh Produce Expiry Push Reminder (10:00 AM local time)
    from scripts.cron_daily import check_still_good_produce_expiry_pushes
    pipeline_results["still_good_produce_pushes"] = safe_execute_task(
        "Still Good Fresh Produce Expiry Push Reminder (10:00 AM local)",
        check_still_good_produce_expiry_pushes,
        target_hour=10,
        dry_run=dry_run,
        force_send=force_send
    )

    # Task 5: Store Plan Push Reminders (for stores with >= n items lacking a plan date)
    plan_fn = check_store_plan_push_reminders
    try:
        from scripts import cron_daily
        if hasattr(cron_daily, "check_store_plan_push_reminders") and cron_daily.check_store_plan_push_reminders != check_store_plan_push_reminders:
            plan_fn = cron_daily.check_store_plan_push_reminders
    except Exception:
        pass
    pipeline_results["store_plan_push_reminders"] = safe_execute_task(
        "Store Plan Push Reminders",
        plan_fn,
        dry_run=dry_run,
        force_send=force_send
    )

    # -------------------------------------------------------------------------
    # Future Piggybacked Hourly Tasks can be added here cleanly:
    # e.g.,
    # pipeline_results["cart_reminders"] = safe_execute_task(...)
    # pipeline_results["cache_cleanup"] = safe_execute_task(...)
    # -------------------------------------------------------------------------

    logger.info(f"Hourly pipeline finished. Tasks evaluated: {len(pipeline_results)}")
    for task_name, res in pipeline_results.items():
        logger.info(f" - {task_name}: {res.get('status')} ({res.get('duration_ms', 0):.1f}ms)")

    return pipeline_results


def main():
    parser = argparse.ArgumentParser(description="ListMate Unified Hourly Automation Engine")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate candidates and log intended actions without dispatching pushes"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass the 8:00 AM local time restriction to force immediate evaluation"
    )
    parser.add_argument(
        "--target-hour",
        type=int,
        default=8,
        help="Target local hour for timezone evaluation (0-23, default: 8)"
    )
    parser.add_argument(
        "--still-good-ai",
        action="store_true",
        help="Run Still Good AI batch shelf-life enhancement immediately"
    )
    parser.add_argument(
        "--still-good-lunch",
        action="store_true",
        help="Run Still Good morning fridge lunch push reminders immediately"
    )
    parser.add_argument(
        "--still-good-produce",
        action="store_true",
        help="Run Still Good fresh produce expiry push reminders immediately"
    )
    parser.add_argument(
        "--store-plan-pushes", "--test-store-plan-pushes", "--test-store-plan-push", "--plan-pushes",
        dest="store_plan_pushes",
        action="store_true",
        help="Run store plan push reminders immediately"
    )

    args = parser.parse_args()

    if args.store_plan_pushes:
        print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] Running store plan push reminders via cron_hourly...")
        try:
            stats = check_store_plan_push_reminders(dry_run=args.dry_run, force_send=args.force)
            print(f"Store plan push reminders result: {stats}")
        except Exception as exc:
            print(f"Store plan push reminders failed: {exc}")
        print("Done.")
        sys.exit(0)

    if args.still_good_ai:
        print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] Running Still Good AI batch shelf-life enhancement via cron_hourly...")
        try:
            from still_good_ai import enhance_still_good_shelf_life_batch
            stats = enhance_still_good_shelf_life_batch(limit=50)
            print(f"Still Good AI result: {stats}")
        except Exception as exc:
            print(f"Still Good AI failed: {exc}")
        print("Done.")
        sys.exit(0)

    if args.still_good_lunch:
        print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] Running Still Good morning fridge lunch push reminders via cron_hourly...")
        try:
            from scripts.cron_daily import check_still_good_fridge_lunch_pushes
            stats = check_still_good_fridge_lunch_pushes(target_hour=7, dry_run=args.dry_run, force_send=args.force)
            print(f"Still Good lunch pushes result: {stats}")
        except Exception as exc:
            print(f"Still Good lunch pushes failed: {exc}")
        print("Done.")
        sys.exit(0)

    if args.still_good_produce:
        print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] Running Still Good fresh produce expiry push reminders via cron_hourly...")
        try:
            from scripts.cron_daily import check_still_good_produce_expiry_pushes
            stats = check_still_good_produce_expiry_pushes(target_hour=10, dry_run=args.dry_run, force_send=args.force)
            print(f"Still Good produce pushes result: {stats}")
        except Exception as exc:
            print(f"Still Good produce pushes failed: {exc}")
        print("Done.")
        sys.exit(0)

    results = run_hourly_pipeline(
        dry_run=args.dry_run,
        force_send=args.force,
        target_hour=args.target_hour
    )

    # Exit with code 1 if any task failed, code 0 otherwise
    has_errors = any(res.get("status") == "error" for res in results.values())
    if has_errors:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
