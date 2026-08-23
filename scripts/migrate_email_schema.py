import os
import sys

# Support PROD_DATABASE_URL fallback if DATABASE_URL is not explicitly set
if os.environ.get("PROD_DATABASE_URL") and not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["PROD_DATABASE_URL"]
if os.environ.get("PROD_DB_URL") and not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["PROD_DB_URL"]

# Add parent directory to path to import shared modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.auth import _run

def migrate_and_clean():
    print("Starting data migration from auth_households to email_events...")
    
    columns_to_campaigns = {
        'email_solo_nudge_sent_at': 'solo_nudge',
        'email_trial_week1_sent_at': 'trial_week1',
        'email_trial_week3_sent_at': 'trial_week3',
        'email_activation_sent_at': 'activation',
        'email_reengagement_sent_at': 'reengagement',
        'email_trial_exp_3days_sent_at': 'trial_exp_3days',
        'email_trial_exp_today_sent_at': 'trial_exp_today',
        'email_sub_exp_3days_sent_at': 'sub_exp_3days',
        'email_sub_exp_today_sent_at': 'sub_exp_today'
    }
    
    # 1. Migrate Data
    for col, campaign in columns_to_campaigns.items():
        try:
            sql = f"""
                INSERT INTO email_events (email, event_type, campaign, household_id, user_id, event_timestamp, created_at)
                SELECT u.email, 'sent', '{campaign}', h.id, u.id, h.{col}, h.{col}
                FROM auth_households h
                JOIN auth_users u ON u.household_id = h.id AND u.is_owner = TRUE
                WHERE h.{col} IS NOT NULL
            """
            _run(sql)
            print(f"Migrated '{campaign}' events successfully.")
        except Exception as e:
            if "column h." + col + " does not exist" in str(e).lower() or "column" in str(e).lower():
                print(f"Column {col} already dropped or doesn't exist. Skipping migration for {campaign}.")
            else:
                print(f"Error migrating {campaign}: {e}")

    # 2. Drop the old columns
    print("\nDropping legacy email tracking columns from auth_households...")
    for col in columns_to_campaigns.keys():
        try:
            _run(f"ALTER TABLE auth_households DROP COLUMN {col}")
            print(f"Dropped {col}")
        except Exception as e:
            if "does not exist" in str(e):
                print(f"Column {col} already dropped.")
            else:
                print(f"Error dropping {col}: {e}")

    print("\nMigration and cleanup complete!")

if __name__ == "__main__":
    migrate_and_clean()
