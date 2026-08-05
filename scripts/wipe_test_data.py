import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables (ensure this connects to your prod/staging DB correctly)
load_dotenv()

DB_URL = os.environ.get("DATABASE_URL")
if not DB_URL:
    print("DATABASE_URL not set in environment.")
    exit(1)

def wipe_data():
    confirm = input("WARNING: This will delete ALL data in the database (users, households, lists, stores). Type 'DELETE EVERYTHING' to confirm: ")
    if confirm != 'DELETE EVERYTHING':
        print("Aborted.")
        return

    print("Connecting to database...")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    try:
        # Tables to truncate. CASCADE will handle foreign key dependencies.
        tables = [
            "login_intents",
            "auth_sessions",
            "invites",
            "store_enrich_queue",
            "store_visits",
            "list_items",
            "store_items",
            "stores",
            "auth_users",
            "auth_households",
            "feature_flags",
            "user_settings",
            "recipes",
            "recipe_items",
            "ai_generations",
            "user_ai_limits"
        ]

        print("Executing TRUNCATE...")
        # Join tables into a single comma-separated string for a massive truncate command
        truncate_sql = f"TRUNCATE TABLE {', '.join(tables)} CASCADE;"
        cur.execute(truncate_sql)
        
        conn.commit()
        print("All test data successfully wiped. Database is now clean for production.")

    except Exception as e:
        conn.rollback()
        print("An error occurred:")
        print(e)
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    wipe_data()
