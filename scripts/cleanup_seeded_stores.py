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
        
        target_stores = ["Costco", "Whole Foods", "Valli", "Patel / IndiaCo", "Jewel", "Amazon"]
        
        print("Starting cleanup of auto-seeded stores...")
        
        for store_name in target_stores:
            # Find stores with this name
            cur.execute("SELECT id, household_id, name FROM stores WHERE name = %s", (store_name,))
            stores = cur.fetchall()
            
            deleted_count = 0
            skipped_count = 0
            
            for store in stores:
                store_id = store['id']
                hh_id = store['household_id']
                
                # Check if there are any active or purchased items in list_items
                cur.execute("SELECT COUNT(*) as cnt FROM list_items WHERE store_id = %s", (store_id,))
                list_items_count = cur.fetchone()['cnt']
                
                # Check if there are any items in store_items catalog
                cur.execute("SELECT COUNT(*) as cnt FROM store_items WHERE store_id = %s", (store_id,))
                store_items_count = cur.fetchone()['cnt']
                
                # Check if there are any store visits
                cur.execute("SELECT COUNT(*) as cnt FROM store_visits WHERE store_id = %s", (store_id,))
                store_visits_count = cur.fetchone()['cnt']
                
                total_usage = list_items_count + store_items_count + store_visits_count
                
                if total_usage == 0:
                    # Safe to delete
                    cur.execute("DELETE FROM stores WHERE id = %s", (store_id,))
                    deleted_count += 1
                else:
                    skipped_count += 1
                    print(f"  - Skipped '{store_name}' (ID: {store_id}) for Household {hh_id} - Has {total_usage} associated records.")
            
            print(f"Store '{store_name}': Deleted {deleted_count} empty instances. Skipped {skipped_count} active instances.")
            
        conn.commit()
        print("\nCleanup completed successfully!")
        
    except Exception as e:
        print(f"An error occurred: {e}")
        if 'conn' in locals():
            conn.rollback()
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    run_cleanup()
