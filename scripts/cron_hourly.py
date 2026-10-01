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


def run_hourly_pipeline(dry_run: bool = False, force_send: bool = False, target_hour: int = 8):
    """
    Main hourly pipeline coordinating all hourly jobs.
    """
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

    args = parser.parse_args()

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
