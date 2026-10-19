#!/usr/bin/env python3
"""
Unit tests for Nourish Milestone 2 (Issue #673):
- Core Backend API (`/api/nourish/*`)
- Strict `user_id` privacy isolation within a shared `household_id`
- Household Premium entitlement gating & read-only guard
- 4-Tier Food Lookup & 4-Unit Scaling (`g`, `oz`, `ml`, `serving`)
- Hourly Cron Gemini Batch Enrichment (`nourish_ai.enrich_pending_nourish_logs_batch` & `scripts/cron_hourly.py`)
"""

import datetime
import json
import os
import re
import sys
import unittest
from unittest.mock import MagicMock, patch

# Defensive mocking of external C-extensions if missing locally
for mod in [
    "google",
    "google.oauth2",
    "google.auth",
    "google.auth.transport",
    "google.auth.exceptions",
    "psycopg2",
    "psycopg2.extras",
    "psycopg2.pool",
    "requests",
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

if "flask_limiter" not in sys.modules:
    mock_limiter = MagicMock()
    mock_limiter.Limiter.return_value.limit.return_value = lambda f: f
    sys.modules["flask_limiter"] = mock_limiter
    sys.modules["flask_limiter.util"] = MagicMock()

os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL", "postgresql://dummy:5432/test")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app as app_module
import nourish_ai
import push_helper
import scripts.cron_hourly as cron_hourly
from seed_nourish import normalize_food_name
import shared.auth as authmod


class InMemoryNourishDB:
    """Stateful in-memory PostgreSQL emulator for Nourish M2 tables."""

    def __init__(self):
        self.catalog = {}  # id -> dict
        self.recipes = {}  # id -> dict
        self.logs = {}     # id -> dict
        self.goals = {}    # user_id -> dict
        self.biometrics = {}  # (user_id, log_date) -> dict
        self.users = {}       # user_id -> dict
        self.ai_usage = {}    # (user_id, usage_date_str) -> int count
        self.coach_notes = {} # id -> dict
        self._next_cat_id = 1
        self._next_rec_id = 1
        self._next_log_id = 1
        self._next_bio_id = 1
        self._next_note_id = 1
        self._result_rows = []
        self.rowcount = 0
        self.committed = False

        # Seed a sample public catalog item (Chicken Breast Cooked) and Banana
        self.insert_catalog({
            "name": "Chicken Breast (Cooked)",
            "normalized_name": "chicken breast (cooked)",
            "brand": "",
            "category": "Meat & Poultry",
            "source": "curated",
            "is_public": True,
            "household_id": None,
            "calories_per_100g": 165.0,
            "protein_per_100g": 31.0,
            "carbs_per_100g": 0.0,
            "fat_per_100g": 3.6,
            "fiber_per_100g": 0.0,
            "sugar_per_100g": 0.0,
            "sodium_mg_per_100g": 74.0,
            "serving_label": "1 breast (150g)",
            "serving_weight_g": 150.0,
            "is_liquid": False,
            "prep_state": "cooked",
            "ai_verified": True,
            "usage_count": 0,
        })
        self.insert_catalog({
            "name": "Banana",
            "normalized_name": "banana",
            "brand": "",
            "category": "Fruits",
            "source": "curated",
            "is_public": True,
            "household_id": None,
            "calories_per_100g": 89.0,
            "protein_per_100g": 1.1,
            "carbs_per_100g": 22.8,
            "fat_per_100g": 0.3,
            "fiber_per_100g": 2.6,
            "sugar_per_100g": 12.2,
            "sodium_mg_per_100g": 1.0,
            "serving_label": "1 medium (118g)",
            "serving_weight_g": 118.0,
            "is_liquid": False,
            "prep_state": "as_is",
            "ai_verified": True,
            "usage_count": 5,
        })
        # Seed a sample public recipe
        self.insert_recipe({
            "household_id": None,
            "created_by_user_id": None,
            "linked_recipe_id": None,
            "name": "General Koottu",
            "servings": 4.0,
            "total_cooked_weight_g": 800.0,
            "total_volume_ml": 760.0,
            "density_g_per_ml": 1.05,
            "serving_weight_g": 200.0,
            "raw_ingredients_text": "200g snake gourd, 100g cooked moong dal",
            "ingredients_json": [{"name": "Moong Dal", "quantity_g": 200}],
            "calories_per_serving": 220.0,
            "protein_per_serving": 10.0,
            "carbs_per_serving": 30.0,
            "fat_per_serving": 6.0,
            "fiber_per_serving": 5.0,
            "sugar_per_serving": 2.0,
            "sodium_mg_per_serving": 240.0,
            "calories_per_100g": 110.0,
            "protein_per_100g": 5.0,
            "carbs_per_100g": 15.0,
            "fat_per_100g": 3.0,
            "fiber_per_100g": 2.5,
            "ai_notes": "Seeded recipe",
            "is_public": True,
        })

    def insert_catalog(self, item):
        cid = self._next_cat_id
        self._next_cat_id += 1
        row = {"id": cid, "usage_count": 0, **item}
        self.catalog[cid] = row
        return row

    def insert_recipe(self, rec):
        rid = self._next_rec_id
        self._next_rec_id += 1
        row = {"id": rid, **rec}
        self.recipes[rid] = row
        return row

    def execute(self, sql, params=None):
        norm = re.sub(r"\s+", " ", sql.strip())
        params = tuple(params or ())
        self._result_rows = []
        self.rowcount = 0

        # 1. Pending AI logs query in nourish_ai.py
        if "FROM nourish_food_logs WHERE ai_enrich_status = 'pending'" in norm:
            limit = int(params[0]) if params else 50
            pending = [
                dict(r) for r in sorted(self.logs.values(), key=lambda x: x["id"])
                if r.get("ai_enrich_status") == "pending"
            ][:limit]
            self._result_rows = pending
            self.rowcount = len(pending)
            return self

        # 2. Daily food logs query in GET /api/nourish/day
        if "SELECT * FROM nourish_food_logs WHERE user_id = ? AND log_date = ?::date" in norm:
            uid, d_str = int(params[0]), str(params[1])[:10]
            matched = [
                dict(r) for r in sorted(self.logs.values(), key=lambda x: x["id"])
                if int(r["user_id"]) == uid and str(r["log_date"])[:10] == d_str
            ]
            self._result_rows = matched
            self.rowcount = len(matched)
            return self

        # 3. Single food log lookup by id AND user_id AND household_id
        if "SELECT * FROM nourish_food_logs WHERE id = ? AND user_id = ?" in norm:
            lid, uid = int(params[0]), int(params[1])
            hhid = int(params[2]) if len(params) > 2 else None
            row = self.logs.get(lid)
            if row and int(row["user_id"]) == uid and (hhid is None or int(row.get("household_id", 0)) == hhid):
                self._result_rows = [dict(row)]
                self.rowcount = 1
            return self

        # 4. DELETE food log by id AND user_id AND household_id
        if "DELETE FROM nourish_food_logs WHERE id = ? AND user_id = ?" in norm:
            lid, uid = int(params[0]), int(params[1])
            hhid = int(params[2]) if len(params) > 2 else None
            row = self.logs.get(lid)
            if row and int(row["user_id"]) == uid and (hhid is None or int(row.get("household_id", 0)) == hhid):
                del self.logs[lid]
                self._result_rows = [{"id": lid}]
                self.rowcount = 1
            return self

        # 5. INSERT INTO nourish_food_logs
        if "INSERT INTO nourish_food_logs" in norm:
            lid = self._next_log_id
            self._next_log_id += 1
            row = {
                "id": lid,
                "user_id": int(params[0]),
                "household_id": int(params[1]),
                "log_date": str(params[2])[:10],
                "meal_slot": params[3],
                "food_name": params[4],
                "catalog_id": params[5],
                "nourish_recipe_id": params[6],
                "still_good_item_id": params[7],
                "quantity": float(params[8]),
                "unit": params[9],
                "gram_weight": float(params[10]),
                "calories": float(params[11]),
                "protein_g": float(params[12]),
                "carbs_g": float(params[13]),
                "fat_g": float(params[14]),
                "fiber_g": float(params[15]),
                "sugar_g": float(params[16]),
                "sodium_mg": float(params[17]),
                "ai_enrich_status": params[18],
                "notes": params[19],
                "is_shared_household": bool(params[20]) if len(params) > 20 else False,
            }
            self.logs[lid] = row
            self._result_rows = [dict(row)]
            self.rowcount = 1
            return self

        # 6. UPDATE nourish_food_logs from cron batch enrichment
        if "UPDATE nourish_food_logs" in norm and "ai_enrich_status = 'complete'" in norm and "WHERE id = ?" in norm:
            lid = int(params[9])
            row = self.logs.get(lid)
            if row:
                row["calories"] = float(params[0])
                row["protein_g"] = float(params[1])
                row["carbs_g"] = float(params[2])
                row["fat_g"] = float(params[3])
                row["fiber_g"] = float(params[4])
                row["sugar_g"] = float(params[5])
                row["sodium_mg"] = float(params[6])
                row["gram_weight"] = float(params[7])
                if params[8] is not None:
                    row["catalog_id"] = int(params[8])
                row["ai_enrich_status"] = "complete"
                self.rowcount = 1
            return self

        # 7. UPDATE nourish_food_logs from PUT /api/nourish/logs/<id>
        if "UPDATE nourish_food_logs" in norm and "WHERE id = ? AND user_id = ?" in norm:
            lid, uid = int(params[14]), int(params[15])
            hhid = int(params[16]) if len(params) > 16 else None
            row = self.logs.get(lid)
            if row and int(row["user_id"]) == uid and (hhid is None or int(row.get("household_id", 0)) == hhid):
                row["food_name"] = params[0]
                row["meal_slot"] = params[1]
                row["quantity"] = float(params[2])
                row["unit"] = params[3]
                row["gram_weight"] = float(params[4])
                row["calories"] = float(params[5])
                row["protein_g"] = float(params[6])
                row["carbs_g"] = float(params[7])
                row["fat_g"] = float(params[8])
                row["fiber_g"] = float(params[9])
                row["sugar_g"] = float(params[10])
                row["sodium_mg"] = float(params[11])
                row["ai_enrich_status"] = params[12]
                row["notes"] = params[13]
                self._result_rows = [dict(row)]
                self.rowcount = 1
            return self

        # 8. Catalog lookup by id
        if "SELECT * FROM nourish_food_catalog WHERE id = ?" in norm:
            cid, hhid = int(params[0]), int(params[1])
            row = self.catalog.get(cid)
            if row and (row.get("is_public") or row.get("household_id") == hhid):
                self._result_rows = [dict(row)]
                self.rowcount = 1
            return self

        # 9. Catalog lookup by normalized_name
        if "SELECT * FROM nourish_food_catalog WHERE normalized_name = ?" in norm:
            norm_name, hhid = params[0], int(params[1])
            matches = [
                dict(c) for c in self.catalog.values()
                if c.get("normalized_name") == norm_name and (c.get("is_public") or c.get("household_id") == hhid)
            ]
            matches.sort(key=lambda c: (0 if c.get("household_id") == hhid else 1, c["id"]))
            if matches:
                self._result_rows = [matches[0]]
                self.rowcount = 1
            return self

        # 10. Catalog search
        if "SELECT * FROM nourish_food_catalog WHERE (is_public = TRUE OR household_id = ?)" in norm:
            hhid = int(params[0])
            q = str(params[3])
            matches = [
                dict(c) for c in self.catalog.values()
                if (c.get("is_public") or c.get("household_id") == hhid)
                and (q in c.get("normalized_name", "") or q in c.get("name", "").lower())
            ]
            self._result_rows = matches
            self.rowcount = len(matches)
            return self

        if "SELECT * FROM nourish_food_catalog WHERE is_public = TRUE OR household_id = ?" in norm:
            hhid = int(params[0])
            matches = [
                dict(c) for c in self.catalog.values()
                if c.get("is_public") or c.get("household_id") == hhid
            ]
            self._result_rows = matches
            self.rowcount = len(matches)
            return self

        # 11. Catalog usage_count increment
        if "UPDATE nourish_food_catalog SET usage_count" in norm:
            cid = int(params[0])
            if cid in self.catalog:
                self.catalog[cid]["usage_count"] = int(self.catalog[cid].get("usage_count") or 0) + 1
                self.rowcount = 1
            return self

        # 12. Catalog upsert (AI enrichment or external API cache)
        if "INSERT INTO nourish_food_catalog" in norm:
            norm_name = params[1]
            existing_cat = next(
                (c for c in self.catalog.values() if c.get("is_public") and c.get("normalized_name") == norm_name),
                None,
            )
            if "ai_enriched" in norm:
                # From enrich_pending_nourish_logs_batch
                payload = {
                    "name": params[0],
                    "normalized_name": params[1],
                    "brand": "",
                    "category": params[2],
                    "source": "ai_enriched",
                    "is_public": True,
                    "household_id": None,
                    "calories_per_100g": float(params[3]),
                    "protein_per_100g": float(params[4]),
                    "carbs_per_100g": float(params[5]),
                    "fat_per_100g": float(params[6]),
                    "fiber_per_100g": float(params[7]),
                    "sugar_per_100g": float(params[8]),
                    "sodium_mg_per_100g": float(params[9]),
                    "serving_label": params[10],
                    "serving_weight_g": float(params[11]),
                    "is_liquid": bool(params[12]),
                    "prep_state": params[13],
                    "ai_verified": True,
                }
            elif "'household'" in norm:
                # From api_nourish_logs and api_nourish_share_meal
                payload = {
                    "name": params[0],
                    "normalized_name": params[1],
                    "brand": "",
                    "category": str(params[2]),
                    "source": "household",
                    "is_public": False,
                    "created_by_user_id": int(params[3]),
                    "household_id": int(params[4]),
                    "calories_per_100g": float(params[5]),
                    "protein_per_100g": float(params[6]),
                    "carbs_per_100g": float(params[7]),
                    "fat_per_100g": float(params[8]),
                    "fiber_per_100g": float(params[9]),
                    "sugar_per_100g": float(params[10]),
                    "sodium_mg_per_100g": float(params[11]),
                    "serving_label": params[12],
                    "serving_weight_g": float(params[13]),
                    "is_liquid": False,
                    "prep_state": "as_is",
                    "ai_verified": True,
                }
            else:
                # From search_public_nutrition_apis cache
                payload = {
                    "name": params[0],
                    "normalized_name": params[1],
                    "brand": params[2],
                    "category": params[3],
                    "source": params[4],
                    "is_public": True,
                    "household_id": None,
                    "calories_per_100g": float(params[5]),
                    "protein_per_100g": float(params[6]),
                    "carbs_per_100g": float(params[7]),
                    "fat_per_100g": float(params[8]),
                    "fiber_per_100g": float(params[9]),
                    "sugar_per_100g": float(params[10]),
                    "sodium_mg_per_100g": float(params[11]),
                    "serving_label": params[12],
                    "serving_weight_g": float(params[13]),
                    "is_liquid": False,
                    "prep_state": "as_is",
                    "ai_verified": True,
                }
            if existing_cat:
                existing_cat.update(payload)
                row = existing_cat
            else:
                row = self.insert_catalog(payload)
            self._result_rows = [dict(row)]
            self.rowcount = 1
            return self

        # 13. Recipe lookup by id
        if "SELECT * FROM nourish_recipes WHERE id = ?" in norm:
            rid, hhid = int(params[0]), int(params[1])
            row = self.recipes.get(rid)
            if row and (row.get("is_public") or row.get("household_id") == hhid):
                self._result_rows = [dict(row)]
                self.rowcount = 1
            return self

        # 14. Recipe list/search
        if "SELECT * FROM nourish_recipes WHERE household_id = ? OR is_public = TRUE" in norm:
            hhid = int(params[0])
            matches = [
                dict(r) for r in self.recipes.values()
                if r.get("is_public") or r.get("household_id") == hhid
            ]
            self._result_rows = matches
            self.rowcount = len(matches)
            return self

        if "SELECT * FROM nourish_recipes WHERE (household_id = ? OR is_public = TRUE)" in norm:
            hhid = int(params[0])
            pat = str(params[1]).strip("%").lower()
            matches = [
                dict(r) for r in self.recipes.values()
                if (r.get("is_public") or r.get("household_id") == hhid) and pat in r.get("name", "").lower()
            ]
            self._result_rows = matches
            self.rowcount = len(matches)
            return self

        if "INSERT INTO nourish_recipes" in norm:
            row = self.insert_recipe({
                "household_id": int(params[0]),
                "created_by_user_id": int(params[1]),
                "linked_recipe_id": params[2],
                "name": params[3],
                "servings": float(params[4]),
                "total_cooked_weight_g": float(params[5]),
                "total_volume_ml": float(params[6]),
                "density_g_per_ml": float(params[7]),
                "serving_weight_g": float(params[8]),
                "raw_ingredients_text": params[9],
                "ingredients_json": json.loads(params[10]) if isinstance(params[10], str) else params[10],
                "calories_per_serving": float(params[11]),
                "protein_per_serving": float(params[12]),
                "carbs_per_serving": float(params[13]),
                "fat_per_serving": float(params[14]),
                "fiber_per_serving": float(params[15]),
                "sugar_per_serving": float(params[16]),
                "sodium_mg_per_serving": float(params[17]),
                "calories_per_100g": float(params[18]),
                "protein_per_100g": float(params[19]),
                "carbs_per_100g": float(params[20]),
                "fat_per_100g": float(params[21]),
                "fiber_per_100g": float(params[22]),
                "ai_notes": params[23],
                "is_public": False,
            })
            self._result_rows = [dict(row)]
            self.rowcount = 1
            return self

        # 15. User goals
        if "SELECT * FROM nourish_user_goals WHERE user_id = ?" in norm:
            uid = int(params[0])
            if uid in self.goals:
                self._result_rows = [dict(self.goals[uid])]
                self.rowcount = 1
            return self

        if "INSERT INTO nourish_user_goals" in norm and "coach_token" in norm:
            uid = int(params[0])
            token, is_en, alias = params[1], bool(params[2]), str(params[3] or "")
            row = self.goals.setdefault(uid, {"user_id": uid, "calories_target": 2000, "protein_target_g": 130, "carbs_target_g": 200, "fat_target_g": 65, "fiber_target_g": 30, "water_target_ml": 2500})
            row["coach_token"] = token
            row["coach_link_enabled"] = is_en
            row["coach_display_alias"] = alias
            self.rowcount = 1
            return self

        if "INSERT INTO nourish_user_goals" in norm:
            uid = int(params[0])
            if "coach_token" in norm:
                token, is_en, alias = params[1], bool(params[2]), str(params[3] or "")
                row = self.goals.setdefault(uid, {
                    "user_id": uid,
                    "calories_target": 2000,
                    "calorie_target": 2000,
                    "protein_target_g": 130,
                    "carbs_target_g": 200,
                    "fat_target_g": 65,
                    "fiber_target_g": 30,
                    "water_target_ml": 2500,
                })
                row["coach_token"] = token
                row["coach_link_enabled"] = is_en
                row["coach_display_alias"] = alias
            else:
                row = {
                    "user_id": uid,
                    "calories_target": int(params[1]),
                    "calorie_target": int(params[1]),
                    "protein_target_g": int(params[2]),
                    "carbs_target_g": int(params[3]),
                    "fat_target_g": int(params[4]),
                    "fiber_target_g": int(params[5]),
                    "water_target_ml": int(params[6]),
                    "coach_token": None,
                    "coach_link_enabled": False,
                    "coach_display_alias": "",
                }
                self.goals[uid] = row
            self._result_rows = [dict(row)]
            self.rowcount = 1
            return self

        # 16. Daily biometrics
        if "SELECT * FROM nourish_daily_biometrics WHERE user_id = ? AND log_date = ?::date" in norm:
            uid, d_str = int(params[0]), str(params[1])[:10]
            key = (uid, d_str)
            if key in self.biometrics:
                self._result_rows = [dict(self.biometrics[key])]
                self.rowcount = 1
            return self

        if "INSERT INTO nourish_daily_biometrics" in norm:
            uid, d_str = int(params[0]), str(params[1])[:10]
            key = (uid, d_str)
            bio_id = self.biometrics[key]["id"] if key in self.biometrics else self._next_bio_id
            if key not in self.biometrics:
                self._next_bio_id += 1
            row = {
                "id": bio_id,
                "user_id": uid,
                "log_date": d_str,
                "water_ml": int(params[2]),
                "weight_kg": float(params[3]) if params[3] is not None else None,
                "notes": params[4],
            }
            self.biometrics[key] = row
            self._result_rows = [dict(row)]
            self.rowcount = 1
            return self

        # 17. User nourish_enabled / name
        if "SELECT nourish_enabled FROM auth_users WHERE id = ?" in norm:
            uid = int(params[0])
            user_data = self.users.get(uid, {"nourish_enabled": False})
            self._result_rows = [user_data]
            self.rowcount = 1
            return self

        if "SELECT name FROM auth_users WHERE id = ?" in norm:
            uid = int(params[0])
            user_data = self.users.get(uid, {"name": f"User {uid}"})
            self._result_rows = [{"name": user_data.get("name", f"User {uid}")}]
            self.rowcount = 1
            return self

        if "UPDATE auth_users SET nourish_enabled = ? WHERE id = ?" in norm:
            en = bool(params[0])
            uid = int(params[1])
            self.users.setdefault(uid, {"id": uid, "name": f"User {uid}"})["nourish_enabled"] = en
            self.rowcount = 1
            return self

        # 18. Opt-in meal sharing: UPDATE nourish_food_logs SET is_shared_household = TRUE
        if "UPDATE nourish_food_logs" in norm and "is_shared_household = TRUE" in norm:
            uid, hhid, d_str, slot = int(params[0]), int(params[1]), str(params[2])[:10], str(params[3]).lower()
            updated = []
            for r in self.logs.values():
                if int(r["user_id"]) == uid and int(r["household_id"]) == hhid and str(r["log_date"])[:10] == d_str and str(r.get("meal_slot", "")).lower() == slot:
                    r["is_shared_household"] = True
                    updated.append(dict(r))
            self._result_rows = updated
            self.rowcount = len(updated)
            return self

        # 19. Household shared meals: SELECT l.*, u.name as user_name FROM nourish_food_logs l
        if "FROM nourish_food_logs l" in norm and "is_shared_household = TRUE" in norm:
            hhid, uid, d_str = int(params[0]), int(params[1]), str(params[2])[:10]
            matched = []
            for r in sorted(self.logs.values(), key=lambda x: x["id"]):
                if int(r["household_id"]) == hhid and int(r["user_id"]) != uid and str(r["log_date"])[:10] == d_str and r.get("is_shared_household"):
                    m = dict(r)
                    m["user_name"] = self.users.get(r["user_id"], {}).get("name", f"User {r['user_id']}")
                    matched.append(m)
            self._result_rows = matched
            self.rowcount = len(matched)
            return self

        # 20. Auto-catalog check for household item
        if "SELECT id FROM nourish_food_catalog WHERE household_id = ? AND normalized_name = ?" in norm:
            hhid, norm_name = int(params[0]), str(params[1])
            matched = [dict(r) for r in self.catalog.values() if r.get("household_id") == hhid and r.get("normalized_name") == norm_name]
            self._result_rows = matched
            self.rowcount = len(matched)
            return self

        # 21. nourish_ai_usage check
        if "SELECT request_count FROM nourish_ai_usage" in norm:
            uid = int(params[0])
            d_str = datetime.date.today().isoformat()
            cnt = self.ai_usage.get((uid, d_str), 0)
            if cnt > 0:
                self._result_rows = [{"request_count": cnt}]
                self.rowcount = 1
            return self

        # 22. nourish_ai_usage increment / insert
        if "INSERT INTO nourish_ai_usage" in norm:
            uid = int(params[0])
            d_str = datetime.date.today().isoformat()
            key = (uid, d_str)
            self.ai_usage[key] = self.ai_usage.get(key, 0) + 1
            new_cnt = self.ai_usage[key]
            self._result_rows = [{"request_count": new_cnt}]
            self.rowcount = 1
            return self

        # 23. Food logs BETWEEN dates (Analytics & Coach View)
        if "FROM nourish_food_logs" in norm and "log_date BETWEEN ?::date AND ?::date" in norm:
            if len(params) >= 4:
                uid, hhid, start_d, end_d = int(params[0]), int(params[1]), str(params[2])[:10], str(params[3])[:10]
                matched = [
                    dict(r) for r in sorted(self.logs.values(), key=lambda x: str(x["log_date"]))
                    if r["user_id"] == uid and int(r.get("household_id", 0)) == hhid and start_d <= str(r["log_date"])[:10] <= end_d
                ]
            else:
                uid, start_d, end_d = int(params[0]), str(params[1])[:10], str(params[2])[:10]
                matched = [
                    dict(r) for r in sorted(self.logs.values(), key=lambda x: str(x["log_date"]))
                    if r["user_id"] == uid and start_d <= str(r["log_date"])[:10] <= end_d
                ]
            self._result_rows = matched
            self.rowcount = len(matched)
            return self

        # 24. Biometrics BETWEEN dates (Analytics & Coach View)
        if "FROM nourish_daily_biometrics" in norm and "log_date BETWEEN ?::date AND ?::date" in norm:
            uid, start_d, end_d = int(params[0]), str(params[1])[:10], str(params[2])[:10]
            matched = [
                dict(b) for b in sorted(self.biometrics.values(), key=lambda x: str(x["log_date"]))
                if b["user_id"] == uid and start_d <= str(b["log_date"])[:10] <= end_d
            ]
            self._result_rows = matched
            self.rowcount = len(matched)
            return self

        # 25. Coach goals token lookup
        if "coach_token = ?" in norm and "coach_link_enabled = TRUE" in norm:
            token = params[0]
            for uid, g in self.goals.items():
                if g.get("coach_token") == token and g.get("coach_link_enabled"):
                    u = self.users.get(uid, {"name": f"User {uid}", "household_id": 1})
                    ret = {**g, "user_id": uid, "client_name": u.get("name", "Client"), "household_id": u.get("household_id", 1)}
                    self._result_rows = [ret]
                    self.rowcount = 1
                    return self
            self._result_rows = []
            self.rowcount = 0
            return self

        # 26. Coach goals update / insert
        if "UPDATE nourish_user_goals" in norm and "coach_token = ?" in norm:
            token, is_en, alias, uid = params[0], bool(params[1]), str(params[2] or ""), int(params[3])
            row = self.goals.setdefault(uid, {"user_id": uid, "calories_target": 2000, "protein_target_g": 130, "carbs_target_g": 200, "fat_target_g": 65, "fiber_target_g": 30, "water_target_ml": 2500})
            row["coach_token"] = token
            row["coach_link_enabled"] = is_en
            row["coach_display_alias"] = alias
            self.rowcount = 1
            return self

        if "INSERT INTO nourish_user_goals" in norm and "coach_token" in norm:
            uid = int(params[0])
            token, is_en, alias = params[1], bool(params[2]), str(params[3] or "")
            row = self.goals.setdefault(uid, {"user_id": uid, "calories_target": 2000, "protein_target_g": 130, "carbs_target_g": 200, "fat_target_g": 65, "fiber_target_g": 30, "water_target_ml": 2500})
            row["coach_token"] = token
            row["coach_link_enabled"] = is_en
            row["coach_display_alias"] = alias
            self.rowcount = 1
            return self

        # 27. Coach notes insert
        if "INSERT INTO nourish_coach_notes" in norm:
            nid = self._next_note_id
            self._next_note_id += 1
            row = {
                "id": nid,
                "user_id": int(params[0]),
                "log_date": str(params[1])[:10],
                "author_role": "coach",
                "author_name": str(params[2] or "Coach"),
                "message": str(params[3]),
                "is_read": False,
                "created_at": datetime.datetime.now().isoformat(),
            }
            self.coach_notes[nid] = row
            self._result_rows = [dict(row)]
            self.rowcount = 1
            return self

        # 28. Coach notes select & ack
        if "FROM nourish_coach_notes" in norm:
            if "log_date = ?::date" in norm:
                uid, d_str = int(params[0]), str(params[1])[:10]
                matched = [dict(n) for n in sorted(self.coach_notes.values(), key=lambda x: x["id"]) if n["user_id"] == uid and str(n["log_date"])[:10] == d_str]
                self._result_rows = matched
                self.rowcount = len(matched)
                return self
            if "is_read = FALSE" in norm:
                uid = int(params[0])
                matched = [dict(n) for n in sorted(self.coach_notes.values(), key=lambda x: x["id"], reverse=True) if n["user_id"] == uid and not n.get("is_read")]
                self._result_rows = matched[:1] if matched else []
                self.rowcount = len(self._result_rows)
                return self
            if "WHERE user_id = ?" in norm:
                uid = int(params[0])
                matched = [dict(n) for n in sorted(self.coach_notes.values(), key=lambda x: x["id"], reverse=True) if n["user_id"] == uid]
                self._result_rows = matched
                self.rowcount = len(matched)
                return self

        if "UPDATE nourish_coach_notes SET is_read = TRUE" in norm:
            nid, uid = int(params[0]), int(params[1])
            row = self.coach_notes.get(nid)
            if row and row["user_id"] == uid:
                row["is_read"] = True
                self._result_rows = [{"id": nid}]
                self.rowcount = 1
            return self

        return self

    def fetchall(self):
        return list(self._result_rows)

    def fetchone(self):
        return self._result_rows[0] if self._result_rows else None

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


class TestNourishM2APIAndCron(unittest.TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()
        self.fake_db = InMemoryNourishDB()

    def _context_patches(self, user_id=10, household_id=1, subscription_status="premium", is_premium=True, trial_ends_at=None, is_read_only=False):
        """Context manager mocking auth, household entitlement, and DB."""
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            with self.client.session_transaction() as sess:
                sess["listmate_session"] = {
                    "user_id": user_id,
                    "household_id": household_id,
                    "email": f"user{user_id}@example.com",
                }
            hh_row = {
                "id": household_id,
                "is_premium": is_premium,
                "subscription_status": subscription_status,
                "trial_ends_at": trial_ends_at,
            }
            with contextlib.ExitStack() as stack:
                for p in (
                    patch("shared.auth._reconcile_session", side_effect=lambda s: s),
                    patch("app.get_db", return_value=self.fake_db),
                    patch("app._ensure_schema"),
                    patch("shared.auth.get_user_id", return_value=user_id),
                    patch("shared.auth.get_household_id", return_value=household_id),
                    patch("app.get_household_id", return_value=household_id),
                    patch("shared.auth._one", return_value=hh_row if household_id else None),
                    patch("shared.auth.get_household_status", return_value={"is_read_only": is_read_only}),
                ):
                    stack.enter_context(p)
                yield

        return _ctx()

    def test_1_strict_user_id_privacy_isolation_within_same_household(self):
        """
        User A (id=10, hh=1) and User B (id=11, hh=1) are in the SAME household.
        User A logs food and biometrics; User B calling GET /api/nourish/day sees 0 of User A's
        food logs or weight/water, and User B cannot PUT or DELETE User A's log (404).
        """
        today_str = "2026-10-19"

        # Step 1: User A (id=10, hh=1) logs food and biometrics
        with self._context_patches(user_id=10, household_id=1):
            resp_log = self.client.post(
                "/api/nourish/logs",
                json={
                    "log_date": today_str,
                    "meal_slot": "Lunch",
                    "food_name": "Chicken Breast (Cooked)",
                    "quantity": 200,
                    "unit": "g",
                },
            )
            self.assertEqual(resp_log.status_code, 200)
            data_log = resp_log.get_json()
            self.assertTrue(data_log["ok"])
            user_a_log_id = data_log["log"]["id"]
            self.assertEqual(data_log["log"]["user_id"], 10)
            self.assertAlmostEqual(data_log["log"]["calories"], 330.0)

            resp_bio = self.client.post(
                "/api/nourish/biometrics",
                json={
                    "log_date": today_str,
                    "water_ml": 1750,
                    "weight_kg": 72.4,
                },
            )
            self.assertEqual(resp_bio.status_code, 200)
            self.assertEqual(resp_bio.get_json()["biometrics"]["water_ml"], 1750)
            self.assertAlmostEqual(resp_bio.get_json()["biometrics"]["weight_kg"], 72.4)

            # Verify User A sees their own data on GET /api/nourish/day
            resp_day_a = self.client.get(f"/api/nourish/day?date={today_str}")
            self.assertEqual(resp_day_a.status_code, 200)
            day_a = resp_day_a.get_json()
            self.assertEqual(len(day_a["logs"]), 1)
            self.assertAlmostEqual(day_a["totals"]["calories"], 330.0)
            self.assertEqual(day_a["biometrics"]["water_ml"], 1750)
            self.assertAlmostEqual(day_a["biometrics"]["weight_kg"], 72.4)

        # Step 2: User B (id=11, hh=1 — SAME household!) queries GET /api/nourish/day
        with self._context_patches(user_id=11, household_id=1):
            resp_day_b = self.client.get(f"/api/nourish/day?date={today_str}")
            self.assertEqual(resp_day_b.status_code, 200)
            day_b = resp_day_b.get_json()
            self.assertEqual(day_b["user_id"], 11)
            self.assertEqual(day_b["household_id"], 1)
            # User B sees 0 of User A's logs and 0 of User A's biometrics
            self.assertEqual(len(day_b["logs"]), 0)
            self.assertEqual(day_b["totals"]["calories"], 0.0)
            self.assertEqual(day_b["biometrics"]["water_ml"], 0)
            self.assertIsNone(day_b["biometrics"]["weight_kg"])
            # Shared/public recipes are still visible to User B
            self.assertGreaterEqual(len(day_b["recipes"]), 1)

            # User B cannot PUT User A's food log -> 404
            resp_put_b = self.client.put(
                f"/api/nourish/logs/{user_a_log_id}",
                json={"quantity": 500, "unit": "g"},
            )
            self.assertEqual(resp_put_b.status_code, 404)

            # User B cannot DELETE User A's food log -> 404
            resp_del_b = self.client.delete(f"/api/nourish/logs/{user_a_log_id}")
            self.assertEqual(resp_del_b.status_code, 404)

        # Verify User A's log is still intact at 200g / 330 kcal
        self.assertIn(user_a_log_id, self.fake_db.logs)
        self.assertAlmostEqual(self.fake_db.logs[user_a_log_id]["calories"], 330.0)

    def test_2_household_entitlement_gating_and_read_only_guard(self):
        """
        Free-tier and expired households receive 403 with paywall_required: True;
        trial, premium, active, and lifetime households succeed (200).
        """
        # Free household -> 403 paywall_required: True
        with self._context_patches(
            user_id=10, household_id=1, subscription_status="free", is_premium=False
        ):
            resp = self.client.get("/api/nourish/day")
            self.assertEqual(resp.status_code, 403)
            body = resp.get_json()
            self.assertFalse(body["ok"])
            self.assertTrue(body["paywall_required"])

        # Expired trial household -> 403 paywall_required: True
        past_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)).isoformat()
        with self._context_patches(
            user_id=10, household_id=1, subscription_status="trial", is_premium=False, trial_ends_at=past_date
        ):
            resp = self.client.get("/api/nourish/day")
            self.assertEqual(resp.status_code, 403)
            self.assertTrue(resp.get_json()["paywall_required"])

        # Active trial, premium, active, lifetime -> 200 OK
        future_date = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=10)).isoformat()
        for status, is_prem, t_end in [
            ("trial", False, future_date),
            ("premium", True, None),
            ("active", True, None),
            ("lifetime", True, None),
        ]:
            with self._context_patches(
                user_id=10, household_id=1, subscription_status=status, is_premium=is_prem, trial_ends_at=t_end
            ):
                resp = self.client.get("/api/nourish/day")
                self.assertEqual(resp.status_code, 200, f"Expected 200 for subscription_status={status}")
                self.assertTrue(resp.get_json()["ok"])

        # Falsiness rule: uid=0 or hhid=0 -> 401
        with self._context_patches(user_id=0, household_id=1):
            resp = self.client.get("/api/nourish/day")
            self.assertEqual(resp.status_code, 401)

        # Read-only household guard on POST /api/nourish/logs -> 403 read_only
        with self._context_patches(
            user_id=10, household_id=1, subscription_status="premium", is_premium=True, is_read_only=True
        ):
            resp = self.client.post("/api/nourish/logs", json={"food_name": "Banana", "quantity": 1, "unit": "serving"})
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(resp.get_json().get("code"), "read_only")

    def test_3_four_unit_scaling_on_post_and_put_logs(self):
        """
        Tests 4-unit scaling (`g`, `oz`, `ml`, `serving`) on POST /api/nourish/logs
        and proportional rescaling on PUT /api/nourish/logs/<id>.
        """
        with self._context_patches(user_id=10, household_id=1):
            # 1. Log Chicken Breast (165 kcal/100g, 31g protein/100g, serving_weight_g=150g) in 'serving'
            resp = self.client.post(
                "/api/nourish/logs",
                json={
                    "log_date": "2026-10-19",
                    "meal_slot": "Dinner",
                    "food_name": "Chicken Breast (Cooked)",
                    "quantity": 2,
                    "unit": "serving",
                },
            )
            self.assertEqual(resp.status_code, 200)
            log_item = resp.get_json()["log"]
            log_id = log_item["id"]
            self.assertEqual(log_item["ai_enrich_status"], "complete")
            # 2 servings * 150g = 300g -> 3 * 165 = 495 kcal, 3 * 31 = 93g protein
            self.assertAlmostEqual(log_item["gram_weight"], 300.0)
            self.assertAlmostEqual(log_item["calories"], 495.0)
            self.assertAlmostEqual(log_item["protein_g"], 93.0)

            # 2. PUT to update unit to 'oz' and quantity to 4 oz (4 * 28.3495 = 113.4g)
            resp_oz = self.client.put(
                f"/api/nourish/logs/{log_id}",
                json={"quantity": 4, "unit": "oz"},
            )
            self.assertEqual(resp_oz.status_code, 200)
            oz_log = resp_oz.get_json()["log"]
            expected_gw = round(4 * 28.3495, 2)
            self.assertAlmostEqual(oz_log["gram_weight"], expected_gw, places=1)
            self.assertAlmostEqual(oz_log["calories"], round(165.0 * (4 * 28.3495) / 100.0, 2), places=1)

            # 3. PUT to update unit to 'g' and quantity to 100g
            resp_g = self.client.put(
                f"/api/nourish/logs/{log_id}",
                json={"quantity": 100, "unit": "g"},
            )
            self.assertEqual(resp_g.status_code, 200)
            g_log = resp_g.get_json()["log"]
            self.assertAlmostEqual(g_log["gram_weight"], 100.0)
            self.assertAlmostEqual(g_log["calories"], 165.0)
            self.assertAlmostEqual(g_log["protein_g"], 31.0)

            # 4. Log a recipe (General Koottu: 110 kcal/100g, density=1.05, serving_weight_g=200g) in 'ml'
            resp_rec = self.client.post(
                "/api/nourish/logs",
                json={
                    "log_date": "2026-10-19",
                    "meal_slot": "Lunch",
                    "food_name": "General Koottu",
                    "nourish_recipe_id": 1,
                    "quantity": 200,
                    "unit": "ml",
                },
            )
            self.assertEqual(resp_rec.status_code, 200)
            rec_log = resp_rec.get_json()["log"]
            # 200 ml * 1.05 g/ml = 210g -> 2.1 * 110 = 231 kcal
            self.assertAlmostEqual(rec_log["gram_weight"], 210.0)
            self.assertAlmostEqual(rec_log["calories"], 231.0)

    def test_4_pending_ai_enrichment_and_hourly_cron_sweep(self):
        """
        Unknown food logged at 0 kcal gets ai_enrich_status = 'pending'.
        Running enrich_pending_nourish_logs_batch (and cron_hourly.run_hourly_jobs)
        enriches the log entry, flips ai_enrich_status = 'complete', and caches the item
        into nourish_food_catalog (is_public = TRUE).
        """
        with self._context_patches(user_id=10, household_id=1):
            # 1. Log an unknown food with 0 calories
            resp = self.client.post(
                "/api/nourish/logs",
                json={
                    "log_date": "2026-10-19",
                    "meal_slot": "Breakfast",
                    "food_name": "Homemade Ragi Mudde",
                    "quantity": 2,
                    "unit": "serving",
                },
            )
            self.assertEqual(resp.status_code, 200)
            pending_log = resp.get_json()["log"]
            log_id = pending_log["id"]
            self.assertEqual(pending_log["ai_enrich_status"], "pending")
            self.assertEqual(pending_log["calories"], 0.0)

            # 2. Verify dry_run=True reports candidates without mutating
            dry_res = nourish_ai.enrich_pending_nourish_logs_batch(db=self.fake_db, dry_run=True)
            self.assertEqual(dry_res["candidates"], 1)
            self.assertEqual(dry_res["enriched"], 0)
            self.assertEqual(self.fake_db.logs[log_id]["ai_enrich_status"], "pending")

            # 3. Run cron_hourly.run_hourly_jobs with mocked Gemini response
            fake_gemini_response = [
                {
                    "normalized_name": "homemade ragi mudde",
                    "calories_per_100g": 128.0,
                    "protein_per_100g": 3.4,
                    "carbs_per_100g": 27.0,
                    "fat_per_100g": 0.6,
                    "fiber_per_100g": 3.8,
                    "sugar_per_100g": 0.3,
                    "sodium_mg_per_100g": 45.0,
                    "serving_weight_g": 150.0,
                    "serving_label": "1 ball (150g)",
                    "category": "Grains & Starches",
                }
            ]
            with patch("nourish_ai._call_gemini_json", return_value=fake_gemini_response), \
                 patch("scripts.cron_hourly.check_trial_expiration_pushes", return_value={"ok": True}), \
                 patch("scripts.cron_hourly.check_still_good_fridge_lunch_pushes", return_value={"ok": True}), \
                 patch("scripts.cron_hourly.check_still_good_produce_expiry_pushes", return_value={"ok": True}), \
                 patch("scripts.cron_hourly.check_still_good_freezer_expiry_pushes", return_value={"ok": True}), \
                 patch("scripts.cron_hourly.check_store_plan_push_reminders", return_value={"ok": True}), \
                 patch("scripts.cron_hourly.check_post_shopping_smart_stash_pushes", return_value={"ok": True}):
                summary = cron_hourly.run_hourly_jobs(db=self.fake_db, dry_run=False)

            self.assertIn("nourish_ai_enrichment", summary)
            enrich_summary = summary["nourish_ai_enrichment"]
            self.assertEqual(enrich_summary["candidates"], 1)
            self.assertEqual(enrich_summary["enriched"], 1)
            self.assertEqual(enrich_summary["cataloged"], 1)

            # 4. Verify the log entry is now 'complete' with scaled macros (2 servings * 150g = 300g -> 3 * 128 = 384 kcal)
            enriched_log = self.fake_db.logs[log_id]
            self.assertEqual(enriched_log["ai_enrich_status"], "complete")
            self.assertAlmostEqual(enriched_log["gram_weight"], 300.0)
            self.assertAlmostEqual(enriched_log["calories"], 384.0)
            self.assertAlmostEqual(enriched_log["protein_g"], 10.2)
            self.assertIsNotNone(enriched_log["catalog_id"])

            # 5. Verify the food was cached in nourish_food_catalog with is_public = TRUE
            cached_cat = self.fake_db.catalog[enriched_log["catalog_id"]]
            self.assertTrue(cached_cat["is_public"])
            self.assertEqual(cached_cat["normalized_name"], "homemade ragi mudde")
            self.assertEqual(cached_cat["source"], "ai_enriched")
            self.assertAlmostEqual(cached_cat["calories_per_100g"], 128.0)

            # 6. Verify subsequent log of "Homemade Ragi Mudde" resolves immediately from catalog!
            resp_second = self.client.post(
                "/api/nourish/logs",
                json={
                    "log_date": "2026-10-19",
                    "meal_slot": "Dinner",
                    "food_name": "Homemade Ragi Mudde",
                    "quantity": 100,
                    "unit": "g",
                },
            )
            self.assertEqual(resp_second.status_code, 200)
            second_log = resp_second.get_json()["log"]
            self.assertEqual(second_log["ai_enrich_status"], "complete")
            self.assertAlmostEqual(second_log["calories"], 128.0)

    def test_5_catalog_search_meal_deconstructor_and_recipe_analyzer(self):
        """
        Tests GET /api/nourish/catalog/search, POST /api/nourish/analyze-meal,
        and POST /api/nourish/recipes/analyze (including cooked vs raw rule).
        """
        with self._context_patches(user_id=10, household_id=1):
            # 1. Catalog search
            resp_search = self.client.get("/api/nourish/catalog/search?q=banana")
            self.assertEqual(resp_search.status_code, 200)
            s_data = resp_search.get_json()
            self.assertTrue(s_data["ok"])
            self.assertEqual(len(s_data["foods"]), 1)
            self.assertEqual(s_data["foods"][0]["normalized_name"], "banana")

            # 2. Meal deconstructor (heuristic fallback when no Gemini key)
            with patch("nourish_ai._call_gemini_json", return_value=None):
                resp_meal = self.client.post(
                    "/api/nourish/analyze-meal",
                    json={"text": "200g cooked white rice and 150g chicken breast"},
                )
                self.assertEqual(resp_meal.status_code, 200)
                m_data = resp_meal.get_json()
                self.assertTrue(m_data["ok"])
                self.assertEqual(len(m_data["items"]), 2)
                self.assertGreater(m_data["totals"]["calories"], 400.0)
                # Cooked rice should be ~130-135 kcal/100g, NOT raw 360 kcal/100g
                rice_item = m_data["items"][0]
                self.assertLess(rice_item["calories_per_100g"], 180.0)

            # 3. 5-baseline Recipe Analyzer with save=True
            with patch("nourish_ai._call_gemini_json", return_value=None):
                resp_rec = self.client.post(
                    "/api/nourish/recipes/analyze",
                    json={
                        "name": "High Protein Dal Bowl",
                        "servings": 2,
                        "raw_ingredients_text": "200g cooked dal\n150g cooked white rice",
                        "save": True,
                    },
                )
                self.assertEqual(resp_rec.status_code, 200)
                r_data = resp_rec.get_json()
                self.assertTrue(r_data["ok"])
                rec = r_data["recipe"]
                self.assertEqual(rec["name"], "High Protein Dal Bowl")
                self.assertEqual(rec["servings"], 2.0)
                self.assertGreater(rec["total_cooked_weight_g"], 0)
                self.assertGreater(rec["calories_per_serving"], 0)
                self.assertGreater(rec["calories_per_100g"], 0)
                self.assertIn("id", rec)

    def test_10_goals_endpoint_crud_and_aliasing(self):
        """Tests GET /api/nourish/goals defaults, POST /api/nourish/goals upsert, and day endpoint integration."""
        with self._context_patches(user_id=42, household_id=1):
            # 1. Default goals
            get_res = self.client.get("/api/nourish/goals")
            self.assertEqual(get_res.status_code, 200)
            g_data = get_res.get_json()
            self.assertTrue(g_data["ok"])
            self.assertEqual(g_data["goals"]["calories_target"], 2000)

            # 2. Update goals
            post_res = self.client.post(
                "/api/nourish/goals",
                json={
                    "calories_target": 2350,
                    "protein_target_g": 160,
                    "carbs_target_g": 240,
                    "fat_target_g": 70,
                    "fiber_target_g": 35,
                    "water_target_ml": 3000,
                },
            )
            self.assertEqual(post_res.status_code, 200)
            up_data = post_res.get_json()
            self.assertTrue(up_data["ok"])
            self.assertEqual(up_data["goals"]["calories_target"], 2350)
            self.assertEqual(up_data["goals"]["protein_target_g"], 160)
            self.assertEqual(up_data["goals"]["water_target_ml"], 3000)

            # 3. Reflected in /api/nourish/day
            day_res = self.client.get("/api/nourish/day?date=2026-10-19")
            self.assertEqual(day_res.status_code, 200)
            d_data = day_res.get_json()
            self.assertEqual(d_data["goals"]["calories_target"], 2350)
            self.assertEqual(d_data["goals"]["protein_target_g"], 160)

    def test_11_user_nourish_enabled_and_household_sharing(self):
        """Tests per-user nourish enable/disable toggle, opt-in meal sharing, auto-cataloging, and shared-meals drawer endpoint."""
        # 1. Default nourish_enabled is False
        with self._context_patches(user_id=10, household_id=1):
            res = self.client.get("/api/user/nourish-enabled")
            self.assertEqual(res.status_code, 200)
            self.assertFalse(res.get_json()["enabled"])

            # 2. Toggle nourish_enabled to True for User 10
            post_res = self.client.post("/api/user/nourish-enabled", json={"enabled": True})
            self.assertEqual(post_res.status_code, 200)
            self.assertTrue(post_res.get_json()["enabled"])

            # Verify GET now returns True
            res2 = self.client.get("/api/user/nourish-enabled")
            self.assertTrue(res2.get_json()["enabled"])

            # 3. User 10 logs a shared meal (Dinner: 3 Dosa + Paneer Burji)
            log_res = self.client.post(
                "/api/nourish/logs",
                json={
                    "log_date": "2026-10-19",
                    "meal_slot": "Dinner",
                    "is_shared_household": True,
                    "items": [
                        {
                            "name": "Dosa",
                            "serving_amount": 3,
                            "serving_unit": "serving",
                            "calories": 360,
                            "protein_g": 9,
                            "carbs_g": 66,
                            "fat_g": 6,
                            "fiber_g": 3,
                            "serving_weight_g": 100,
                        },
                        {
                            "name": "Paneer Burji",
                            "serving_amount": 1,
                            "serving_unit": "serving",
                            "calories": 280,
                            "protein_g": 18,
                            "carbs_g": 8,
                            "fat_g": 20,
                            "fiber_g": 2,
                            "serving_weight_g": 150,
                        },
                    ],
                },
            )
            self.assertEqual(log_res.status_code, 200)
            self.assertTrue(log_res.get_json()["ok"])

        # 4. User 11 (in same household 1) has Nourish DISABLED -> shared meals endpoint returns empty
        with self._context_patches(user_id=11, household_id=1):
            shared_res_dis = self.client.get("/api/nourish/household/shared-meals?date=2026-10-19")
            self.assertEqual(shared_res_dis.status_code, 200)
            # Must return empty list so bottom drawer NEVER shows for users who disabled Nourish
            self.assertEqual(shared_res_dis.get_json()["shared_meals"], [])

            # 5. User 11 ENABLES Nourish
            self.client.post("/api/user/nourish-enabled", json={"enabled": True})

            # Now User 11 sees the shared meal from User 10
            shared_res_en = self.client.get("/api/nourish/household/shared-meals?date=2026-10-19")
            self.assertEqual(shared_res_en.status_code, 200)
            meals = shared_res_en.get_json()["shared_meals"]
            self.assertEqual(len(meals), 1)
            self.assertEqual(meals[0]["meal_slot"], "Dinner")
            self.assertEqual(meals[0]["shared_by_user_id"], 10)
            self.assertEqual(len(meals[0]["items"]), 2)
            names = [it["food_name"] for it in meals[0]["items"]]
            self.assertIn("Dosa", names)
            self.assertIn("Paneer Burji", names)

        # 6. User 10 tests bulk slot share via /api/nourish/meals/share
        with self._context_patches(user_id=10, household_id=1):
            # Log private Breakfast
            self.client.post(
                "/api/nourish/logs",
                json={
                    "log_date": "2026-10-19",
                    "meal_slot": "Breakfast",
                    "is_shared_household": False,
                    "items": [
                        {
                            "name": "Oatmeal with Almond Milk",
                            "serving_amount": 1,
                            "serving_unit": "serving",
                            "calories": 210,
                            "protein_g": 6,
                            "carbs_g": 36,
                            "fat_g": 4,
                            "fiber_g": 5,
                            "serving_weight_g": 200,
                        }
                    ],
                },
            )
            # Share Breakfast slot
            share_res = self.client.post(
                "/api/nourish/meals/share",
                json={
                    "date": "2026-10-19",
                    "meal_slot": "Breakfast",
                },
            )
            self.assertEqual(share_res.status_code, 200)
            s_data = share_res.get_json()
            self.assertTrue(s_data["ok"])
            self.assertEqual(s_data["shared_count"], 1)

        # 7. Verify an unshared new item (is_shared_household=False) is STILL added to household catalog
        with self._context_patches(user_id=10, household_id=1):
            unshared_log = self.client.post(
                "/api/nourish/logs",
                json={
                    "log_date": "2026-10-19",
                    "meal_slot": "Snack",
                    "is_shared_household": False,
                    "items": [
                        {
                            "name": "Homemade Mango Lassi",
                            "serving_amount": 1,
                            "serving_unit": "serving",
                            "calories": 180,
                            "protein_g": 5,
                            "carbs_g": 28,
                            "fat_g": 3,
                            "fiber_g": 1,
                            "serving_weight_g": 250,
                        }
                    ],
                },
            )
            self.assertEqual(unshared_log.status_code, 200)

        # User 11 searches catalog for Mango Lassi -> finds it!
        with self._context_patches(user_id=11, household_id=1):
            search_res = self.client.get("/api/nourish/catalog/search?q=Mango+Lassi")
            self.assertEqual(search_res.status_code, 200)
            foods = search_res.get_json()["foods"]
            self.assertTrue(any(f["name"] == "Homemade Mango Lassi" and f.get("household_id") == 1 for f in foods))

            # But Snack is NOT in shared meals drawer
            shared_res_snack = self.client.get("/api/nourish/household/shared-meals?date=2026-10-19")
            shared_slots = [m["meal_slot"] for m in shared_res_snack.get_json()["shared_meals"]]
            self.assertNotIn("Snack", shared_slots)

    def test_12_ai_batch_enrichment_does_not_catalog_unmatched_zero_calories(self):
        """Issue #679: When AI returns None and heuristic is unmatched/0 cal, do NOT catalog as verified and keep pending."""
        with self._context_patches(user_id=10, household_id=1):
            # 1. Log an unmatchable unknown food
            res = self.client.post(
                "/api/nourish/logs",
                json={
                    "log_date": "2026-10-19",
                    "meal_slot": "Dinner",
                    "food_name": "Totally Mysterious Food Item XYZ 999",
                    "quantity": 100,
                    "unit": "g",
                },
            )
            self.assertEqual(res.status_code, 200)
            pending_log = res.get_json()["log"]
            log_id = pending_log["id"]
            self.assertEqual(pending_log["ai_enrich_status"], "pending")

            initial_cat_count = len(self.fake_db.catalog)

            # 2. Run enrich_pending_nourish_logs_batch with Gemini returning None (simulating failure/timeout)
            with patch("nourish_ai._call_gemini_json", return_value=None):
                stats = nourish_ai.enrich_pending_nourish_logs_batch(db=self.fake_db, dry_run=False)

            # Enriched and cataloged MUST be 0!
            self.assertEqual(stats["enriched"], 0)
            self.assertEqual(stats["cataloged"], 0)

            # Log row must REMAIN 'pending' with 0 calories
            self.assertEqual(self.fake_db.logs[log_id]["ai_enrich_status"], "pending")
            self.assertEqual(self.fake_db.logs[log_id]["calories"], 0.0)

            # Food catalog must NOT have been poisoned with an unverified 0-calorie item!
            self.assertEqual(len(self.fake_db.catalog), initial_cat_count)
            self.assertFalse(any("mysterious food item" in c.get("normalized_name", "") for c in self.fake_db.catalog.values()))

    def test_13_share_endpoints_safe_date_parsing(self):
        """Issue #680: Invalid dates to /api/nourish/meals/share and /api/nourish/household/shared-meals return HTTP 400."""
        with self._context_patches(user_id=10, household_id=1):
            # 1. Invalid date in POST /api/nourish/meals/share -> 400
            res1 = self.client.post(
                "/api/nourish/meals/share",
                json={"date": "invalid-date-format", "meal_slot": "Dinner"},
            )
            self.assertEqual(res1.status_code, 400)
            self.assertFalse(res1.get_json()["ok"])
            self.assertIn("Invalid date format", res1.get_json()["error"])

            # 2. Invalid date in GET /api/nourish/household/shared-meals -> 400
            self.fake_db.users.setdefault(10, {})["nourish_enabled"] = True
            res2 = self.client.get("/api/nourish/household/shared-meals?date=2026-99-99")
            self.assertEqual(res2.status_code, 400)
            self.assertFalse(res2.get_json()["ok"])
            self.assertIn("Invalid date format", res2.get_json()["error"])

    def test_14_user_goals_respects_explicit_zero_macro_targets(self):
        """Issue #681: Explicit 0g macro targets (keto/carnivore) are preserved and not overridden with defaults."""
        with self._context_patches(user_id=10, household_id=1):
            res = self.client.post(
                "/api/nourish/goals",
                json={
                    "calories_target": 1800,
                    "protein_target_g": 140,
                    "carbs_target_g": 0,
                    "fat_target_g": 80,
                    "fiber_target_g": 0,
                },
            )
            self.assertEqual(res.status_code, 200)
            goals = res.get_json()["goals"]
            self.assertEqual(goals["calories_target"], 1800)
            self.assertEqual(goals["protein_target_g"], 140)
            self.assertEqual(goals["carbs_target_g"], 0)
            self.assertEqual(goals["fat_target_g"], 80)
            self.assertEqual(goals["fiber_target_g"], 0)

    def test_15_canonical_boolean_parser_and_user_nourish_enabled_alias(self):
        """Issue #681: Boolean parsing handles string 'false'/'0', and /api/nourish/user/nourish-enabled alias works."""
        with self._context_patches(user_id=10, household_id=1):
            # Test /api/nourish/user/nourish-enabled route alias with string "true"
            res = self.client.post("/api/nourish/user/nourish-enabled", json={"enabled": "true"})
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.get_json()["enabled"])

            # Test toggling off with string "false" -> must evaluate to False (not True!)
            res2 = self.client.post("/api/nourish/user/nourish-enabled", json={"enabled": "false"})
            self.assertEqual(res2.status_code, 200)
            self.assertFalse(res2.get_json()["enabled"])

            # Test toggling with integer 0 -> False
            res3 = self.client.post("/api/nourish/user/nourish-enabled", json={"enabled": 0})
            self.assertEqual(res3.status_code, 200)
            self.assertFalse(res3.get_json()["enabled"])

    def test_16_modify_food_log_scoping_by_household_id(self):
        """Issue #681: Cannot PUT or DELETE a log belonging to another household even if user_id matches."""
        # Seed a log in household 1 for user 10
        self.fake_db.logs[999] = {
            "id": 999,
            "user_id": 10,
            "household_id": 1,
            "log_date": "2026-10-19",
            "meal_slot": "Dinner",
            "food_name": "Test Item",
            "quantity": 100,
            "unit": "g",
            "gram_weight": 100,
            "calories": 150,
            "protein_g": 10,
            "carbs_g": 15,
            "fat_g": 5,
            "fiber_g": 2,
            "sugar_g": 1,
            "sodium_mg": 50,
            "ai_enrich_status": "complete",
            "notes": "",
        }

        # User 10 in household 2 tries to PUT log 999 -> 404
        with self._context_patches(user_id=10, household_id=2):
            res_put = self.client.put("/api/nourish/logs/999", json={"quantity": 200})
            self.assertEqual(res_put.status_code, 404)

            res_del = self.client.delete("/api/nourish/logs/999")
            self.assertEqual(res_del.status_code, 404)

        # In correct household 1 -> succeeds
        with self._context_patches(user_id=10, household_id=1):
            res_del_ok = self.client.delete("/api/nourish/logs/999")
            self.assertEqual(res_del_ok.status_code, 200)
            self.assertEqual(res_del_ok.get_json()["deleted_id"], 999)

    def test_17_ai_daily_rate_limiting(self):
        """Issue #685: Daily AI rate limit on POST /api/nourish/analyze-meal."""
        mock_analysis = {
            "text": "1 cup oats",
            "items": [{"food_name": "oats", "calories": 150, "quantity": 1, "unit": "cup"}],
            "total_calories": 150,
            "total_protein_g": 5,
            "total_carbs_g": 27,
            "total_fat_g": 3,
            "total_fiber_g": 4,
            "total_sugar_g": 1,
            "total_sodium_mg": 0,
            "confidence": 0.9,
            "ai_source": "gemini",
        }

        with self._context_patches(user_id=10, household_id=1), \
             patch.dict(os.environ, {"NOURISH_AI_DAILY_LIMIT": "2"}), \
             patch("nourish_ai.analyze_natural_language_meal", return_value=mock_analysis):

            # Request 1: allowed, remaining 1
            res1 = self.client.post("/api/nourish/analyze-meal", json={"text": "1 cup oats"})
            self.assertEqual(res1.status_code, 200)
            self.assertTrue(res1.get_json()["ok"])
            self.assertEqual(res1.get_json()["remaining_today"], 1)

            # Request 2: allowed, remaining 0
            res2 = self.client.post("/api/nourish/analyze-meal", json={"text": "1 cup oats"})
            self.assertEqual(res2.status_code, 200)
            self.assertEqual(res2.get_json()["remaining_today"], 0)

            # Request 3: rate limit reached -> HTTP 429
            res3 = self.client.post("/api/nourish/analyze-meal", json={"text": "1 cup oats"})
            self.assertEqual(res3.status_code, 429)
            body3 = res3.get_json()
            self.assertFalse(body3["ok"])
            self.assertTrue(body3["limit_reached"])
            self.assertEqual(body3["daily_limit"], 2)
            self.assertIn("Daily AI evaluation limit reached", body3["error"])

    def test_18_household_shared_meal_push_and_nourish_filter(self):
        """Issue #687: Shared household meal push notifications with nourish_enabled filter and debounce."""
        # 1. Test shared.auth.get_active_tokens_for_household_nourish
        # Invalid household_id <= 0 returns empty immediately
        self.assertEqual(authmod.get_active_tokens_for_household_nourish(0), [])
        self.assertEqual(authmod.get_active_tokens_for_household_nourish(None), [])

        with patch("shared.auth._run") as mock_run, patch("shared.auth._init_schema"):
            mock_run.return_value = [{"token": "token_user11", "platform": "ios", "device_model": "iPhone", "app_version": "1.0", "user_id": 11}]

            # Without exclude_user_id
            tokens = authmod.get_active_tokens_for_household_nourish(1)
            self.assertEqual(len(tokens), 1)
            self.assertEqual(tokens[0]["token"], "token_user11")
            sql_called = mock_run.call_args[0][0]
            self.assertIn("u.nourish_enabled = TRUE", sql_called)
            self.assertNotIn("ps.user_id != %s", sql_called)

            # With exclude_user_id
            mock_run.reset_mock()
            tokens_ex = authmod.get_active_tokens_for_household_nourish(1, exclude_user_id=10)
            self.assertEqual(len(tokens_ex), 1)
            sql_called_ex = mock_run.call_args[0][0]
            self.assertIn("u.nourish_enabled = TRUE", sql_called_ex)
            self.assertIn("ps.user_id != %s", sql_called_ex)
            self.assertEqual(mock_run.call_args[0][1], (1, 10))

        # 2. Test push_helper.send_push_to_household_nourish
        self.assertEqual(
            push_helper.send_push_to_household_nourish(0, "Title", "Body"),
            {"sent": 0, "failed": 0, "error": "Invalid household_id"}
        )

        with patch("shared.auth.get_active_tokens_for_household_nourish", return_value=[]), \
             patch("shared.auth.log_push_dispatch"):
            res_no_tok = push_helper.send_push_to_household_nourish(1, "Title", "Body")
            self.assertEqual(res_no_tok.get("sent"), 0)
            self.assertIn("No active nourish tokens", res_no_tok.get("message", ""))

        with patch("shared.auth.get_active_tokens_for_household_nourish", return_value=[{"token": "fcm_tok_1"}]), \
             patch("push_helper._send_fcm_multicast", return_value={"sent": 1, "failed": 0}) as mock_multicast:
            res_sent = push_helper.send_push_to_household_nourish(
                household_id=1,
                title="Title",
                body="Body",
                data={"action": "open_nourish"},
                exclude_user_id=10
            )
            self.assertEqual(res_sent.get("sent"), 1)
            mock_multicast.assert_called_once_with(
                ["fcm_tok_1"], "Title", "Body", {"action": "open_nourish"}, target_type="household", target_id=1
            )

        # 3. Test POST /api/nourish/meals/share push dispatch and debounce
        app_module._last_nourish_shared_push.clear()
        self.fake_db.users[10] = {"id": 10, "name": "Alice", "nourish_enabled": True}

        with self._context_patches(user_id=10, household_id=1):
            # Seed 2 logs for Lunch on 2026-10-19
            self.client.post(
                "/api/nourish/logs",
                json={
                    "log_date": "2026-10-19",
                    "meal_slot": "Lunch",
                    "items": [
                        {"food_name": "Chicken Salad", "quantity": 1, "unit": "serving", "calories": 350, "gram_weight": 250},
                        {"food_name": "Iced Tea", "quantity": 1, "unit": "serving", "calories": 50, "gram_weight": 240},
                    ],
                },
            )

            with patch("push_helper.send_push_to_household_nourish") as mock_push:
                # First share: should trigger push notification
                res_share1 = self.client.post(
                    "/api/nourish/meals/share",
                    json={"date": "2026-10-19", "meal_slot": "Lunch"},
                )
                self.assertEqual(res_share1.status_code, 200)
                self.assertTrue(res_share1.get_json()["ok"])
                self.assertEqual(mock_push.call_count, 1)

                call_kwargs = mock_push.call_args[1]
                self.assertEqual(call_kwargs["household_id"], 1)
                self.assertEqual(call_kwargs["title"], "🍽️ Lunch logged by Alice")
                self.assertIn("Chicken Salad & Iced Tea. Did you eat this too? Tap to log in 1 tap.", call_kwargs["body"])
                self.assertEqual(call_kwargs["data"], {
                    "action": "open_nourish",
                    "screen": "nourish",
                    "date": "2026-10-19",
                    "slot": "Lunch",
                })
                self.assertEqual(call_kwargs["exclude_user_id"], 10)

                # Second share immediately after: should be debounced (no second push)
                res_share2 = self.client.post(
                    "/api/nourish/meals/share",
                    json={"date": "2026-10-19", "meal_slot": "Lunch"},
                )
                self.assertEqual(res_share2.status_code, 200)
                self.assertEqual(mock_push.call_count, 1)

                # Advance past 10 minutes (600 seconds) in the debounce cache
                cache_key = (1, "2026-10-19", "lunch")
                app_module._last_nourish_shared_push[cache_key] = 0.0

                # Third share after debounce window: should trigger push again
                res_share3 = self.client.post(
                    "/api/nourish/meals/share",
                    json={"date": "2026-10-19", "meal_slot": "Lunch"},
                )
                self.assertEqual(res_share3.status_code, 200)
                self.assertEqual(mock_push.call_count, 2)

    def test_19_still_good_item_id_bridge(self):
        """Issue #688: still_good_item_id bridge into nourish_food_logs."""
        with self._context_patches(user_id=10, household_id=1):
            # 1. Entry-level still_good_item_id
            res1 = self.client.post(
                "/api/nourish/logs",
                json={
                    "log_date": "2026-10-19",
                    "meal_slot": "Dinner",
                    "items": [
                        {
                            "food_name": "Leftover Roast Chicken",
                            "quantity": 1,
                            "unit": "serving",
                            "calories": 250,
                            "gram_weight": 180,
                            "still_good_item_id": 42,
                        }
                    ],
                },
            )
            self.assertEqual(res1.status_code, 200)
            data1 = res1.get_json()
            self.assertTrue(data1["ok"])
            self.assertEqual(len(data1["logs"]), 1)
            self.assertEqual(data1["logs"][0]["still_good_item_id"], 42)

            log_id1 = data1["logs"][0]["id"]
            db_row1 = self.fake_db.logs.get(log_id1)
            self.assertIsNotNone(db_row1)
            self.assertEqual(db_row1.get("still_good_item_id"), 42)

            # 2. Request payload top-level still_good_item_id fallback
            res2 = self.client.post(
                "/api/nourish/logs",
                json={
                    "log_date": "2026-10-19",
                    "meal_slot": "Dinner",
                    "still_good_item_id": 88,
                    "items": [
                        {
                            "food_name": "Leftover Rice",
                            "quantity": 1,
                            "unit": "serving",
                            "calories": 200,
                            "gram_weight": 150,
                        }
                    ],
                },
            )
            self.assertEqual(res2.status_code, 200)
            data2 = res2.get_json()
            self.assertTrue(data2["ok"])
            self.assertEqual(data2["logs"][0]["still_good_item_id"], 88)

            log_id2 = data2["logs"][0]["id"]
            db_row2 = self.fake_db.logs.get(log_id2)
            self.assertIsNotNone(db_row2)
            self.assertEqual(db_row2.get("still_good_item_id"), 88)

            # 3. Invalid / 0 still_good_item_id resolves to None
            res3 = self.client.post(
                "/api/nourish/logs",
                json={
                    "log_date": "2026-10-19",
                    "meal_slot": "Dinner",
                    "items": [
                        {
                            "food_name": "Fresh Apple",
                            "quantity": 1,
                            "unit": "serving",
                            "calories": 95,
                            "gram_weight": 182,
                            "still_good_item_id": 0,
                        }
                    ],
                },
            )
            self.assertEqual(res3.status_code, 200)
            data3 = res3.get_json()
            self.assertIsNone(data3["logs"][0]["still_good_item_id"])

    def test_20_hydration_water_delta_persistence(self):
        """Issue #690: Test hydration increments via both delta_water_ml and water_delta_ml persist correctly."""
        with self._context_patches(user_id=10, household_id=1):
            # 1. Post +250ml with delta_water_ml (frontend format)
            res1 = self.client.post(
                "/api/nourish/biometrics",
                json={
                    "log_date": "2026-10-19",
                    "delta_water_ml": 250,
                },
            )
            self.assertEqual(res1.status_code, 200)
            data1 = res1.get_json()
            self.assertTrue(data1["ok"])
            self.assertEqual(data1["biometrics"]["water_ml"], 250)

            # 2. Post another +250ml with water_delta_ml
            res2 = self.client.post(
                "/api/nourish/biometrics",
                json={
                    "log_date": "2026-10-19",
                    "water_delta_ml": 250,
                },
            )
            self.assertEqual(res2.status_code, 200)
            data2 = res2.get_json()
            self.assertTrue(data2["ok"])
            self.assertEqual(data2["biometrics"]["water_ml"], 500)

            # 3. Verify GET /api/nourish/day?date=2026-10-19 returns 500ml
            day_res = self.client.get("/api/nourish/day?date=2026-10-19")
            self.assertEqual(day_res.status_code, 200)
            day_data = day_res.get_json()
            self.assertEqual(day_data["biometrics"]["water_ml"], 500)

            # 4. Verify different date returns 0ml and returning to 2026-10-19 returns 500ml
            day_other = self.client.get("/api/nourish/day?date=2026-10-20")
            self.assertEqual(day_other.get_json()["biometrics"]["water_ml"], 0)

            day_again = self.client.get("/api/nourish/day?date=2026-10-19")
            self.assertEqual(day_again.get_json()["biometrics"]["water_ml"], 500)

    def test_20_nourish_macro_trends_and_analytics(self):
        """Issue #692: Macro Trends & Analytics endpoint GET /api/nourish/analytics."""
        with self._context_patches(user_id=10, household_id=1):
            # Seed goals
            self.fake_db.goals[10] = {
                "user_id": 10,
                "calories_target": 2000,
                "protein_target_g": 140,
                "carbs_target_g": 200,
                "fat_target_g": 65,
                "fiber_target_g": 30,
                "water_target_ml": 2500,
            }

            # Seed 2 days of logs and biometrics
            today = datetime.date.today().isoformat()
            yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

            self.client.post("/api/nourish/logs", json={
                "log_date": today,
                "meal_slot": "Breakfast",
                "items": [{"food_name": "Eggs & Toast", "calories": 400, "protein_g": 25, "carbs_g": 30, "fat_g": 15, "fiber_g": 4}],
            })
            self.client.post("/api/nourish/logs", json={
                "log_date": yesterday,
                "meal_slot": "Lunch",
                "items": [{"food_name": "Chicken Rice Bowl", "calories": 600, "protein_g": 45, "carbs_g": 60, "fat_g": 12, "fiber_g": 6}],
            })
            self.client.post("/api/nourish/biometrics", json={"log_date": today, "water_ml": 1800, "weight_kg": 75.5})

            # Call analytics for 7 days
            res = self.client.get("/api/nourish/analytics?days=7")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data["ok"])
            self.assertEqual(data["days"], 7)
            self.assertEqual(len(data["daily"]), 7)

            # Daily entries
            today_entry = next((d for d in data["daily"] if d["date"] == today), None)
            self.assertIsNotNone(today_entry)
            self.assertEqual(today_entry["calories"], 400.0)
            self.assertEqual(today_entry["water_ml"], 1800)
            self.assertEqual(today_entry["weight_kg"], 75.5)

            # Averages
            avg = data["averages"]
            self.assertEqual(avg["days_logged"], 2)
            self.assertEqual(avg["calories"], 500.0)  # (400 + 600) / 2
            self.assertEqual(avg["protein_g"], 35.0)  # (25 + 45) / 2

            # Macro split
            split = data["macro_split"]
            self.assertGreater(split["protein_pct"], 0)
            self.assertGreater(split["carbs_pct"], 0)

            # Test invalid / clamped days
            res_clamped = self.client.get("/api/nourish/analytics?days=999")
            self.assertEqual(res_clamped.get_json()["days"], 90)

            res_invalid = self.client.get("/api/nourish/analytics?days=abc")
            self.assertEqual(res_invalid.get_json()["days"], 7)

    def test_21_evening_diary_and_hydration_push_reminders(self):
        """Issue #693: Evening Diary (8pm) & Afternoon Hydration (3pm) push reminders."""
        with patch("push_helper.send_push_to_user", return_value={"sent": 1, "failed": 0}) as mock_send:
            # 1. Evening Diary push: candidate user has NOT logged dinner
            cand_user = [{
                "user_id": 10,
                "user_name": "Test User",
                "user_email": "test@example.com",
                "user_timezone": "America/New_York",
                "household_id": 1,
                "household_name": "Test Household",
                "subscription_status": "premium",
                "is_premium": True,
            }]

            with patch("push_helper._run") as mock_run:
                # First call returns candidate list, second returns food logs summary (count=1, cal_sum=500)
                mock_run.side_effect = [cand_user, [{"count": 1, "cal_sum": 500}]]
                res_diary = push_helper.check_nourish_evening_diary_pushes(target_hour=20, force_send=True)
                self.assertTrue(res_diary["ok"])
                self.assertEqual(res_diary["dispatched"], 1)
                mock_send.assert_called()
                call_args = mock_send.call_args[1]
                self.assertEqual(call_args["title"], "📖 Wrap up today's Nourish diary")
                self.assertEqual(call_args["data"]["campaign"], "nourish_evening_diary_8pm")

            # 2. Afternoon Hydration push: user below water goal
            mock_send.reset_mock()
            with patch("push_helper._run") as mock_run:
                # First returns candidates, second returns biometrics + goal (water_ml=1000, water_target_ml=2500)
                mock_run.side_effect = [cand_user, [{"water_ml": 1000, "water_target_ml": 2500}]]
                res_hyd = push_helper.check_nourish_afternoon_hydration_pushes(target_hour=15, force_send=True)
                self.assertTrue(res_hyd["ok"])
                self.assertEqual(res_hyd["dispatched"], 1)
                call_args = mock_send.call_args[1]
                self.assertEqual(call_args["title"], "💧 Afternoon Hydration Check")
                self.assertIn("1000ml of your 2500ml", call_args["body"])
                self.assertEqual(call_args["data"]["campaign"], "nourish_afternoon_hydration_3pm")

            # 3. Afternoon Hydration push: user already reached goal -> skipped
            mock_send.reset_mock()
            with patch("push_helper._run") as mock_run:
                mock_run.side_effect = [cand_user, [{"water_ml": 2500, "water_target_ml": 2500}]]
                res_hyd_skip = push_helper.check_nourish_afternoon_hydration_pushes(target_hour=15, force_send=False)
                self.assertTrue(res_hyd_skip["ok"])
                self.assertEqual(res_hyd_skip["dispatched"], 0)
                mock_send.assert_not_called()

    def test_22_coach_link_portal_and_notes(self):
        """Issue #694: VitalPath Coach Link Portal & Push Alert backend endpoints."""
        with self._context_patches(user_id=10, household_id=1):
            # 1. Generate coach link
            res_link = self.client.post("/api/nourish/coach/link", json={
                "enabled": True,
                "alias": "Athlete Sam",
                "regenerate": True,
            })
            self.assertEqual(res_link.status_code, 200)
            link_data = res_link.get_json()
            self.assertTrue(link_data["ok"])
            token = link_data["coach_token"]
            self.assertTrue(bool(token))
            self.assertEqual(link_data["coach_display_alias"], "Athlete Sam")
            self.assertTrue(link_data["coach_link_enabled"])
            self.assertIn(token, link_data["coach_url"])

            # 2. Coach views client data via token (GET /api/nourish/coach/view/<token>)
            res_view = self.client.get(f"/api/nourish/coach/view/{token}")
            self.assertEqual(res_view.status_code, 200)
            view_data = res_view.get_json()
            self.assertTrue(view_data["ok"])
            self.assertEqual(view_data["client"]["alias"], "Athlete Sam")
            self.assertEqual(len(view_data["days"]), 14)

            # 3. Coach posts feedback note with push alert (POST /api/nourish/coach/notes/<token>)
            with patch("push_helper.send_push_to_user", return_value={"sent": 1, "failed": 0}) as mock_coach_push:
                res_note = self.client.post(f"/api/nourish/coach/notes/{token}", json={
                    "message": "Great protein intake today! Add 500ml water after dinner.",
                    "author_name": "Coach Maria",
                    "log_date": "2026-10-19",
                })
                self.assertEqual(res_note.status_code, 200)
                note_data = res_note.get_json()
                self.assertTrue(note_data["ok"])
                note_id = note_data["note"]["id"]
                self.assertIsNotNone(note_id)

                # Push was dispatched to user
                mock_coach_push.assert_called_once()
                push_args = mock_coach_push.call_args[1]
                self.assertEqual(push_args["user_id"], 10)
                self.assertEqual(push_args["title"], "💬 Coach Note from Coach Maria")
                self.assertEqual(push_args["data"]["source"], "coach_note")

            # 4. Client retrieves daily diary via GET /api/nourish/day and sees coach_notes & unread_coach_note
            res_day = self.client.get("/api/nourish/day?date=2026-10-19")
            self.assertEqual(res_day.status_code, 200)
            day_data = res_day.get_json()
            self.assertEqual(len(day_data["coach_notes"]), 1)
            self.assertEqual(day_data["coach_notes"][0]["author_name"], "Coach Maria")
            self.assertIsNotNone(day_data["unread_coach_note"])
            self.assertEqual(day_data["unread_coach_note"]["id"], note_id)

            # 5. Client acknowledges note (POST /api/nourish/coach/notes/<id>/ack)
            res_ack = self.client.post(f"/api/nourish/coach/notes/{note_id}/ack")
            self.assertEqual(res_ack.status_code, 200)
            self.assertTrue(res_ack.get_json()["ok"])

            # Verify unread_coach_note is now None
            res_day_read = self.client.get("/api/nourish/day?date=2026-10-19")
            self.assertIsNone(res_day_read.get_json()["unread_coach_note"])

            # 6. Verify Web portal route GET /coach/<token> renders mobile-friendly HTML
            res_portal = self.client.get(f"/coach/{token}")
            self.assertEqual(res_portal.status_code, 200)
            self.assertIn("VitalPath Coach Portal", res_portal.get_data(as_text=True))
            self.assertIn(token, res_portal.get_data(as_text=True))

            # 7. Disabling coach link revokes access
            self.client.post("/api/nourish/coach/link", json={"enabled": False})
            res_revoked = self.client.get(f"/api/nourish/coach/view/{token}")
            self.assertEqual(res_revoked.status_code, 404)


if __name__ == "__main__":
    unittest.main()

