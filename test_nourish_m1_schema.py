#!/usr/bin/env python3
"""Unit tests for Nourish Milestone 1: Normalized PostgreSQL Schema & VitalPath Seed Migration."""

import inspect
import os
import re
import sys
import unittest
from unittest.mock import MagicMock

if "psycopg2" not in sys.modules:
    mock_psycopg2 = MagicMock()
    sys.modules["psycopg2"] = mock_psycopg2
    sys.modules["psycopg2.extras"] = MagicMock()
    sys.modules["psycopg2.pool"] = MagicMock()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db_pg
import seed_nourish


class StatefulMockDB:
    """In-memory mock DB that tracks unique public food catalog items and public recipes for idempotency verification."""

    def __init__(self):
        self.executed = []
        self.public_foods = {}
        self.public_recipes = {}
        self.rowcount = 0
        self.committed = False

    def execute(self, sql, params=None):
        norm_sql = re.sub(r"\s+", " ", sql.strip())
        self.executed.append((norm_sql, params))
        self.rowcount = 0

        if "INSERT INTO nourish_food_catalog" in norm_sql and params:
            norm_name = params[1]
            is_public = bool(params[5])
            if is_public and norm_name not in self.public_foods:
                self.public_foods[norm_name] = params
                self.rowcount = 1
        elif "INSERT INTO nourish_recipes" in norm_sql and params:
            recipe_name = params[0].strip().lower()
            if recipe_name not in self.public_recipes:
                self.public_recipes[recipe_name] = params
                self.rowcount = 1
        return self

    def commit(self):
        self.committed = True

    def rollback(self):
        pass


