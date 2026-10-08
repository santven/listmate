import os
import re
import json
import urllib.request
import datetime
from db_pg import get_db, close_db


def _discover_gemini_key():
    for var in ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"]:
        k = os.environ.get(var, "").strip()
        if k and not k.startswith("dev-") and not k.startswith("secret-"):
            return k
    for path in ["/opt/shared/.env", ".env", "/app/applet/.env"]:
        if os.path.exists(path):
            try:
                for line in open(path):
                    for var in ["GEMINI_API_KEY=", "GOOGLE_API_KEY=", "GOOGLE_GENAI_API_KEY="]:
                        if line.strip().startswith(var):
                            k = line.split("=", 1)[1].strip().strip("'").strip('"')
                            if k and not k.startswith("dev-") and not k.startswith("secret-"):
                                return k
            except Exception:
                pass
    return ""


def enhance_still_good_shelf_life_batch(limit=50):
    """
    Runs once daily (e.g. at midnight GMT via cron_daily.py).
    Batch-enhances active Still Good items where ai_estimated is FALSE.
    Conservative about food safety and token-efficient (batches all items in a single call).
    Marks ai_estimated = TRUE so each item is processed exactly once.
    """
    db = get_db()
    try:
        cur = db.execute(
            "SELECT id, name, location, item_type, TO_CHAR(date_added, 'YYYY-MM-DD') as date_added, notes "
            "FROM still_good_items "
            "WHERE status = 'active' AND ai_estimated = FALSE "
            "ORDER BY id ASC LIMIT ?",
            (limit,)
        )
        items = cur.fetchall() or []
        if not items:
            return {"ok": True, "processed": 0, "enhanced": 0, "message": "No unestimated items found"}

        print(f"[STILL GOOD AI] Found {len(items)} item(s) to evaluate for safe shelf life.")

        batch_payload = []
        for it in items:
            batch_payload.append({
                "id": it["id"],
                "name": it["name"],
                "location": it["location"],
                "type": it["item_type"],
                "notes": it.get("notes") or ""
            })

        key = _discover_gemini_key()
        models_to_try = [m.strip() for m in os.environ.get("GEMINI_MODEL_NAME", "gemini-3.1-flash-lite,gemini-flash-latest").split(",") if m.strip()]
        ai_results = {}

        if key:
            system_instruction = (
                "You are an expert culinary and food safety authority. "
                "For each leftover or prepared food item, evaluate its specific ingredients, storage location, and preparation type, "
                "and determine the safe conservative shelf life (in days) from the date stored, along with an optimal nudge window. "
                "CRITICAL PRINCIPLE:\n"
                "Be strictly conservative. Always prioritize food safety over shelf extension to prevent foodborne illness. "
                "Use your full knowledge of microbial growth, food chemistry, moisture activity, and temperature to decide the safe shelf life and cap. "
                "Provide a short 3-6 word practical tip (e.g., 'Reheat until steaming hot', 'Keep tightly sealed in freezer bag').\n"
                "Produce ONLY a valid JSON array of objects with keys: id, safe_days, tip. No markdown wrapping."
            )

            prompt = (
                "Conservatively evaluate the safe shelf-life in days and food safety tips for these items:\n" +
                json.dumps(batch_payload, indent=2)
            )

            body = {
                "contents": [
                    {
                        "parts": [
                            {"text": system_instruction + "\n\n" + prompt}
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.2,
                    "responseMimeType": "application/json"
                }
            }

            for model_name in models_to_try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
                req = urllib.request.Request(
                    url,
                    data=json.dumps(body).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": key,
                        "User-Agent": "listmate-stillgood-cron"
                    }
                )
                try:
                    with urllib.request.urlopen(req, timeout=14) as resp:
                        raw = resp.read().decode("utf-8")
                        data = json.loads(raw)
                        candidates = data.get("candidates", [])
                        if candidates:
                            text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                            if text.startswith("```"):
                                lines = text.splitlines()
                                if lines[0].startswith("```"): lines = lines[1:]
                                if lines and lines[-1].startswith("```"): lines = lines[:-1]
                                text = "\n".join(lines).strip()
                            parsed = json.loads(text)
                            if isinstance(parsed, list):
                                for entry in parsed:
                                    if "id" in entry and "safe_days" in entry:
                                        ai_results[int(entry["id"])] = {
                                            "safe_days": max(1, int(entry["safe_days"])),
                                            "tip": (entry.get("tip") or "").strip()
                                        }
                                print(f"[STILL GOOD AI] Model {model_name} successfully evaluated {len(ai_results)} item(s).")
                                break
                except Exception as e:
                    print(f"[STILL GOOD AI ERROR] Call to {model_name} failed: {e}")
                    continue
        else:
            print("[STILL GOOD AI] No Gemini key found; using conservative heuristic rules.")

        # Apply updates to database
        updated_count = 0
        for it in items:
            item_id = it["id"]
            date_added_str = it["date_added"]
            try:
                date_added = datetime.datetime.strptime(date_added_str, "%Y-%m-%d").date()
            except Exception:
                date_added = datetime.date.today()

            res = ai_results.get(item_id)
            if res:
                safe_days = res["safe_days"]
                tip = res["tip"]
            else:
                # Conservative fallback
                if it["location"] == "freezer":
                    if it["item_type"] == "restaurant":
                        safe_days = 30
                        tip = "Best within 1 month in freezer"
                    else:
                        safe_days = 60
                        tip = "Keep airtight to avoid freezer burn"
                elif it["item_type"] == "restaurant":
                    safe_days = 1
                    tip = "Best consumed within 24 hours"
                elif it["item_type"] == "batch_cook":
                    safe_days = 4
                    tip = "Portion out and reheat thoroughly"
                else:
                    safe_days = 3
                    tip = "Keep sealed and refrigerated"

            new_consume_by = date_added + datetime.timedelta(days=safe_days)

            db.execute(
                "UPDATE still_good_items "
                "SET consume_by = ?::date, "
                "    shelf_life_days = ?, "
                "    ai_tip = ?, "
                "    ai_estimated = TRUE, "
                "    ai_estimated_at = NOW(), "
                "    updated_at = NOW() "
                "WHERE id = ?",
                (new_consume_by.strftime("%Y-%m-%d"), safe_days, tip, item_id)
            )
            updated_count += 1

        db.commit()
        print(f"[STILL GOOD AI] Successfully enhanced {updated_count} item(s).")
        return {"ok": True, "processed": len(items), "enhanced": updated_count}
    except Exception as exc:
        print(f"[STILL GOOD AI ERROR] Batch enhancement failed: {exc}")
        return {"ok": False, "error": str(exc)}
    finally:
        close_db(db)
