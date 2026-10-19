#!/usr/bin/env python3
"""PostgreSQL — connection pool (ThreadedConnectionPool) for Render/Neon."""

import os, re, psycopg2, subprocess
from psycopg2 import pool as _pool

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

_pool_ctx = None

def _ensure_local_pg():
    if os.environ.get("DATABASE_URL"):
        return
    try:
        subprocess.run("mkdir -p /var/run/postgresql /tmp/pgdata && chown -R postgres:postgres /var/run/postgresql /tmp/pgdata 2>/dev/null || true", shell=True, check=False)
        check_res = subprocess.run("su - postgres -c '/usr/lib/postgresql/15/bin/pg_ctl -D /tmp/pgdata status'", shell=True, capture_output=True)
        if check_res.returncode != 0:
            subprocess.run("su - postgres -c '/usr/lib/postgresql/15/bin/initdb -D /tmp/pgdata'", shell=True, capture_output=True)
            subprocess.run("su - postgres -c '/usr/lib/postgresql/15/bin/pg_ctl -D /tmp/pgdata -l /tmp/postgres.log start'", shell=True, capture_output=True)
            subprocess.run("su - postgres -c '/usr/lib/postgresql/15/bin/createdb listmate'", shell=True, capture_output=True)
    except Exception as e:
        print(f"[db_pg] local pg check notice: {e}", flush=True)

def _get_pool():
    global _pool_ctx
    if _pool_ctx is None:
        _ensure_local_pg()
        url = os.environ.get("DATABASE_URL", "postgresql://postgres@localhost:5432/listmate")
        _pool_ctx = _pool.ThreadedConnectionPool(1, 20, url)
    return _pool_ctx

def get_db():
    import time
    pool = _get_pool()
    for attempt in range(4):
        try:
            conn = pool.getconn()
            conn.autocommit = True
            return PgConnection(conn)
        except _pool.PoolError:
            if attempt == 3:
                raise
            time.sleep(0.15 * (attempt + 1))

def close_db(conn):
    if conn:
        try: conn.close()
        except Exception: pass

def execute_query(sql, params=None):
    """Executes a SQL query and returns list of dict rows if result set exists, or commits."""
    db = get_db()
    try:
        db.execute(sql, params)
        if db._cur and db._cur.description:
            return db.fetchall()
        db.commit()
        return []
    finally:
        close_db(db)

class PgConnection:
    def __init__(self, conn):
        self._conn = conn
        self._cur = None
        self._last_rowcount = 0
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def execute(self, sql, params=None):
        sql = re.sub(r'\?', '%s', sql)
        if self._cur:
            try: self._cur.close()
            except Exception: pass
            self._cur = None

        try:
            self._cur = self._conn.cursor()
            if params: self._cur.execute(sql, params)
            else: self._cur.execute(sql)
            self._last_rowcount = self._cur.rowcount
            return self
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            # Connection dropped (e.g. SSL closed unexpectedly after idle timeout).
            # Discard dead connection, request a fresh one from the pool, and retry statement.
            try:
                _get_pool().putconn(self._conn, close=True)
            except Exception:
                pass
            self._conn = _get_pool().getconn()
            self._cur = self._conn.cursor()
            if params: self._cur.execute(sql, params)
            else: self._cur.execute(sql)
            self._last_rowcount = self._cur.rowcount
            return self

    def fetchall(self):
        if self._cur is None or self._cur.description is None: return []
        rows = self._cur.fetchall()
        return [dict(zip([d[0] for d in self._cur.description], r)) for r in rows]

    def fetchone(self):
        if self._cur is None or self._cur.description is None: return None
        row = self._cur.fetchone()
        if row is None: return None
        return dict(zip([d[0] for d in self._cur.description], row))

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._cur:
            try: self._cur.close()
            except Exception: pass
            self._cur = None
        if self._conn:
            is_broken = getattr(self._conn, 'closed', False) != 0
            if not is_broken:
                try:
                    self._conn.commit()
                except Exception:
                    is_broken = True
            try:
                _get_pool().putconn(self._conn, close=is_broken)
            except Exception:
                try: self._conn.close()
                except Exception: pass
            self._conn = None

    def commit(self):
        if self._conn and not getattr(self._conn, 'closed', False):
            self._conn.commit()

    def rollback(self):
        if self._conn and not getattr(self._conn, 'closed', False):
            self._conn.rollback()

    total_changes = property(lambda self: self._last_rowcount)
    rowcount = property(lambda self: self._last_rowcount)

