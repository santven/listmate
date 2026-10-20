#!/usr/bin/env python3
"""
Nourish AI Nutrition Engine (`nourish_ai.py`)

Provides:
1. Hourly Cron Batch Enrichment (`enrich_pending_nourish_logs_batch`) — modeled after `still_good_ai.py`.
   Processes `nourish_food_logs` where `ai_enrich_status = 'pending'`, enforces the COOKED vs RAW rule,
   scales macros across the 4-unit system (`g`, `oz`, `ml`, `serving`), upserts enriched items into
   `nourish_food_catalog` (`is_public = TRUE`), and marks logs `'complete'`.
2. Deterministic 4-Unit Macro Scaling (`compute_scaled_macros`).
3. Optional Tier-2 Public API Lookup (`search_public_nutrition_apis`).
4. Interactive Natural-Language Meal Deconstructor (`analyze_natural_language_meal`).
5. 5-Baseline Recipe Nutrition Calculator (`analyze_recipe_nutrition`).
"""

import json
import os
import re
import urllib.parse
import urllib.request
from db_pg import get_db, close_db
from seed_nourish import normalize_food_name, CURATED_AND_MIGRATED_FOODS

OZ_TO_G = 28.3495

COOKED_VS_RAW_RULE = (
    "CRITICAL COOKED VS RAW RULE:\n"
    "Always assume any food logged in a meal diary is in its COOKED or PREPARED state "
    "(e.g., cooked rice, cooked lentils/dal, cooked chicken breast, cooked pasta, steamed idli) "
    "unless the user explicitly labels the food as 'raw' or 'dry'. "
    "Never apply raw dry-grain calorie densities (~350-370 kcal/100g) to cooked grains/legumes (~110-140 kcal/100g)."
)


def _discover_gemini_key():
    for var in ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"]:
        k = os.environ.get(var, "").strip()
        if k and not k.startswith("dev-") and not k.startswith("secret-"):
            return k
    for path in ["/opt/shared/.env", ".env", "/app/applet/.env"]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        for var in ["GEMINI_API_KEY=", "GOOGLE_API_KEY=", "GOOGLE_GENAI_API_KEY="]:
                            if line.strip().startswith(var):
                                k = line.split("=", 1)[1].strip().strip("'").strip('"')
                                if k and not k.startswith("dev-") and not k.startswith("secret-"):
                                    return k
            except Exception:
                pass
    return ""


def _get_gemini_models():
    """Returns the Gemini Lite fallback cascade with resilient production fallbacks."""
    raw_models = os.environ.get(
        "GEMINI_MODEL_NAME",
        "gemini-2.5-flash-lite,gemini-2.0-flash,gemini-flash-latest,gemini-1.5-flash",
    )
    models_to_try = []
    for m in raw_models.split(","):
        clean_m = m.strip().strip("'").strip('"')
        if clean_m.startswith("models/"):
            clean_m = clean_m[len("models/"):]
        if clean_m and clean_m not in models_to_try:
            models_to_try.append(clean_m)

    for fallback in [
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-flash-latest",
        "gemini-1.5-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash-lite-preview-02-05",
    ]:
        if fallback not in models_to_try:
            models_to_try.append(fallback)
    return models_to_try


