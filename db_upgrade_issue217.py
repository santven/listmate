import psycopg2
import os

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres@localhost:5432/listmate")
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

# 1. Add owner_id and downgraded_at
try:
    cur.execute("ALTER TABLE auth_households ADD COLUMN IF NOT EXISTS owner_id INTEGER;")
    cur.execute("ALTER TABLE auth_households ADD COLUMN IF NOT EXISTS downgraded_at TIMESTAMP;")
except Exception as e:
    print(e)

# Set initial owner_id to the earliest user in each household
try:
    cur.execute("""
    UPDATE auth_households h SET owner_id = (
        SELECT id FROM auth_users u WHERE u.household_id = h.id ORDER BY id ASC LIMIT 1
    ) WHERE owner_id IS NULL;
    """)
except Exception as e:
    print(e)

# Create history table
try:
    cur.execute("""
    CREATE TABLE IF NOT EXISTS household_subscription_history (
        id SERIAL PRIMARY KEY,
        household_id INTEGER NOT NULL REFERENCES auth_households(id),
        is_premium BOOLEAN,
        subscription_status TEXT,
        subscription_ends_at TIMESTAMP,
        trial_ends_at TIMESTAMP,
        downgraded_at TIMESTAMP,
        changed_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    """)
except Exception as e:
    print(e)

# Create trigger function for history
try:
    cur.execute("""
    CREATE OR REPLACE FUNCTION log_hh_sub_history()
    RETURNS TRIGGER AS $$
    BEGIN
        INSERT INTO household_subscription_history (household_id, is_premium, subscription_status, subscription_ends_at, trial_ends_at, downgraded_at)
        VALUES (NEW.id, NEW.is_premium, NEW.subscription_status, NEW.subscription_ends_at, NEW.trial_ends_at, NEW.downgraded_at);
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_log_hh_sub_history ON auth_households;
    CREATE TRIGGER trg_log_hh_sub_history
    AFTER INSERT OR UPDATE OF is_premium, subscription_status, subscription_ends_at, trial_ends_at, downgraded_at
    ON auth_households
    FOR EACH ROW
    WHEN (OLD.* IS DISTINCT FROM NEW.* OR TG_OP = 'INSERT')
    EXECUTE FUNCTION log_hh_sub_history();
    """)
except Exception as e:
    print(e)

# Create trigger function for downgraded_at
try:
    cur.execute("""
    CREATE OR REPLACE FUNCTION update_downgraded_at()
    RETURNS TRIGGER AS $$
    BEGIN
        -- If becoming premium/trial
        IF NEW.is_premium = TRUE OR NEW.subscription_status = 'trial' THEN
            NEW.downgraded_at = NULL;
        -- If losing premium explicitly
        ELSIF (NEW.is_premium = FALSE AND OLD.is_premium = TRUE) OR (NEW.subscription_status IN ('expired', 'free', 'canceled') AND OLD.subscription_status IN ('premium', 'active', 'trial')) THEN
            NEW.downgraded_at = COALESCE(NEW.downgraded_at, NOW());
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    DROP TRIGGER IF EXISTS trg_update_downgraded_at ON auth_households;
    CREATE TRIGGER trg_update_downgraded_at
    BEFORE UPDATE ON auth_households
    FOR EACH ROW
    EXECUTE FUNCTION update_downgraded_at();
    """)
except Exception as e:
    print(e)

print("Upgrade done.")
