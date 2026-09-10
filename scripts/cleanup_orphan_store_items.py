import os
import psycopg2
from psycopg2.extras import RealDictCursor

def run_cleanup():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL environment variable is required.")
        return

    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor(cursor_factory=RealDictCursor)

        print("Starting cleanup of orphan/ghost store items...")

        # 1. Remove store_items associated with 'General List'
        cur.execute("""
            DELETE FROM store_items
            WHERE store_id IN (
                SELECT id FROM stores WHERE name = 'General List'
            )
            RETURNING id, household_id, name;
        """)
        gen_deleted = cur.fetchall()
        print(f"Deleted {len(gen_deleted)} store_items from 'General List': {[r['name'] for r in gen_deleted]}")

        # 2. Remove cross-store ghost items (items in store_items with 0 purchases and 0 active list items at this store,
        # where the item exists in another store for this household)
        cur.execute("""
            DELETE FROM store_items si
            WHERE NOT EXISTS (
                SELECT 1 FROM list_items li
                WHERE li.household_id = si.household_id
                  AND li.store_id = si.store_id
                  AND LOWER(TRIM(li.name)) = LOWER(TRIM(si.name))
                  AND li.purchased = TRUE
            )
            AND NOT EXISTS (
                SELECT 1 FROM list_items li
                WHERE li.household_id = si.household_id
                  AND li.store_id = si.store_id
                  AND LOWER(TRIM(li.name)) = LOWER(TRIM(si.name))
                  AND li.purchased = FALSE
            )
            AND EXISTS (
                SELECT 1 FROM store_items si2
                WHERE si2.household_id = si.household_id
                  AND si2.id != si.id
                  AND LOWER(TRIM(si2.name)) = LOWER(TRIM(si.name))
            )
            RETURNING id, household_id, store_id, name;
        """)
        ghosts_deleted = cur.fetchall()
        print(f"Deleted {len(ghosts_deleted)} cross-store ghost store_items: {[r['name'] for r in ghosts_deleted]}")

        conn.commit()
        print("Cleanup completed successfully.")

    except Exception as e:
        print(f"Error during cleanup: {e}")
        if 'conn' in locals() and conn:
            conn.rollback()
    finally:
        if 'cur' in locals() and cur:
            cur.close()
        if 'conn' in locals() and conn:
            conn.close()

if __name__ == "__main__":
    run_cleanup()
