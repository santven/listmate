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
from push_helper import (
    check_trial_expiration_pushes,
    check_store_plan_push_reminders,
    check_still_good_fridge_lunch_pushes,
    check_still_good_produce_expiry_pushes,
    check_still_good_freezer_expiry_pushes,
    check_post_shopping_smart_stash_pushes,
    check_nourish_evening_diary_pushes,
    check_nourish_afternoon_hydration_pushes,
    check_dormant_list_triage_pushes,
)


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


def run_hourly_pipeline(dry_run: bool = False, force_send: bool = False, target_hour: int = 8, now_utc: datetime.datetime = None, db=None):
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
    pipeline_results["still_good_lunch_pushes"] = safe_execute_task(
        "Still Good Morning Fridge Lunch Push Reminder (7:00 AM local)",
        check_still_good_fridge_lunch_pushes,
        target_hour=7,
        dry_run=dry_run,
        force_send=force_send
    )

    # Task 4: Still Good Fresh Produce Expiry Push Reminder (10:00 AM local time)
    pipeline_results["still_good_produce_pushes"] = safe_execute_task(
        "Still Good Fresh Produce Expiry Push Reminder (10:00 AM local)",
        check_still_good_produce_expiry_pushes,
        target_hour=10,
        dry_run=dry_run,
        force_send=force_send
    )

    # Task 4b: Still Good Freezer 1-Week Expiry Push Reminder (9:00 AM local time)
    pipeline_results["still_good_freezer_pushes"] = safe_execute_task(
        "Still Good Freezer 1-Week Expiry Push Reminder (9:00 AM local)",
        check_still_good_freezer_expiry_pushes,
        target_hour=9,
        dry_run=dry_run,
        force_send=force_send
    )

    # Task 5: Store Plan Push Reminders (for stores with >= n items lacking a plan date)
    pipeline_results["store_plan_push_reminders"] = safe_execute_task(
        "Store Plan Push Reminders",
        check_store_plan_push_reminders,
        dry_run=dry_run,
        force_send=force_send
    )

    # Task 6: Still Good Post-Shopping Smart Stash Push Reminder (Runs hourly for trips >= 3 hours ago)
    pipeline_results["smart_stash_pushes"] = safe_execute_task(
        "Still Good Post-Shopping Smart Stash Push (3h post-trip)",
        check_post_shopping_smart_stash_pushes,
        dry_run=dry_run,
        force_send=force_send
    )

    # Task 7: Nourish AI Pending Food Log Batch Enrichment (Runs hourly)
    try:
        from nourish_ai import enrich_pending_nourish_logs_batch
        nourish_task_res = safe_execute_task(
            "Nourish AI Pending Food Log Batch Enrichment",
            enrich_pending_nourish_logs_batch,
            db=db,
            dry_run=dry_run
        )
        if isinstance(nourish_task_res.get("result"), dict):
            for k, v in nourish_task_res["result"].items():
                nourish_task_res.setdefault(k, v)
        pipeline_results["nourish_ai_enrichment"] = nourish_task_res
    except Exception as exc:
        logger.error(f"Nourish AI task failed to launch: {exc}")
        pipeline_results["nourish_ai_enrichment"] = {"status": "error", "error": str(exc)}

    # Task 8: Nourish Smart Evening Diary Push Reminder (8:00 PM local)
    pipeline_results["nourish_evening_diary_pushes"] = safe_execute_task(
        "Nourish Smart Evening Diary Push Reminder (8:00 PM local)",
        check_nourish_evening_diary_pushes,
        target_hour=20,
        dry_run=dry_run,
        force_send=force_send
    )

    # Task 9: Nourish Afternoon Hydration Push Reminder (3:00 PM local)
    pipeline_results["nourish_afternoon_hydration_pushes"] = safe_execute_task(
        "Nourish Afternoon Hydration Push Reminder (3:00 PM local)",
        check_nourish_afternoon_hydration_pushes,
        target_hour=15,
        dry_run=dry_run,
        force_send=force_send
    )

    # Task 10: Dormant List Triage Push Reminder (Saturday 10:00 AM local time)
    pipeline_results["dormant_list_triage_pushes"] = safe_execute_task(
        "Dormant List Triage Push Reminder (Saturday 10:00 AM local)",
        check_dormant_list_triage_pushes,
        target_hour=10,
        dry_run=dry_run,
        force_send=force_send
    )

    logger.info(f"Hourly pipeline finished. Tasks evaluated: {len(pipeline_results)}")
    for task_name, res in pipeline_results.items():
        logger.info(f" - {task_name}: {res.get('status')} ({res.get('duration_ms', 0):.1f}ms)")

    return pipeline_results


def run_hourly_jobs(db=None, dry_run: bool = False, force_send: bool = False, target_hour: int = 8, now_utc: datetime.datetime = None):
    """
    Runs all hourly jobs (including Nourish AI batch enrichment) and returns summary dict.
    """
    return run_hourly_pipeline(
        dry_run=dry_run,
        force_send=force_send,
        target_hour=target_hour,
        now_utc=now_utc,
        db=db
    )


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
        "--nourish-ai",
        action="store_true",
        help="Run Nourish AI pending food log batch enrichment immediately"
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
        "--still-good-freezer",
        action="store_true",
        help="Run Still Good freezer 1-week expiry push reminders immediately"
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

    if args.nourish_ai:
        print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] Running Nourish AI batch food log enrichment via cron_hourly...")
        try:
            from nourish_ai import enrich_pending_nourish_logs_batch
            stats = enrich_pending_nourish_logs_batch(dry_run=args.dry_run)
            print(f"Nourish AI result: {stats}")
        except Exception as exc:
            print(f"Nourish AI failed: {exc}")
        print("Done.")
        sys.exit(0)

    if args.still_good_lunch:
        print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] Running Still Good morning fridge lunch push reminders via cron_hourly...")
        try:
            from push_helper import check_still_good_fridge_lunch_pushes
            stats = check_still_good_fridge_lunch_pushes(target_hour=7, dry_run=args.dry_run, force_send=args.force)
            print(f"Still Good lunch pushes result: {stats}")
        except Exception as exc:
            print(f"Still Good lunch pushes failed: {exc}")
        print("Done.")
        sys.exit(0)

    if args.still_good_produce:
        print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] Running Still Good fresh produce expiry push reminders via cron_hourly...")
        try:
            from push_helper import check_still_good_produce_expiry_pushes
            stats = check_still_good_produce_expiry_pushes(target_hour=10, dry_run=args.dry_run, force_send=args.force)
            print(f"Still Good produce pushes result: {stats}")
        except Exception as exc:
            print(f"Still Good produce pushes failed: {exc}")
        print("Done.")
        sys.exit(0)

    if args.still_good_freezer:
        print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] Running Still Good freezer 1-week expiry push reminders via cron_hourly...")
        try:
            from push_helper import check_still_good_freezer_expiry_pushes
            stats = check_still_good_freezer_expiry_pushes(target_hour=9, dry_run=args.dry_run, force_send=args.force)
            print(f"Still Good freezer pushes result: {stats}")
        except Exception as exc:
            print(f"Still Good freezer pushes failed: {exc}")
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