def _call_gemini_json(system_instruction: str, prompt: str, temperature: float = 0.2, timeout: int = 30):
    """Calls Gemini using the Lite model fallback cascade and parses JSON response."""
    key = _discover_gemini_key()
    if not key:
        print("[NOURISH AI] Notice: No GEMINI_API_KEY found in environment or .env files. Skipping AI call.")
        return None

    import time
    models_to_try = _get_gemini_models()
    body = {
        "contents": [
            {
                "parts": [
                    {"text": system_instruction + "\n\n" + prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
        },
    }

    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": key,
                "User-Agent": "listmate-nourish-cron",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                candidates = data.get("candidates", [])
                if candidates:
                    text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                    if text.startswith("```"):
                        lines = text.splitlines()
                        if lines and lines[0].startswith("```"):
                            lines = lines[1:]
                        if lines and lines[-1].startswith("```"):
                            lines = lines[:-1]
                        text = "\n".join(lines).strip()
                    parsed = json.loads(text)
                    print(f"[NOURISH AI] Model {model_name} succeeded.")
                    return parsed
        except Exception as exc:
            print(f"[NOURISH AI ERROR] Call to {model_name} failed: {exc}")
            if "503" in str(exc):
                time.sleep(0.5)
            continue
    return None


def compute_scaled_macros(per_100g_dict, quantity, unit, serving_weight_g=100.0, density_g_per_ml=1.0):
    """
    Deterministic 4-unit scaling math (`g`, `oz`, `ml`, `serving`) ported from VitalPath's `calculateEstimatedMacros`.
    """
    try:
        qty = max(0.0, float(quantity if quantity is not None else 0.0))
    except (ValueError, TypeError):
        qty = 0.0

    raw_unit = str(unit or "g").strip().lower()
    if raw_unit in ("g", "gram", "grams"):
        norm_unit = "g"
    elif raw_unit in ("oz", "ounce", "ounces"):
        norm_unit = "oz"
    elif raw_unit in ("ml", "milliliter", "milliliters"):
        norm_unit = "ml"
    elif raw_unit in ("plate", "plates"):
        norm_unit = "plate"
    elif raw_unit in ("serving", "servings", "piece", "pieces", "cup", "bowl", "slice"):
        norm_unit = "serving"
    else:
        norm_unit = "g"

    try:
        srv_w = float(serving_weight_g if serving_weight_g is not None else 100.0)
        if srv_w <= 0:
            srv_w = 100.0
    except (ValueError, TypeError):
        srv_w = 100.0

    try:
        dens = float(density_g_per_ml if density_g_per_ml is not None else 1.0)
        if dens <= 0:
            dens = 1.0
    except (ValueError, TypeError):
        dens = 1.0

    if norm_unit == "g":
        gram_weight = qty
    elif norm_unit == "oz":
        gram_weight = qty * OZ_TO_G
    elif norm_unit == "ml":
        gram_weight = qty * dens
    elif norm_unit in ("serving", "plate"):
        gram_weight = qty * srv_w
    else:
        gram_weight = qty

    factor = gram_weight / 100.0
    src = per_100g_dict or {}

    def _num(*keys):
        for k in keys:
            val = src.get(k)
            if val is not None:
                try:
                    return max(0.0, float(val))
                except (ValueError, TypeError):
                    pass
        return 0.0

    cal_100 = _num("calories_per_100g", "calories")
    pro_100 = _num("protein_per_100g", "protein_g", "protein")
    carb_100 = _num("carbs_per_100g", "carbs_g", "carbs")
    fat_100 = _num("fat_per_100g", "fat_g", "fat")
    fib_100 = _num("fiber_per_100g", "fiber_g", "fiber")
    sug_100 = _num("sugar_per_100g", "sugar_g", "sugar")
    sod_100 = _num("sodium_mg_per_100g", "sodium_mg", "sodium")

    return {
        "quantity": round(qty, 2),
        "unit": norm_unit,
        "gram_weight": round(gram_weight, 2),
        "calories": round(cal_100 * factor, 2),
        "protein_g": round(pro_100 * factor, 2),
        "carbs_g": round(carb_100 * factor, 2),
        "fat_g": round(fat_100 * factor, 2),
        "fiber_g": round(fib_100 * factor, 2),
        "sugar_g": round(sug_100 * factor, 2),
        "sodium_mg": round(sod_100 * factor, 2),
    }


def _heuristic_food_nutrition(food_name: str) -> dict:
    """
    Conservative, cooked-aware heuristic nutrition estimator per 100g.
    Guarantees that pending logs are always enriched even when offline or without GEMINI_API_KEY.
    """
    norm = normalize_food_name(food_name)
    is_raw_explicit = bool(re.search(r"\b(raw|dry|uncooked)\b", norm))

    # 1. Exact or substring match in curated seed catalog
    for item in CURATED_AND_MIGRATED_FOODS:
        if item.get("normalized_name") == norm:
            return dict(item)
    for item in CURATED_AND_MIGRATED_FOODS:
        c_norm = item.get("normalized_name", "")
        if c_norm and (c_norm in norm or norm in c_norm):
            return dict(item)

    # 2. Keyword-based cooked/prepared heuristics
    if any(k in norm for k in ["chicken", "turkey", "poultry", "tikka"]):
        return {
            "calories_per_100g": 165.0,
            "protein_per_100g": 29.0,
            "carbs_per_100g": 1.5,
            "fat_per_100g": 4.5,
            "fiber_per_100g": 0.0,
            "sugar_per_100g": 0.5,
            "sodium_mg_per_100g": 180.0,
            "serving_weight_g": 140.0,
            "serving_label": "1 serving (140g)",
            "category": "Meat & Poultry",
            "prep_state": "raw" if is_raw_explicit else "cooked",
        }
    if any(k in norm for k in ["salmon", "fish", "tuna", "shrimp", "prawn", "cod"]):
        return {
            "calories_per_100g": 185.0,
            "protein_per_100g": 24.0,
            "carbs_per_100g": 0.5,
            "fat_per_100g": 9.5,
            "fiber_per_100g": 0.0,
            "sugar_per_100g": 0.0,
            "sodium_mg_per_100g": 160.0,
            "serving_weight_g": 140.0,
            "serving_label": "1 fillet (140g)",
            "category": "Seafood",
            "prep_state": "raw" if is_raw_explicit else "cooked",
        }
    if any(k in norm for k in ["rice", "pulao", "biryani", "quinoa", "oats", "oatmeal", "pasta", "noodle", "upma", "poha", "pongal"]):
        if is_raw_explicit:
            return {
                "calories_per_100g": 360.0,
                "protein_per_100g": 8.0,
                "carbs_per_100g": 76.0,
                "fat_per_100g": 2.0,
                "fiber_per_100g": 3.5,
                "sugar_per_100g": 0.8,
                "sodium_mg_per_100g": 5.0,
                "serving_weight_g": 45.0,
                "serving_label": "1 dry serving (45g)",
                "category": "Grains & Starches",
                "prep_state": "raw",
            }
        return {
            "calories_per_100g": 135.0,
            "protein_per_100g": 3.5,
            "carbs_per_100g": 26.5,
            "fat_per_100g": 1.8,
            "fiber_per_100g": 1.6,
            "sugar_per_100g": 0.5,
            "sodium_mg_per_100g": 140.0,
            "serving_weight_g": 160.0,
            "serving_label": "1 cup cooked (160g)",
            "category": "Grains & Starches",
            "prep_state": "cooked",
        }
    if any(k in norm for k in ["dal", "daal", "lentil", "sambar", "kootu", "koottu", "chana", "chickpea", "rajma", "bean", "rasam"]):
        if is_raw_explicit:
            return {
                "calories_per_100g": 345.0,
                "protein_per_100g": 24.0,
                "carbs_per_100g": 58.0,
                "fat_per_100g": 1.8,
                "fiber_per_100g": 11.0,
                "sugar_per_100g": 2.0,
                "sodium_mg_per_100g": 12.0,
                "serving_weight_g": 40.0,
                "serving_label": "1 dry serving (40g)",
                "category": "Legumes & Lentils",
                "prep_state": "raw",
            }
        return {
            "calories_per_100g": 118.0,
            "protein_per_100g": 6.8,
            "carbs_per_100g": 16.5,
            "fat_per_100g": 2.8,
            "fiber_per_100g": 4.8,
            "sugar_per_100g": 1.5,
            "sodium_mg_per_100g": 240.0,
            "serving_weight_g": 180.0,
            "serving_label": "1 bowl (180g)",
            "category": "Legumes & Lentils",
            "prep_state": "cooked",
        }
    if any(k in norm for k in ["idli", "dosa", "uttapam", "roti", "chapati", "naan", "paratha", "bread", "toast"]):
        return {
            "calories_per_100g": 195.0,
            "protein_per_100g": 5.5,
            "carbs_per_100g": 36.0,
            "fat_per_100g": 3.2,
            "fiber_per_100g": 2.8,
            "sugar_per_100g": 1.2,
            "sodium_mg_per_100g": 260.0,
            "serving_weight_g": 80.0,
            "serving_label": "1 serving (80g)",
            "category": "Grains & Bakery",
            "prep_state": "cooked",
        }
    if any(k in norm for k in ["paneer", "tofu", "cheese", "curd", "yogurt", "dahi", "milk", "latte", "cappuccino", "coffee", "chai", "tea"]):
        is_drink = any(k in norm for k in ["milk", "latte", "cappuccino", "coffee", "chai", "tea"])
        return {
            "calories_per_100g": 65.0 if is_drink else 210.0,
            "protein_per_100g": 3.4 if is_drink else 14.0,
            "carbs_per_100g": 6.0 if is_drink else 3.8,
            "fat_per_100g": 3.0 if is_drink else 15.0,
            "fiber_per_100g": 0.0 if is_drink else 0.5,
            "sugar_per_100g": 5.0 if is_drink else 1.5,
            "sodium_mg_per_100g": 45.0 if is_drink else 190.0,
            "serving_weight_g": 240.0 if is_drink else 100.0,
            "serving_label": "1 cup (240ml)" if is_drink else "1 serving (100g)",
            "category": "Dairy & Beverages" if is_drink else "Dairy & Plant Proteins",
            "is_liquid": is_drink,
            "prep_state": "cooked",
        }
    if any(k in norm for k in ["salad", "broccoli", "spinach", "gobi", "cauliflower", "bhindi", "okra", "poriyal", "subzi", "sabzi", "vegetable", "veggie"]):
        return {
            "calories_per_100g": 85.0,
            "protein_per_100g": 2.6,
            "carbs_per_100g": 9.5,
            "fat_per_100g": 4.2,
            "fiber_per_100g": 3.4,
            "sugar_per_100g": 2.8,
            "sodium_mg_per_100g": 195.0,
            "serving_weight_g": 130.0,
            "serving_label": "1 cup (130g)",
            "category": "Vegetables",
            "prep_state": "raw" if is_raw_explicit else "cooked",
        }

    return {
        "calories_per_100g": 0.0,
        "protein_per_100g": 0.0,
        "carbs_per_100g": 0.0,
        "fat_per_100g": 0.0,
        "fiber_per_100g": 0.0,
        "sugar_per_100g": 0.0,
        "sodium_mg_per_100g": 0.0,
        "serving_weight_g": 100.0,
        "serving_label": "1 serving (100g)",
        "category": "Prepared Foods",
        "prep_state": "raw" if is_raw_explicit else "cooked",
        "is_unmatched": True,
    }


def enrich_pending_nourish_logs_batch(db=None, dry_run=False, limit=50):
    """
    Runs hourly via scripts/cron_hourly.py.
    Queries `nourish_food_logs` where `ai_enrich_status = 'pending'`, batches unique foods
    into a single Gemini JSON request (with heuristic fallback if GEMINI_API_KEY is missing
    or all models fail), upserts into `nourish_food_catalog` (`is_public = TRUE`), and updates
    each pending log row with scaled macros and `ai_enrich_status = 'complete'`.
    """
    own_db = db is None
    if own_db:
        db = get_db()

    try:
        cur = db.execute(
            "SELECT id, user_id, household_id, food_name, quantity, unit, gram_weight "
            "FROM nourish_food_logs "
            "WHERE ai_enrich_status = 'pending' "
            "ORDER BY id ASC LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall() if cur else []
        if not isinstance(rows, list):
            rows = []

        if not rows:
            return {"ok": True, "candidates": 0, "enriched": 0, "cataloged": 0}

        print(f"[NOURISH AI] Found {len(rows)} pending food log(s) to enrich.")
        if dry_run:
            return {
                "ok": True,
                "candidates": len(rows),
                "enriched": 0,
                "cataloged": 0,
                "dry_run": True,
            }

        # Group unique food_names by normalized_name (batch up to 25 per Gemini call)
        unique_foods = {}
        for r in rows:
            fname = str(r.get("food_name") or "").strip()
            norm = normalize_food_name(fname)
            if norm and norm not in unique_foods:
                unique_foods[norm] = fname

        norm_keys = list(unique_foods.keys())
        ai_by_norm = {}

        system_instruction = (
            "You are a clinical nutritionist and culinary food scientist.\n"
            f"{COOKED_VS_RAW_RULE}\n"
            "For each food item in the input array, estimate accurate nutrition values per 100 grams "
            "and a typical single serving weight in grams.\n"
            "Return ONLY a valid JSON array of objects with these exact keys:\n"
            "normalized_name, calories_per_100g, protein_per_100g, carbs_per_100g, fat_per_100g, "
            "fiber_per_100g, sugar_per_100g, sodium_mg_per_100g, serving_weight_g, serving_label, category."
        )

        for i in range(0, len(norm_keys), 25):
            chunk_norms = norm_keys[i:i + 25]
            batch_payload = [
                {"normalized_name": nk, "food_name": unique_foods[nk]}
                for nk in chunk_norms
            ]
            prompt = "Estimate per-100g nutrition and typical serving weight for these foods:\n" + json.dumps(batch_payload, indent=2)
            parsed = _call_gemini_json(system_instruction, prompt, temperature=0.2)
            if isinstance(parsed, dict):
                for wrapper_key in ["foods", "items", "results", "data", "nutrition"]:
                    if isinstance(parsed.get(wrapper_key), list):
                        parsed = parsed[wrapper_key]
                        break
                else:
                    if parsed.get("calories_per_100g") is not None or parsed.get("normalized_name"):
                        parsed = [parsed]

            if isinstance(parsed, list):
                if len(chunk_norms) == 1 and len(parsed) >= 1 and isinstance(parsed[0], dict):
                    ai_by_norm[chunk_norms[0]] = parsed[0]

                for entry in parsed:
                    if not isinstance(entry, dict):
                        continue
                    enorm = normalize_food_name(entry.get("normalized_name") or entry.get("food_name") or "")
                    if enorm:
                        ai_by_norm[enorm] = entry
            elif parsed is not None:
                print(f"[NOURISH AI] Warning: Gemini response could not be parsed as a list of food items: {type(parsed)}")

        catalog_id_by_norm = {}
        cataloged_count = 0

        for norm, display_name in unique_foods.items():
            raw_est = ai_by_norm.get(norm)
            if not raw_est:
                heur = _heuristic_food_nutrition(display_name)
                if not heur.get("is_unmatched") and float(heur.get("calories_per_100g") or 0.0) > 0:
                    raw_est = heur
                else:
                    # If AI returned None and heuristic returned is_unmatched or 0 cal,
                    # NEVER upsert into nourish_food_catalog as verified!
                    continue

            cal_100 = max(0.0, float(raw_est.get("calories_per_100g") or 0.0))
            if cal_100 <= 0:
                continue
            pro_100 = max(0.0, float(raw_est.get("protein_per_100g", 7.0) or 0.0))
            carb_100 = max(0.0, float(raw_est.get("carbs_per_100g", 18.0) or 0.0))
            fat_100 = max(0.0, float(raw_est.get("fat_per_100g", 5.0) or 0.0))
            fib_100 = max(0.0, float(raw_est.get("fiber_per_100g", 2.5) or 0.0))
            sug_100 = max(0.0, float(raw_est.get("sugar_per_100g", 2.0) or 0.0))
            sod_100 = max(0.0, float(raw_est.get("sodium_mg_per_100g", 200.0) or 0.0))
            srv_w = max(1.0, float(raw_est.get("serving_weight_g", 100.0) or 100.0))
            srv_label = str(raw_est.get("serving_label") or f"1 serving ({int(round(srv_w))}g)").strip()
            category = str(raw_est.get("category") or "Prepared Foods").strip()[:80]
            is_liquid = bool(raw_est.get("is_liquid", False))
            prep_state = "raw" if re.search(r"\b(raw|dry|uncooked)\b", norm) else str(raw_est.get("prep_state") or "cooked")[:20]

            normalized_est = {
                "calories_per_100g": round(cal_100, 2),
                "protein_per_100g": round(pro_100, 2),
                "carbs_per_100g": round(carb_100, 2),
                "fat_per_100g": round(fat_100, 2),
                "fiber_per_100g": round(fib_100, 2),
                "sugar_per_100g": round(sug_100, 2),
                "sodium_mg_per_100g": round(sod_100, 2),
                "serving_weight_g": round(srv_w, 2),
                "serving_label": srv_label,
                "category": category,
                "is_liquid": is_liquid,
                "prep_state": prep_state,
            }
            ai_by_norm[norm] = normalized_est

            upsert_cur = db.execute(
                """
                INSERT INTO nourish_food_catalog (
                    name, normalized_name, brand, category, source, is_public,
                    calories_per_100g, protein_per_100g, carbs_per_100g, fat_per_100g,
                    fiber_per_100g, sugar_per_100g, sodium_mg_per_100g,
                    serving_label, serving_weight_g, is_liquid, prep_state, ai_verified
                ) VALUES (
                    ?, ?, '', ?, 'ai_enriched', TRUE,
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?, TRUE
                )
                ON CONFLICT (normalized_name) WHERE is_public = TRUE
                DO UPDATE SET
                    calories_per_100g = EXCLUDED.calories_per_100g,
                    protein_per_100g = EXCLUDED.protein_per_100g,
                    carbs_per_100g = EXCLUDED.carbs_per_100g,
                    fat_per_100g = EXCLUDED.fat_per_100g,
                    fiber_per_100g = EXCLUDED.fiber_per_100g,
                    sugar_per_100g = EXCLUDED.sugar_per_100g,
                    sodium_mg_per_100g = EXCLUDED.sodium_mg_per_100g,
                    serving_label = EXCLUDED.serving_label,
                    serving_weight_g = EXCLUDED.serving_weight_g,
                    ai_verified = TRUE,
                    updated_at = NOW()
                RETURNING id
                """,
                (
                    display_name,
                    norm,
                    category,
                    normalized_est["calories_per_100g"],
                    normalized_est["protein_per_100g"],
                    normalized_est["carbs_per_100g"],
                    normalized_est["fat_per_100g"],
                    normalized_est["fiber_per_100g"],
                    normalized_est["sugar_per_100g"],
                    normalized_est["sodium_mg_per_100g"],
                    srv_label,
                    normalized_est["serving_weight_g"],
                    is_liquid,
                    prep_state,
                ),
            )
            up_row = upsert_cur.fetchone() if upsert_cur else None
            if up_row and isinstance(up_row, dict) and up_row.get("id"):
                catalog_id_by_norm[norm] = int(up_row["id"])
            cataloged_count += 1

        enriched_count = 0
        for r in rows:
            log_id = r["id"]
            fname = str(r.get("food_name") or "").strip()
            norm = normalize_food_name(fname)
            est = ai_by_norm.get(norm)
            if not est:
                heur = _heuristic_food_nutrition(fname)
                if not heur.get("is_unmatched") and float(heur.get("calories_per_100g") or 0.0) > 0:
                    est = heur
            if not est or float(est.get("calories_per_100g") or 0.0) <= 0:
                # Do not invent numbers if AI failed and no verified curated match; leave pending for next cron run
                continue

            scaled = compute_scaled_macros(
                est,
                r.get("quantity", 100),
                r.get("unit", "g"),
                serving_weight_g=est.get("serving_weight_g", 100.0),
            )
            cat_id = catalog_id_by_norm.get(norm)

            db.execute(
                """
                UPDATE nourish_food_logs
                SET calories = ?,
                    protein_g = ?,
                    carbs_g = ?,
                    fat_g = ?,
                    fiber_g = ?,
                    sugar_g = ?,
                    sodium_mg = ?,
                    gram_weight = ?,
                    catalog_id = COALESCE(?, catalog_id),
                    ai_enrich_status = 'complete',
                    updated_at = NOW()
                WHERE id = ?
                """,
                (
                    scaled["calories"],
                    scaled["protein_g"],
                    scaled["carbs_g"],
                    scaled["fat_g"],
                    scaled["fiber_g"],
                    scaled["sugar_g"],
                    scaled["sodium_mg"],
                    scaled["gram_weight"],
                    cat_id,
                    log_id,
                ),
            )
            enriched_count += 1

        db.commit()
        print(f"[NOURISH AI] Enriched {enriched_count} log(s) across {cataloged_count} catalog food(s).")
        return {
            "ok": True,
            "candidates": len(rows),
            "enriched": enriched_count,
            "cataloged": cataloged_count,
        }
    except Exception as exc:
        print(f"[NOURISH AI ERROR] Batch enrichment failed: {exc}")
        return {"ok": False, "error": str(exc), "candidates": 0, "enriched": 0, "cataloged": 0}
    finally:
        if own_db:
            close_db(db)


def search_public_nutrition_apis(query_str: str, timeout: float = 2.5):
    """
    Optional Tier-2 lookup against USDA FoodData Central / OpenFoodFacts.
    Safe fallback returning `[]` on network timeout or offline execution.
    """
    q = (query_str or "").strip()
    if len(q) < 2:
        return []

    results = []
    # Try OpenFoodFacts public search
    try:
        params = urllib.parse.urlencode({
            "search_terms": q,
            "search_simple": 1,
            "action": "process",
            "json": 1,
            "page_size": 5,
        })
        url = f"https://world.openfoodfacts.org/cgi/search.pl?{params}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "ListMate-Nourish/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            products = data.get("products", [])
            for prod in products:
                pname = (prod.get("product_name") or "").strip()
                nutr = prod.get("nutriments") or {}
                cal = nutr.get("energy-kcal_100g") or nutr.get("energy-kcal")
                if not pname or cal is None:
                    continue
                norm = normalize_food_name(pname)
                if not norm:
                    continue
                results.append({
                    "name": pname[:120],
                    "normalized_name": norm[:180],
                    "brand": (prod.get("brands") or "").split(",")[0].strip()[:80],
                    "category": "Packaged Foods",
                    "source": "openfoodfacts",
                    "is_public": True,
                    "calories_per_100g": round(max(0.0, float(cal or 0.0)), 2),
                    "protein_per_100g": round(max(0.0, float(nutr.get("proteins_100g") or 0.0)), 2),
                    "carbs_per_100g": round(max(0.0, float(nutr.get("carbohydrates_100g") or 0.0)), 2),
                    "fat_per_100g": round(max(0.0, float(nutr.get("fat_100g") or 0.0)), 2),
                    "fiber_per_100g": round(max(0.0, float(nutr.get("fiber_100g") or 0.0)), 2),
                    "sugar_per_100g": round(max(0.0, float(nutr.get("sugars_100g") or 0.0)), 2),
                    "sodium_mg_per_100g": round(max(0.0, float(nutr.get("sodium_100g") or 0.0) * 1000.0), 2),
                    "serving_label": str(prod.get("serving_size") or "1 serving (100g)")[:60],
                    "serving_weight_g": 100.0,
                    "is_liquid": False,
                    "prep_state": "as_is",
                    "ai_verified": True,
                })
                if len(results) >= 5:
                    break
    except Exception:
        return []

    return results


class PlateItemList(list):
    """List of parsed meal clause items with an associated logical plate_name."""

    def __init__(self, iterable=None, plate_name=""):
        super().__init__(iterable or [])
        self.plate_name = plate_name


_PROTEIN_KEYWORDS = {
    "chicken", "turkey", "beef", "steak", "pork", "salmon", "tuna", "shrimp",
    "fish", "tilapia", "cod", "egg", "eggs", "tofu", "paneer", "lamb", "bacon",
    "sausage", "ham", "tempeh", "lentil", "lentils", "dal"
}
_BASE_KEYWORDS = {
    "rice", "quinoa", "pasta", "noodles", "spaghetti", "macaroni", "toast",
    "bread", "salad", "greens", "potatoes", "potato", "sweet potato", "oats", "oatmeal"
}
_LOWERCASE_WORDS = {"a", "an", "the", "and", "with", "or", "in", "on", "at", "to", "for", "of", "de"}


def _clean_title_word(w: str, is_first: bool = False, is_last: bool = False) -> str:
    low = w.lower()
    if low == "&":
        return "&"
    if low in _LOWERCASE_WORDS and not is_first and not is_last:
        return low
    if w.isupper() and len(w) <= 4:
        return w
    return w.capitalize()


def _title_case_plate_name(text: str) -> str:
    tokens = text.split()
    if not tokens:
        return ""
    n = len(tokens)
    return " ".join(_clean_title_word(tok, is_first=(i == 0), is_last=(i == n - 1)) for i, tok in enumerate(tokens))


def _clean_ingredient_for_title(name: str) -> str:
    s = str(name or "").strip()
    s = re.sub(
        r"^\s*\d+(?:\.\d+)?\s*(?:g|grams?|oz|ounces?|ml|milliliters?|cups?|bowls?|servings?|pieces?|slices?)?\s+(?:of\s+)?",
        "",
        s,
        flags=re.IGNORECASE,
    ).strip()
    s = re.sub(r"^(?:cooked|steamed|dry|raw|uncooked)\s+", "", s, flags=re.IGNORECASE).strip()
    return s.strip()


def derive_plate_name(text_description: str, items: list = None) -> str:
    """
    Derives a clean, appetizing, concise logical plate name (max 4-6 words)
    from a free-text meal description or parsed food items.
    """
    desc = (text_description or "").strip()
    has_quantities = bool(re.search(r"\b\d+(?:\.\d+)?\s*(?:g|oz|ml|gram|ounce|milliliter)\b", desc, flags=re.IGNORECASE))
    has_multi_lines = "\n" in desc or ";" in desc
    clean_desc = re.sub(
        r"^\s*\d+(?:\.\d+)?\s*(?:servings?|bowls?|plates?|cups?|slices?|pieces?)?\s+(?:of\s+)?",
        "",
        desc,
        flags=re.IGNORECASE,
    ).strip()
    clean_desc = re.sub(r"\s+", " ", clean_desc)

    words = clean_desc.split()
    if not has_quantities and not has_multi_lines and 1 <= len(words) <= 6:
        m = re.match(r"^(.+?)\s+with\s+(.+?)(?:\s+and\s+|\s+&\s+)(.+)$", clean_desc, flags=re.IGNORECASE)
        if m:
            p1 = _title_case_plate_name(_clean_ingredient_for_title(m.group(1)))
            p2 = _title_case_plate_name(_clean_ingredient_for_title(m.group(2)))
            p3 = _title_case_plate_name(_clean_ingredient_for_title(m.group(3)))
            return f"{p1} with {p2} & {p3}"
        if "," not in clean_desc:
            return _title_case_plate_name(clean_desc)

    food_names = []
    if items:
        for it in items:
            fname = ""
            if isinstance(it, dict):
                fname = it.get("food_name") or it.get("name") or ""
            elif isinstance(it, str):
                fname = it
            cleaned = _clean_ingredient_for_title(fname)
            if cleaned and cleaned.lower() not in [x.lower() for x in food_names]:
                food_names.append(cleaned)

    if not food_names and desc:
        parts = [p.strip() for p in re.split(r"(?:,|\band\b|\bwith\b|\bplus\b|\n|;)+", desc, flags=re.IGNORECASE) if p.strip()]
        for p in parts:
            cleaned = _clean_ingredient_for_title(p)
            if cleaned and cleaned.lower() not in [x.lower() for x in food_names]:
                food_names.append(cleaned)

    if not food_names:
        return _title_case_plate_name(desc[:40]) if desc else "Custom Plate"

    titles = [_title_case_plate_name(fn) for fn in food_names]

    if len(titles) == 1:
        plate = titles[0]
    elif len(titles) == 2:
        first_low = titles[0].lower()
        second_low = titles[1].lower()
        is_first_protein = any(k in first_low for k in _PROTEIN_KEYWORDS)
        is_second_protein = any(k in second_low for k in _PROTEIN_KEYWORDS)
        is_first_base = any(k in first_low for k in _BASE_KEYWORDS)

        if is_second_protein and is_first_base and not is_first_protein:
            plate = f"{titles[1]} with {titles[0]}"
        else:
            plate = f"{titles[0]} with {titles[1]}"
    elif len(titles) == 3:
        plate = f"{titles[0]} with {titles[1]} & {titles[2]}"
    else:
        plate = f"{titles[0]} with {titles[1]} & {titles[2]}"

    plate_words = plate.split()
    if len(plate_words) > 6:
        plate_words = plate_words[:6]
        while plate_words and plate_words[-1].lower() in {"with", "and", "&", "of", "in", "to", "for", "on", "a", "an", "the"}:
            plate_words.pop()
        plate = " ".join(plate_words)

    return plate


_derive_plate_name = derive_plate_name


def _parse_heuristic_meal_clauses(text_description: str):
    """Deterministic fallback parser for natural-language meal descriptions."""
    raw_parts = [
        p.strip()
        for p in re.split(r"(?:,|\band\b|\bwith\b|\bplus\b|\n|;)+", text_description or "", flags=re.IGNORECASE)
        if p and p.strip()
    ]
    if not raw_parts and (text_description or "").strip():
        raw_parts = [(text_description or "").strip()]

    items = []
    for part in raw_parts:
        qty = 1.0
        unit = "serving"
        food_name = part

        m = re.match(
            r"^\s*(\d+(?:\.\d+)?)\s*(g|grams?|oz|ounces?|ml|milliliters?|cups?|bowls?|servings?|pieces?|slices?)?\s+(?:of\s+)?(.+)$",
            part,
            flags=re.IGNORECASE,
        )
        if m:
            qty = float(m.group(1))
            raw_u = (m.group(2) or "serving").lower()
            food_name = m.group(3).strip()
            if raw_u.startswith("g"):
                unit = "g"
            elif raw_u.startswith("oz") or raw_u.startswith("ounce"):
                unit = "oz"
            elif raw_u.startswith("ml") or raw_u.startswith("milliliter"):
                unit = "ml"
            else:
                unit = "serving"

        est = _heuristic_food_nutrition(food_name)
        is_pending = bool(est.get("is_unmatched") or est.get("calories_per_100g", 0.0) == 0.0)
        scaled = compute_scaled_macros(
            est,
            qty,
            unit,
            serving_weight_g=est.get("serving_weight_g", 100.0),
        )
        items.append({
            "food_name": food_name[:120],
            "name": food_name[:120],
            "quantity": scaled["quantity"],
            "serving_amount": scaled["quantity"],
            "unit": scaled["unit"],
            "serving_unit": scaled["unit"],
            "gram_weight": scaled["gram_weight"],
            "calories": 0.0 if is_pending else scaled["calories"],
            "protein_g": 0.0 if is_pending else scaled["protein_g"],
            "carbs_g": 0.0 if is_pending else scaled["carbs_g"],
            "fat_g": 0.0 if is_pending else scaled["fat_g"],
            "fiber_g": 0.0 if is_pending else scaled["fiber_g"],
            "sugar_g": 0.0 if is_pending else scaled["sugar_g"],
            "sodium_mg": 0.0 if is_pending else scaled["sodium_mg"],
            "calories_per_100g": 0.0 if is_pending else est["calories_per_100g"],
            "protein_per_100g": 0.0 if is_pending else est["protein_per_100g"],
            "carbs_per_100g": 0.0 if is_pending else est["carbs_per_100g"],
            "fat_per_100g": 0.0 if is_pending else est["fat_per_100g"],
            "fiber_per_100g": 0.0 if is_pending else est["fiber_per_100g"],
            "serving_weight_g": est["serving_weight_g"],
            "serving_label": est["serving_label"],
            "category": est.get("category", "Prepared Foods"),
            "ai_enrich_status": "pending" if is_pending else "complete",
        })
    plate_name = derive_plate_name(text_description, items)
    return PlateItemList(items, plate_name=plate_name)


def analyze_natural_language_meal(text_description: str):
    """
    Deconstructs a free-text meal description into individual food items with 4-unit scaling
    and per-100g baselines, enforcing the COOKED vs RAW rule, and derives a concise logical plate title.
    """
    desc = (text_description or "").strip()
    if not desc:
        return {
            "plate_name": "",
            "items": [],
            "totals": {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": 0, "sugar_g": 0, "sodium_mg": 0},
        }

    system_instruction = (
        "You are an expert nutritionist deconstructing a meal log into individual food items.\n"
        f"{COOKED_VS_RAW_RULE}\n"
        "Return ONLY a JSON object with keys:\n"
        "1. 'plate_name': A clean, appetizing, concise title for this dish (e.g. 'Chicken Burrito Bowl', "
        "'Greek Yogurt with Blueberries & Walnuts', 'Avocado Toast with Poached Eggs', 'Spaghetti Bolognese'). Max 4-6 words.\n"
        "2. 'items': array of individual food items, where each item has:\n"
        "food_name, quantity (number), unit ('g', 'oz', 'ml', or 'serving'), "
        "calories_per_100g, protein_per_100g, carbs_per_100g, fat_per_100g, fiber_per_100g, "
        "sugar_per_100g, sodium_mg_per_100g, serving_weight_g, serving_label, category."
    )
    parsed = _call_gemini_json(system_instruction, f"Deconstruct this meal:\n{desc}", temperature=0.2)

    plate_name = ""
    if isinstance(parsed, dict):
        raw_plate = parsed.get("plate_name")
        if raw_plate and isinstance(raw_plate, str):
            plate_name = raw_plate.strip().strip('"\'')
            p_words = plate_name.split()
            if len(p_words) > 6:
                p_words = p_words[:6]
                while p_words and p_words[-1].lower() in {"with", "and", "&", "of", "in", "to", "for", "on", "a", "an", "the"}:
                    p_words.pop()
                plate_name = " ".join(p_words)

    items = []
    if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
        for entry in parsed["items"]:
            if not isinstance(entry, dict) or not entry.get("food_name"):
                continue
            srv_w = max(1.0, float(entry.get("serving_weight_g", 100.0) or 100.0))
            scaled = compute_scaled_macros(
                entry,
                entry.get("quantity", 1.0),
                entry.get("unit", "serving"),
                serving_weight_g=srv_w,
            )
            items.append({
                "food_name": str(entry["food_name"]).strip(),
                "name": str(entry["food_name"]).strip(),
                "quantity": scaled["quantity"],
                "serving_amount": scaled["quantity"],
                "unit": scaled["unit"],
                "serving_unit": scaled["unit"],
                "gram_weight": scaled["gram_weight"],
                "calories": scaled["calories"],
                "protein_g": scaled["protein_g"],
                "carbs_g": scaled["carbs_g"],
                "fat_g": scaled["fat_g"],
                "fiber_g": scaled["fiber_g"],
                "sugar_g": scaled["sugar_g"],
                "sodium_mg": scaled["sodium_mg"],
                "calories_per_100g": round(float(entry.get("calories_per_100g", 0.0) or 0.0), 2),
                "protein_per_100g": round(float(entry.get("protein_per_100g", 0.0) or 0.0), 2),
                "carbs_per_100g": round(float(entry.get("carbs_per_100g", 0.0) or 0.0), 2),
                "fat_per_100g": round(float(entry.get("fat_per_100g", 0.0) or 0.0), 2),
                "fiber_per_100g": round(float(entry.get("fiber_per_100g", 0.0) or 0.0), 2),
                "serving_weight_g": round(srv_w, 2),
                "serving_label": str(entry.get("serving_label") or f"1 serving ({int(round(srv_w))}g)"),
                "category": str(entry.get("category") or "Prepared Foods"),
            })

    if not items:
        heuristic_res = _parse_heuristic_meal_clauses(desc)
        items = list(heuristic_res)
        if not plate_name:
            plate_name = getattr(heuristic_res, "plate_name", "")

    if not plate_name:
        plate_name = derive_plate_name(desc, items)

    totals = {
        "calories": round(sum(i["calories"] for i in items), 2),
        "protein_g": round(sum(i["protein_g"] for i in items), 2),
        "carbs_g": round(sum(i["carbs_g"] for i in items), 2),
        "fat_g": round(sum(i["fat_g"] for i in items), 2),
        "fiber_g": round(sum(i["fiber_g"] for i in items), 2),
        "sugar_g": round(sum(i.get("sugar_g", 0.0) for i in items), 2),
        "sodium_mg": round(sum(i.get("sodium_mg", 0.0) for i in items), 2),
    }
    return {"plate_name": plate_name, "items": items, "totals": totals}


def analyze_recipe_nutrition(name: str, servings: float, raw_ingredients_text: str):
    """
    5-Baseline Recipe Calculator (ported from VitalPath):
    Computes total cooked weight, per-serving macros, per-100g macros, density (g/ml),
    and structured ingredient breakdown with heuristic fallback.
    """
    recipe_name = (name or "Custom Recipe").strip()
    try:
        srv_count = max(1.0, float(servings or 4.0))
    except (ValueError, TypeError):
        srv_count = 4.0
    raw_text = (raw_ingredients_text or "").strip()

    system_instruction = (
        "You are a culinary food scientist calculating 5-baseline recipe nutrition.\n"
        f"{COOKED_VS_RAW_RULE}\n"
        "Given a recipe name, number of servings, and raw ingredient lines, calculate:\n"
        "1. Structured ingredients array with cooked gram weights and macros: "
        "[{name, quantity_g, calories, protein, carbs, fat, fiber}]\n"
        "2. Total cooked weight in grams (accounting for water absorption or moisture evaporation during cooking)\n"
        "3. Total volume in ml and density_g_per_ml (typically 0.85 to 1.15)\n"
        "4. Per-serving macros and per-100g macros.\n"
        "Return ONLY a valid JSON object with keys: "
        "total_cooked_weight_g, total_volume_ml, density_g_per_ml, ingredients_json, ai_notes."
    )
    prompt = f"Recipe: {recipe_name}\nServings: {srv_count}\nIngredients:\n{raw_text}"
    parsed = _call_gemini_json(system_instruction, prompt, temperature=0.2) if raw_text else None

    ingredients_list = []
    if isinstance(parsed, dict) and isinstance(parsed.get("ingredients_json"), list):
        for ing in parsed["ingredients_json"]:
            if not isinstance(ing, dict) or not ing.get("name"):
                continue
            ingredients_list.append({
                "name": str(ing["name"]).strip(),
                "quantity_g": round(max(1.0, float(ing.get("quantity_g", 100.0) or 100.0)), 2),
                "calories": round(max(0.0, float(ing.get("calories", 0.0) or 0.0)), 2),
                "protein": round(max(0.0, float(ing.get("protein", 0.0) or 0.0)), 2),
                "carbs": round(max(0.0, float(ing.get("carbs", 0.0) or 0.0)), 2),
                "fat": round(max(0.0, float(ing.get("fat", 0.0) or 0.0)), 2),
                "fiber": round(max(0.0, float(ing.get("fiber", 0.0) or 0.0)), 2),
            })

    if not ingredients_list:
        lines = [ln.strip() for ln in re.split(r"[\n,;]+", raw_text) if ln.strip()]
        if not lines:
            lines = [recipe_name]
        for ln in lines:
            clause_items = _parse_heuristic_meal_clauses(ln)
            for ci in clause_items:
                ingredients_list.append({
                    "name": ci["food_name"],
                    "quantity_g": ci["gram_weight"],
                    "calories": ci["calories"],
                    "protein": ci["protein_g"],
                    "carbs": ci["carbs_g"],
                    "fat": ci["fat_g"],
                    "fiber": ci["fiber_g"],
                })

    total_ing_weight = sum(i["quantity_g"] for i in ingredients_list) or 400.0
    total_cooked_weight_g = round(
        max(50.0, float((parsed or {}).get("total_cooked_weight_g") or total_ing_weight)),
        2,
    )
    density_g_per_ml = round(
        max(0.5, min(2.0, float((parsed or {}).get("density_g_per_ml") or 1.05))),
        3,
    )
    total_volume_ml = round(
        float((parsed or {}).get("total_volume_ml") or (total_cooked_weight_g / density_g_per_ml)),
        2,
    )
    serving_weight_g = round(total_cooked_weight_g / srv_count, 2)

    total_cal = sum(i["calories"] for i in ingredients_list)
    total_pro = sum(i["protein"] for i in ingredients_list)
    total_carb = sum(i["carbs"] for i in ingredients_list)
    total_fat = sum(i["fat"] for i in ingredients_list)
    total_fib = sum(i["fiber"] for i in ingredients_list)

    w_factor = 100.0 / total_cooked_weight_g if total_cooked_weight_g > 0 else 1.0

    return {
        "name": recipe_name,
        "servings": round(srv_count, 2),
        "total_cooked_weight_g": total_cooked_weight_g,
        "total_volume_ml": total_volume_ml,
        "density_g_per_ml": density_g_per_ml,
        "serving_weight_g": serving_weight_g,
        "raw_ingredients_text": raw_text,
        "ingredients_json": ingredients_list,
        "calories_per_serving": round(total_cal / srv_count, 2),
        "protein_per_serving": round(total_pro / srv_count, 2),
        "carbs_per_serving": round(total_carb / srv_count, 2),
        "fat_per_serving": round(total_fat / srv_count, 2),
        "fiber_per_serving": round(total_fib / srv_count, 2),
        "sugar_per_serving": 0.0,
        "sodium_mg_per_serving": 0.0,
        "calories_per_100g": round(total_cal * w_factor, 2),
        "protein_per_100g": round(total_pro * w_factor, 2),
        "carbs_per_100g": round(total_carb * w_factor, 2),
        "fat_per_100g": round(total_fat * w_factor, 2),
        "fiber_per_100g": round(total_fib * w_factor, 2),
        "ai_notes": str((parsed or {}).get("ai_notes") or "Calculated with 5-baseline cooked yield model."),
    }