class TestNourishM1Schema(unittest.TestCase):
    def test_all_six_nourish_tables_present_in_schema(self):
        combined_schema = "\n".join(db_pg._SCHEMA)
        expected_tables = [
            "nourish_food_catalog",
            "nourish_recipes",
            "nourish_food_logs",
            "nourish_user_goals",
            "nourish_daily_biometrics",
            "nourish_coach_notes",
        ]
        for table in expected_tables:
            self.assertIn(
                f"CREATE TABLE IF NOT EXISTS {table}",
                combined_schema,
                f"Missing table {table} in db_pg._SCHEMA",
            )

    def test_nourish_integer_foreign_keys(self):
        combined_schema = "\n".join(db_pg._SCHEMA)
        expected_fks = [
            "created_by_user_id INTEGER REFERENCES auth_users(id) ON DELETE SET NULL",
            "household_id INTEGER REFERENCES auth_households(id) ON DELETE CASCADE",
            "linked_recipe_id INTEGER REFERENCES recipes(id) ON DELETE SET NULL",
            "user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE",
            "household_id INTEGER NOT NULL REFERENCES auth_households(id) ON DELETE CASCADE",
            "catalog_id INTEGER REFERENCES nourish_food_catalog(id) ON DELETE SET NULL",
            "nourish_recipe_id INTEGER REFERENCES nourish_recipes(id) ON DELETE SET NULL",
            "still_good_item_id INTEGER REFERENCES still_good_items(id) ON DELETE SET NULL",
            "user_id INTEGER PRIMARY KEY REFERENCES auth_users(id) ON DELETE CASCADE",
        ]
        for fk in expected_fks:
            self.assertIn(fk, combined_schema, f"Missing expected INTEGER FK clause: {fk}")

    def test_nourish_indexes_present_in_schema(self):
        combined_schema = "\n".join(db_pg._SCHEMA)
        expected_indexes = [
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_nourish_cat_public_norm ON nourish_food_catalog(normalized_name) WHERE is_public = TRUE",
            "CREATE INDEX IF NOT EXISTS idx_nourish_cat_hh_norm ON nourish_food_catalog(household_id, normalized_name)",
            "CREATE INDEX IF NOT EXISTS idx_nourish_cat_search ON nourish_food_catalog(LOWER(name))",
            "CREATE INDEX IF NOT EXISTS idx_nourish_recipes_hh ON nourish_recipes(household_id)",
            "CREATE INDEX IF NOT EXISTS idx_nourish_recipes_public ON nourish_recipes(is_public) WHERE is_public = TRUE",
            "CREATE INDEX IF NOT EXISTS idx_nourish_logs_user_date ON nourish_food_logs(user_id, log_date DESC, id ASC)",
            "CREATE INDEX IF NOT EXISTS idx_nourish_logs_pending_ai ON nourish_food_logs(ai_enrich_status) WHERE ai_enrich_status = 'pending'",
            "CREATE INDEX IF NOT EXISTS idx_nourish_goals_coach_token ON nourish_user_goals(coach_token) WHERE coach_link_enabled = TRUE",
            "CREATE INDEX IF NOT EXISTS idx_nourish_bio_user_date ON nourish_daily_biometrics(user_id, log_date DESC)",
            "CREATE INDEX IF NOT EXISTS idx_nourish_coach_notes_user_date ON nourish_coach_notes(user_id, log_date DESC)",
        ]
        for idx in expected_indexes:
            self.assertIn(idx, combined_schema, f"Missing expected index: {idx}")

    def test_seed_nourish_data_completeness_and_validity(self):
        foods = seed_nourish.CURATED_AND_MIGRATED_FOODS
        recipes = seed_nourish.MIGRATED_RECIPES

        self.assertGreater(len(foods), 60, "Expected >60 unique public food items in CURATED_AND_MIGRATED_FOODS")
        self.assertEqual(len(recipes), 5, "Expected 5 migrated recipes in MIGRATED_RECIPES")

        seen_norms = set()
        curated_count = 0
        migrated_count = 0
        for item in foods:
            self.assertTrue(item.get("name"), "Food item must have a non-empty name")
            norm = item.get("normalized_name")
            self.assertTrue(norm, "Food item must have a normalized_name")
            self.assertNotIn(norm, seen_norms, f"Duplicate normalized_name in seed catalog: {norm}")
            seen_norms.add(norm)

            self.assertTrue(item.get("is_public"), f"Seed food {norm} must be public")
            self.assertGreaterEqual(float(item["calories_per_100g"]), 0.0)
            self.assertGreaterEqual(float(item["protein_per_100g"]), 0.0)
            self.assertGreaterEqual(float(item["carbs_per_100g"]), 0.0)
            self.assertGreaterEqual(float(item["fat_per_100g"]), 0.0)
            self.assertGreater(float(item["serving_weight_g"]), 0.0)

            if item.get("source") == "curated":
                curated_count += 1
            elif item.get("source") == "vitalpath_neon":
                migrated_count += 1

        self.assertEqual(curated_count, 54, "Expected all 54 curated VitalPath staples")
        self.assertGreater(migrated_count, 10, "Expected migrated custom foods from VitalPath Neon DB")

        expected_recipe_names = {
            "Grandma's Chicken & Rice Bowl",
            "General Koottu",
            "Pumpkin Kootu",
            "Tofu Coconut Chutney",
            "My Morning Cappuccino",
        }
        actual_recipe_names = {r["name"] for r in recipes}
        self.assertEqual(actual_recipe_names, expected_recipe_names)
        for rec in recipes:
            self.assertGreater(float(rec["servings"]), 0.0)
            self.assertGreater(float(rec["serving_weight_g"]), 0.0)
            self.assertGreater(float(rec["calories_per_serving"]), 0.0)
            self.assertGreater(float(rec["calories_per_100g"]), 0.0)
            self.assertTrue(rec.get("is_public"))
            self.assertIsInstance(rec.get("ingredients_json"), list)
            self.assertGreater(len(rec["ingredients_json"]), 0)

    def test_seed_nourish_has_no_hardcoded_credentials_or_network_calls(self):
        src = inspect.getsource(seed_nourish)
        self.assertNotIn("npg_", src)
        self.assertNotIn("neon.tech", src)
        self.assertNotIn("urllib", src)
        self.assertNotIn("requests", src)

    def test_seed_nourish_catalog_idempotency(self):
        mock_db = StatefulMockDB()
        first_run = seed_nourish.seed_nourish_catalog(mock_db)
        self.assertEqual(first_run["inserted_foods"], len(seed_nourish.CURATED_AND_MIGRATED_FOODS))
        self.assertEqual(first_run["inserted_recipes"], len(seed_nourish.MIGRATED_RECIPES))
        self.assertTrue(mock_db.committed)

        # Second run against same DB state should insert 0 duplicates
        second_run = seed_nourish.seed_nourish_catalog(mock_db)
        self.assertEqual(second_run["inserted_foods"], 0)
        self.assertEqual(second_run["inserted_recipes"], 0)
        self.assertEqual(len(mock_db.public_foods), len(seed_nourish.CURATED_AND_MIGRATED_FOODS))
        self.assertEqual(len(mock_db.public_recipes), len(seed_nourish.MIGRATED_RECIPES))

    def test_init_db_executes_schema_and_seeds_nourish(self):
        mock_db = StatefulMockDB()
        db_pg.init_db(mock_db)
        self.assertEqual(len(mock_db.public_foods), len(seed_nourish.CURATED_AND_MIGRATED_FOODS))
        self.assertEqual(len(mock_db.public_recipes), len(seed_nourish.MIGRATED_RECIPES))
        self.assertTrue(mock_db.committed)


if __name__ == "__main__":
    unittest.main()
