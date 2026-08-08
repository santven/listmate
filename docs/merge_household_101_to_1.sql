-- Comprehensive SQL to merge Household 101 into Household 1
-- This resolves foreign key constraint errors and duplicate key conflicts
-- by reassigning all related records to household 1, avoiding primary key 
-- conflicts in member tables, and then safely dropping household 101.

BEGIN;

-- 1. Update auth_users
UPDATE auth_users 
SET household_id = 1 
WHERE household_id = 101;

-- 2. Update auth_household_members (handle potential PK duplicates safely)
UPDATE auth_household_members 
SET household_id = 1 
WHERE household_id = 101 
  AND user_id NOT IN (SELECT user_id FROM auth_household_members WHERE household_id = 1);

DELETE FROM auth_household_members 
WHERE household_id = 101;

-- 3. Update other auth-related tables
UPDATE invites 
SET household_id = 1 
WHERE household_id = 101;

UPDATE household_subscription_history 
SET household_id = 1 
WHERE household_id = 101;

-- 4. Update core app tables
UPDATE stores 
SET household_id = 1 
WHERE household_id = 101;

UPDATE store_items 
SET household_id = 1 
WHERE household_id = 101;

UPDATE list_items 
SET household_id = 1 
WHERE household_id = 101;

UPDATE store_visits 
SET household_id = 1 
WHERE household_id = 101;

UPDATE store_enrich_queue 
SET household_id = 1 
WHERE household_id = 101;

UPDATE recipe_generations 
SET household_id = 1 
WHERE household_id = 101;

-- 5. Delete the old household now that all dependencies have been moved
DELETE FROM auth_households 
WHERE id = 101;

COMMIT;
