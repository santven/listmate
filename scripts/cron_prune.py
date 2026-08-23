#!/usr/bin/env python3
import os
import sys
import datetime
import time

# Add parent directory to path to import shared modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.auth import _run

def prune_items(description, query_template, batch_size=1000):
    print(f"Starting {description} pruning...")
    total_deleted = 0
    
    # Replace the batch_size placeholder in the query template
    query = query_template.replace('{batch_size}', str(batch_size))
    
    while True:
        try:
            deleted_rows = _run(query)
            deleted_count = len(deleted_rows)
            total_deleted += deleted_count
            
            if deleted_count == 0:
                break
                
            print(f"  Deleted {deleted_count} rows in this batch...")
            time.sleep(0.1) # Small sleep to avoid hammering the DB
            
            # If we deleted less than the batch size, we're done
            if deleted_count < batch_size:
                break
                
        except Exception as e:
            print(f"Error during {description} pruning: {e}")
            break
            
    print(f"Finished {description} pruning. Total deleted: {total_deleted}")
    return total_deleted

def run_prune():
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f"[{now_str}] Starting historical list items pruning job...")
    
    # 1. Standard Free Tier
    # (is_premium = FALSE) AND (downgraded_at IS NULL OR downgraded_at < CURRENT_DATE - INTERVAL '14 days')
    # Prune older than 14 days
    free_query_template = """
    DELETE FROM list_items 
    WHERE id IN (
        SELECT l.id FROM list_items l
        JOIN auth_households h ON l.household_id = h.id
        WHERE h.is_premium = FALSE 
          AND (h.downgraded_at IS NULL OR h.downgraded_at < CURRENT_DATE - INTERVAL '14 days')
          AND l.purchased = TRUE 
          AND l.purchased_at < CURRENT_DATE - INTERVAL '14 days'
        LIMIT {batch_size}
    )
    RETURNING id
    """
    
    # 2. Premium Tier & Grace Period
    # (is_premium = TRUE) OR (is_premium = FALSE AND downgraded_at >= CURRENT_DATE - INTERVAL '14 days')
    # Prune older than 60 days
    premium_query_template = """
    DELETE FROM list_items 
    WHERE id IN (
        SELECT l.id FROM list_items l
        JOIN auth_households h ON l.household_id = h.id
        WHERE (h.is_premium = TRUE OR (h.is_premium = FALSE AND h.downgraded_at >= CURRENT_DATE - INTERVAL '14 days'))
          AND l.purchased = TRUE 
          AND l.purchased_at < CURRENT_DATE - INTERVAL '60 days'
        LIMIT {batch_size}
    )
    RETURNING id
    """
    
    total_free = prune_items("Free Tier (14-day retention)", free_query_template)
    total_premium = prune_items("Premium Tier & Grace Period (60-day retention)", premium_query_template)
    
    # 3. Email Telemetry Events (Open, Click, Delivered, etc. - 90-day retention)
    # Note: We preserve 'sent' records so lifecycle cadences and one-time emails are not re-triggered
    email_events_query_template = """
    DELETE FROM email_events 
    WHERE id IN (
        SELECT id FROM email_events
        WHERE event_type != 'sent'
          AND event_timestamp < CURRENT_DATE - INTERVAL '90 days'
        LIMIT {batch_size}
    )
    RETURNING id
    """
    total_email_events = prune_items("Email Telemetry Events (90-day retention)", email_events_query_template)

    grand_total = total_free + total_premium + total_email_events
    print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] Pruning job complete. Grand total deleted: {grand_total}")

if __name__ == "__main__":
    run_prune()