_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS stores (id SERIAL PRIMARY KEY, name TEXT NOT NULL, household_id INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMP NOT NULL DEFAULT NOW())",
    "CREATE TABLE IF NOT EXISTS store_items (id SERIAL PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), name TEXT NOT NULL, category TEXT NOT NULL DEFAULT '', household_id INTEGER NOT NULL DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS list_items (id SERIAL PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), name TEXT NOT NULL, category TEXT NOT NULL DEFAULT '', added_by TEXT NOT NULL DEFAULT '', added_by_user_id INTEGER REFERENCES auth_users(id) ON DELETE SET NULL, added_at TIMESTAMP NOT NULL DEFAULT NOW(), purchased BOOLEAN NOT NULL DEFAULT FALSE, purchased_by TEXT, purchased_by_user_id INTEGER REFERENCES auth_users(id) ON DELETE SET NULL, purchased_at TIMESTAMP, quantity TEXT DEFAULT '', household_id INTEGER NOT NULL DEFAULT 1, still_good_stashed_at TIMESTAMP, stash_notified_at TIMESTAMP)",
    "CREATE TABLE IF NOT EXISTS store_visits (id SERIAL PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), household_id INTEGER NOT NULL DEFAULT 1, visit_date DATE NOT NULL, items_count INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMP NOT NULL DEFAULT NOW())",
    "CREATE TABLE IF NOT EXISTS store_enrich_queue (id SERIAL PRIMARY KEY, store_id INTEGER NOT NULL, household_id INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'pending', created_at TIMESTAMP NOT NULL DEFAULT NOW(), processed_at TIMESTAMP)",
    "CREATE INDEX IF NOT EXISTS idx_si_store ON store_items(store_id, household_id)",
    "CREATE INDEX IF NOT EXISTS idx_si_name ON store_items(LOWER(name))",
    "CREATE INDEX IF NOT EXISTS idx_li_store ON list_items(store_id, household_id, purchased)",
    "CREATE INDEX IF NOT EXISTS idx_li_name ON list_items(LOWER(name))",
    "CREATE INDEX IF NOT EXISTS idx_li_user ON list_items(household_id)",
    "CREATE INDEX IF NOT EXISTS idx_sv_store ON store_visits(store_id, household_id, visit_date)",
    "CREATE INDEX IF NOT EXISTS idx_stores_hh ON stores(household_id)",
    "CREATE TABLE IF NOT EXISTS recipes (id SERIAL PRIMARY KEY, household_id INTEGER NOT NULL DEFAULT 1, title TEXT NOT NULL, description TEXT DEFAULT '', prep_time TEXT DEFAULT '', cook_time TEXT DEFAULT '', servings TEXT DEFAULT '', cuisine TEXT DEFAULT '', dietary_tags TEXT DEFAULT '', instructions TEXT DEFAULT '', ingredients TEXT DEFAULT '', created_at TIMESTAMP NOT NULL DEFAULT NOW())",
    "CREATE INDEX IF NOT EXISTS idx_recipes_hh ON recipes(household_id)",
    "CREATE TABLE IF NOT EXISTS recipe_generations (id SERIAL PRIMARY KEY, household_id INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMP NOT NULL DEFAULT NOW())",
    "CREATE INDEX IF NOT EXISTS idx_recipe_gen_hh ON recipe_generations(household_id, created_at)",
    "CREATE TABLE IF NOT EXISTS app_feedback (id SERIAL PRIMARY KEY, household_id INTEGER, user_email TEXT, user_name TEXT, feedback_type TEXT, rating INTEGER, message TEXT, created_at TIMESTAMP NOT NULL DEFAULT NOW())",
    "CREATE TABLE IF NOT EXISTS app_invites (id SERIAL PRIMARY KEY, sender_email TEXT, household_id INTEGER, recipient_email TEXT NOT NULL, sent_at TIMESTAMP NOT NULL DEFAULT NOW())",
    "CREATE TABLE IF NOT EXISTS item_taxonomy (id SERIAL PRIMARY KEY, normalized_name VARCHAR(120) UNIQUE NOT NULL, category VARCHAR(60) NOT NULL, source VARCHAR(30) DEFAULT 'manual', created_at TIMESTAMP NOT NULL DEFAULT NOW(), updated_at TIMESTAMP NOT NULL DEFAULT NOW())",
    "CREATE INDEX IF NOT EXISTS idx_item_taxonomy_norm ON item_taxonomy(normalized_name)",
    "CREATE TABLE IF NOT EXISTS still_good_items (id SERIAL PRIMARY KEY, household_id INTEGER NOT NULL REFERENCES auth_households(id) ON DELETE CASCADE, name TEXT NOT NULL, location TEXT NOT NULL DEFAULT 'fridge', item_type TEXT NOT NULL DEFAULT 'home_cooked', servings INTEGER NOT NULL DEFAULT 1, date_added DATE NOT NULL DEFAULT CURRENT_DATE, consume_by DATE, snooze_until DATE, remind_cadence VARCHAR(16) NOT NULL DEFAULT 'daily', status TEXT NOT NULL DEFAULT 'active', consumed_at TIMESTAMP, discarded_at TIMESTAMP, thawing BOOLEAN NOT NULL DEFAULT FALSE, notes TEXT DEFAULT '', ai_estimated BOOLEAN NOT NULL DEFAULT FALSE, ai_estimated_at TIMESTAMP, shelf_life_days INTEGER, ai_tip TEXT DEFAULT '', list_item_id INTEGER REFERENCES list_items(id) ON DELETE SET NULL, store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL, category TEXT DEFAULT '', created_at TIMESTAMP NOT NULL DEFAULT NOW(), updated_at TIMESTAMP NOT NULL DEFAULT NOW())",
    "CREATE INDEX IF NOT EXISTS idx_still_good_hh_status ON still_good_items(household_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_still_good_hh_loc ON still_good_items(household_id, location)",
    "CREATE INDEX IF NOT EXISTS idx_still_good_ai_pending ON still_good_items(status, ai_estimated)",
    "CREATE INDEX IF NOT EXISTS idx_still_good_snooze ON still_good_items(household_id, snooze_until)",
    "CREATE INDEX IF NOT EXISTS idx_still_good_list_item ON still_good_items(list_item_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_still_good_store ON still_good_items(store_id)",
    "CREATE INDEX IF NOT EXISTS idx_list_items_stash_window ON list_items(household_id, purchased, still_good_stashed_at, purchased_at)",
    """CREATE TABLE IF NOT EXISTS nourish_food_catalog (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        normalized_name VARCHAR(180) NOT NULL,
        brand TEXT DEFAULT '',
        category VARCHAR(80) DEFAULT 'General',
        source VARCHAR(32) NOT NULL DEFAULT 'curated',
        is_public BOOLEAN NOT NULL DEFAULT TRUE,
        created_by_user_id INTEGER REFERENCES auth_users(id) ON DELETE SET NULL,
        household_id INTEGER REFERENCES auth_households(id) ON DELETE CASCADE,
        calories_per_100g NUMERIC(8,2) NOT NULL DEFAULT 0,
        protein_per_100g NUMERIC(8,2) NOT NULL DEFAULT 0,
        carbs_per_100g NUMERIC(8,2) NOT NULL DEFAULT 0,
        fat_per_100g NUMERIC(8,2) NOT NULL DEFAULT 0,
        fiber_per_100g NUMERIC(8,2) NOT NULL DEFAULT 0,
        sugar_per_100g NUMERIC(8,2) NOT NULL DEFAULT 0,
        sodium_mg_per_100g NUMERIC(8,2) NOT NULL DEFAULT 0,
        serving_label TEXT NOT NULL DEFAULT '1 serving (100g)',
        serving_weight_g NUMERIC(8,2) NOT NULL DEFAULT 100,
        is_liquid BOOLEAN NOT NULL DEFAULT FALSE,
        prep_state VARCHAR(20) NOT NULL DEFAULT 'as_is',
        ai_verified BOOLEAN NOT NULL DEFAULT TRUE,
        usage_count INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_nourish_cat_public_norm ON nourish_food_catalog(normalized_name) WHERE is_public = TRUE",
    "CREATE INDEX IF NOT EXISTS idx_nourish_cat_hh_norm ON nourish_food_catalog(household_id, normalized_name)",
    "CREATE INDEX IF NOT EXISTS idx_nourish_cat_search ON nourish_food_catalog(LOWER(name))",
    """CREATE TABLE IF NOT EXISTS nourish_recipes (
        id SERIAL PRIMARY KEY,
        household_id INTEGER REFERENCES auth_households(id) ON DELETE CASCADE,
        created_by_user_id INTEGER REFERENCES auth_users(id) ON DELETE SET NULL,
        linked_recipe_id INTEGER REFERENCES recipes(id) ON DELETE SET NULL,
        name TEXT NOT NULL,
        servings NUMERIC(6,2) NOT NULL DEFAULT 4,
        total_cooked_weight_g NUMERIC(10,2) NOT NULL DEFAULT 400,
        total_volume_ml NUMERIC(10,2),
        density_g_per_ml NUMERIC(6,3) DEFAULT 1.050,
        serving_weight_g NUMERIC(8,2) NOT NULL DEFAULT 100,
        raw_ingredients_text TEXT NOT NULL DEFAULT '',
        ingredients_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        calories_per_serving NUMERIC(8,2) NOT NULL DEFAULT 0,
        protein_per_serving NUMERIC(8,2) NOT NULL DEFAULT 0,
        carbs_per_serving NUMERIC(8,2) NOT NULL DEFAULT 0,
        fat_per_serving NUMERIC(8,2) NOT NULL DEFAULT 0,
        fiber_per_serving NUMERIC(8,2) NOT NULL DEFAULT 0,
        sugar_per_serving NUMERIC(8,2) NOT NULL DEFAULT 0,
        sodium_mg_per_serving NUMERIC(8,2) NOT NULL DEFAULT 0,
        calories_per_100g NUMERIC(8,2) NOT NULL DEFAULT 0,
        protein_per_100g NUMERIC(8,2) NOT NULL DEFAULT 0,
        carbs_per_100g NUMERIC(8,2) NOT NULL DEFAULT 0,
        fat_per_100g NUMERIC(8,2) NOT NULL DEFAULT 0,
        fiber_per_100g NUMERIC(8,2) NOT NULL DEFAULT 0,
        ai_notes TEXT DEFAULT '',
        is_public BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_nourish_recipes_hh ON nourish_recipes(household_id)",
    "CREATE INDEX IF NOT EXISTS idx_nourish_recipes_public ON nourish_recipes(is_public) WHERE is_public = TRUE",
    """CREATE TABLE IF NOT EXISTS nourish_food_logs (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
        household_id INTEGER NOT NULL REFERENCES auth_households(id) ON DELETE CASCADE,
        log_date DATE NOT NULL DEFAULT CURRENT_DATE,
        meal_slot VARCHAR(24) NOT NULL DEFAULT 'Breakfast',
        food_name TEXT NOT NULL,
        catalog_id INTEGER REFERENCES nourish_food_catalog(id) ON DELETE SET NULL,
        nourish_recipe_id INTEGER REFERENCES nourish_recipes(id) ON DELETE SET NULL,
        still_good_item_id INTEGER REFERENCES still_good_items(id) ON DELETE SET NULL,
        quantity NUMERIC(8,2) NOT NULL DEFAULT 100,
        unit VARCHAR(16) NOT NULL DEFAULT 'g',
        gram_weight NUMERIC(8,2) NOT NULL DEFAULT 100,
        calories NUMERIC(8,2) NOT NULL DEFAULT 0,
        protein_g NUMERIC(8,2) NOT NULL DEFAULT 0,
        carbs_g NUMERIC(8,2) NOT NULL DEFAULT 0,
        fat_g NUMERIC(8,2) NOT NULL DEFAULT 0,
        fiber_g NUMERIC(8,2) NOT NULL DEFAULT 0,
        sugar_g NUMERIC(8,2) NOT NULL DEFAULT 0,
        sodium_mg NUMERIC(8,2) NOT NULL DEFAULT 0,
        ai_enrich_status VARCHAR(20) NOT NULL DEFAULT 'complete',
        notes TEXT DEFAULT '',
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_nourish_logs_user_date ON nourish_food_logs(user_id, log_date DESC, id ASC)",
    "CREATE INDEX IF NOT EXISTS idx_nourish_logs_pending_ai ON nourish_food_logs(ai_enrich_status) WHERE ai_enrich_status = 'pending'",
    """CREATE TABLE IF NOT EXISTS nourish_user_goals (
        user_id INTEGER PRIMARY KEY REFERENCES auth_users(id) ON DELETE CASCADE,
        calories_target INTEGER NOT NULL DEFAULT 2000,
        protein_target_g INTEGER NOT NULL DEFAULT 130,
        carbs_target_g INTEGER NOT NULL DEFAULT 200,
        fat_target_g INTEGER NOT NULL DEFAULT 65,
        fiber_target_g INTEGER NOT NULL DEFAULT 30,
        water_target_ml INTEGER NOT NULL DEFAULT 2500,
        sex VARCHAR(16) DEFAULT '',
        age INTEGER,
        height_cm NUMERIC(6,2),
        weight_kg NUMERIC(6,2),
        activity_level VARCHAR(24) DEFAULT 'moderate',
        goal_pace VARCHAR(24) DEFAULT 'maintain',
        coach_token VARCHAR(64) UNIQUE,
        coach_link_enabled BOOLEAN NOT NULL DEFAULT FALSE,
        coach_display_alias TEXT DEFAULT '',
        coach_created_at TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_nourish_goals_coach_token ON nourish_user_goals(coach_token) WHERE coach_link_enabled = TRUE",
    """CREATE TABLE IF NOT EXISTS nourish_daily_biometrics (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
        log_date DATE NOT NULL DEFAULT CURRENT_DATE,
        water_ml INTEGER NOT NULL DEFAULT 0,
        weight_kg NUMERIC(6,2),
        notes TEXT DEFAULT '',
        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(user_id, log_date)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_nourish_bio_user_date ON nourish_daily_biometrics(user_id, log_date DESC)",
    """CREATE TABLE IF NOT EXISTS nourish_coach_notes (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
        log_date DATE NOT NULL DEFAULT CURRENT_DATE,
        author_role VARCHAR(16) NOT NULL DEFAULT 'coach',
        author_name VARCHAR(64) NOT NULL DEFAULT 'Coach',
        message TEXT NOT NULL,
        is_read BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_nourish_coach_notes_user_date ON nourish_coach_notes(user_id, log_date DESC)",
]

def init_db(db=None):
    own_db = db is None
    if own_db:
        db = get_db()
    try:
        for s in _SCHEMA:
            try:
                db.execute(s)
            except Exception:
                try: db.rollback()
                except Exception: pass

        def _safe_exec(stmt, params=None):
            try:
                if params: db.execute(stmt, params)
                else: db.execute(stmt)
            except Exception:
                try: db.rollback()
                except Exception: pass

        _safe_exec("ALTER TABLE app_feedback ADD COLUMN IF NOT EXISTS rating INTEGER")
        _safe_exec("ALTER TABLE app_feedback ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'open'")
        _safe_exec("ALTER TABLE app_feedback ADD COLUMN IF NOT EXISTS is_public BOOLEAN DEFAULT FALSE")
        _safe_exec("ALTER TABLE app_feedback ADD COLUMN IF NOT EXISTS public_title TEXT DEFAULT ''")
        _safe_exec("ALTER TABLE app_feedback ADD COLUMN IF NOT EXISTS public_description TEXT DEFAULT ''")
        _safe_exec("ALTER TABLE app_feedback ADD COLUMN IF NOT EXISTS public_type TEXT DEFAULT 'feature'")
        _safe_exec("ALTER TABLE app_feedback ADD COLUMN IF NOT EXISTS build_number TEXT DEFAULT ''")
        _safe_exec("ALTER TABLE app_feedback ADD COLUMN IF NOT EXISTS resolution_note TEXT DEFAULT ''")
        _safe_exec("ALTER TABLE app_feedback ADD COLUMN IF NOT EXISTS github_issue INTEGER")
        _safe_exec("ALTER TABLE app_feedback ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMP")
        _safe_exec("ALTER TABLE app_feedback ADD COLUMN IF NOT EXISTS notified_at TIMESTAMP")
        _safe_exec("ALTER TABLE app_feedback ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMP")
        _safe_exec("CREATE INDEX IF NOT EXISTS idx_feedback_public ON app_feedback(is_public, status)")
        _safe_exec("ALTER TABLE list_items ADD COLUMN IF NOT EXISTS quantity TEXT DEFAULT ''")
        _safe_exec("ALTER TABLE list_items ADD COLUMN IF NOT EXISTS recipe_tag TEXT DEFAULT ''")
        _safe_exec("ALTER TABLE list_items ADD COLUMN IF NOT EXISTS added_by_user_id INTEGER REFERENCES auth_users(id) ON DELETE SET NULL")
        _safe_exec("ALTER TABLE list_items ADD COLUMN IF NOT EXISTS purchased_by_user_id INTEGER REFERENCES auth_users(id) ON DELETE SET NULL")
        _safe_exec("ALTER TABLE list_items ADD COLUMN IF NOT EXISTS trip_notified_at TIMESTAMP")
        _safe_exec("CREATE INDEX IF NOT EXISTS idx_li_unnotified ON list_items(store_id, household_id, purchased, trip_notified_at)")
        _safe_exec("ALTER TABLE stores ADD COLUMN IF NOT EXISTS planned_visit_date DATE")
        _safe_exec("ALTER TABLE stores ADD COLUMN IF NOT EXISTS planned_visit_by TEXT")
        _safe_exec("ALTER TABLE stores ADD COLUMN IF NOT EXISTS visit_notified_users TEXT DEFAULT ''")
        _safe_exec("ALTER TABLE stores ADD COLUMN IF NOT EXISTS category_order TEXT DEFAULT ''")
        _safe_exec("ALTER TABLE stores ADD COLUMN IF NOT EXISTS cuisine TEXT DEFAULT ''")
        _safe_exec("ALTER TABLE recipes ADD COLUMN IF NOT EXISTS cuisine TEXT DEFAULT ''")
        _safe_exec("ALTER TABLE stores ADD COLUMN IF NOT EXISTS auto_populated BOOLEAN DEFAULT FALSE")
        _safe_exec("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS last_inspiration_seen_date DATE")
        _safe_exec("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS daily_inspiration_enabled BOOLEAN NOT NULL DEFAULT TRUE")
        _safe_exec("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS last_app_version VARCHAR(32) DEFAULT ''")
        _safe_exec("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS last_app_platform VARCHAR(32) DEFAULT ''")
        _safe_exec("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS last_app_build VARCHAR(32) DEFAULT ''")
        _safe_exec("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS last_active_at TIMESTAMP")
        _safe_exec("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) DEFAULT 'America/New_York'")
        _safe_exec("ALTER TABLE still_good_items ADD COLUMN IF NOT EXISTS ai_estimated BOOLEAN NOT NULL DEFAULT FALSE")
        _safe_exec("ALTER TABLE still_good_items ADD COLUMN IF NOT EXISTS ai_estimated_at TIMESTAMP")
        _safe_exec("ALTER TABLE still_good_items ADD COLUMN IF NOT EXISTS shelf_life_days INTEGER")
        _safe_exec("ALTER TABLE still_good_items ADD COLUMN IF NOT EXISTS ai_tip TEXT DEFAULT ''")
        _safe_exec("ALTER TABLE still_good_items ADD COLUMN IF NOT EXISTS snooze_until DATE")
        _safe_exec("ALTER TABLE still_good_items ADD COLUMN IF NOT EXISTS remind_cadence VARCHAR(16) DEFAULT 'daily'")
        _safe_exec("CREATE INDEX IF NOT EXISTS idx_still_good_ai_pending ON still_good_items(status, ai_estimated)")
        _safe_exec("CREATE INDEX IF NOT EXISTS idx_still_good_snooze ON still_good_items(household_id, snooze_until)")
        _safe_exec("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS nourish_enabled BOOLEAN NOT NULL DEFAULT FALSE")
        _safe_exec("ALTER TABLE nourish_food_logs ADD COLUMN IF NOT EXISTS is_shared_household BOOLEAN NOT NULL DEFAULT FALSE")
        _safe_exec("CREATE INDEX IF NOT EXISTS idx_nourish_logs_shared ON nourish_food_logs(household_id, log_date, meal_slot) WHERE is_shared_household = TRUE")

        try:
            db.execute("ALTER TABLE list_items ADD COLUMN IF NOT EXISTS still_good_stashed_at TIMESTAMP")
            db.execute("ALTER TABLE list_items ADD COLUMN IF NOT EXISTS stash_notified_at TIMESTAMP")
        except Exception:
            try: db.rollback()
            except Exception: pass

        try:
            db.execute("ALTER TABLE still_good_items ADD COLUMN IF NOT EXISTS list_item_id INTEGER REFERENCES list_items(id) ON DELETE SET NULL")
        except Exception:
            try: db.rollback()
            except Exception: pass

        try:
            db.execute("CREATE INDEX IF NOT EXISTS idx_still_good_list_item ON still_good_items(list_item_id, status)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_list_items_stash_window ON list_items(household_id, purchased, still_good_stashed_at, purchased_at)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_list_items_stash_notified ON list_items(household_id, purchased, stash_notified_at)")
        except Exception:
            try: db.rollback()
            except Exception: pass

        try:
            db.execute("ALTER TABLE still_good_items ADD COLUMN IF NOT EXISTS store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL")
            db.execute("ALTER TABLE still_good_items ADD COLUMN IF NOT EXISTS category TEXT DEFAULT ''")
            db.execute("CREATE INDEX IF NOT EXISTS idx_still_good_store ON still_good_items(store_id)")
            # Idempotent backfill from list_items
            db.execute("""
                UPDATE still_good_items sgi
                SET store_id = li.store_id
                FROM list_items li
                WHERE sgi.list_item_id = li.id
                  AND sgi.store_id IS NULL
                  AND sgi.household_id = li.household_id
            """)
        except Exception:
            try: db.rollback()
            except Exception: pass

        # Migrate still_good_items: drop default and enforce foreign key
        try:
            db.execute("ALTER TABLE still_good_items ALTER COLUMN household_id DROP DEFAULT")
        except Exception:
            try: db.rollback()
            except Exception: pass

        try:
            db.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conname = 'fk_still_good_household'
                    ) THEN
                        DELETE FROM still_good_items WHERE household_id NOT IN (SELECT id FROM auth_households);
                        ALTER TABLE still_good_items
                        ADD CONSTRAINT fk_still_good_household
                        FOREIGN KEY (household_id) REFERENCES auth_households(id) ON DELETE CASCADE;
                    END IF;
                END $$;
            """)
        except Exception:
            try: db.rollback()
            except Exception: pass

        default_aisle_patterns = [
            ("%patel%", "Produce,Spices & Seasonings,Legumes & Grains,Indian Specialties,Nuts & Seeds,Dips & Spreads,Canned & Jarred,Snacks & Sweets,Beverages,Dairy,Frozen,Household"),
            ("%indiaco%", "Produce,Spices & Seasonings,Legumes & Grains,Indian Specialties,Nuts & Seeds,Dips & Spreads,Canned & Jarred,Snacks & Sweets,Beverages,Dairy,Frozen,Household"),
            ("%indian%", "Produce,Spices & Seasonings,Legumes & Grains,Indian Specialties,Nuts & Seeds,Dips & Spreads,Canned & Jarred,Snacks & Sweets,Beverages,Dairy,Frozen,Household"),
            ("%costco%", "Produce,Bakery,Deli,Meat & Seafood,Pantry,Snacks & Sweets,Beverages,Frozen,Household,Dairy"),
            ("%whole foods%", "Produce,Bakery,Meat & Seafood,Deli,Pantry,Canned & Jarred,Dairy,Frozen,Household"),
            ("%jewel%", "Produce,Bakery,Meat & Seafood,Deli,Pantry,Canned & Jarred,Dairy,Frozen,Household"),
            ("%valli%", "Produce,Bakery,Meat & Seafood,Deli,Pantry,Canned & Jarred,Dairy,Frozen,Household")
        ]
        for pattern, order in default_aisle_patterns:
            _safe_exec("UPDATE stores SET category_order = %s WHERE name ILIKE %s AND (category_order IS NULL OR category_order = '' OR category_order NOT LIKE '%Spices%')", (order, pattern))
        _safe_exec("UPDATE stores SET category_order = 'Produce,Bakery,Meat & Seafood,Deli,Spices & Seasonings,Legumes & Grains,Pantry,Canned & Jarred,Dips & Spreads,Nuts & Seeds,Snacks & Sweets,Beverages,Dairy,Frozen,Household' WHERE (category_order IS NULL OR category_order = '')")

        try:
            from seed_nourish import seed_nourish_catalog
            seed_nourish_catalog(db)
        except Exception:
            try: db.rollback()
            except Exception: pass

        db.commit()
    finally:
        if own_db:
            close_db(db)
