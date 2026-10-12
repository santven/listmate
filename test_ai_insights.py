import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock

os.environ["DATABASE_URL"] = "postgresql://dummy:5432/test"
os.environ["GEMINI_API_KEY"] = "fake-gemini-key"

for mod in ["google", "google.oauth2", "google.auth", "google.auth.transport", "google.auth.exceptions", "psycopg2", "psycopg2.extras", "psycopg2.pool", "requests"]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

if "flask_limiter" not in sys.modules:
    mock_limiter = MagicMock()
    mock_limiter.Limiter.return_value.limit.return_value = lambda f: f
    sys.modules["flask_limiter"] = mock_limiter
    sys.modules["flask_limiter.util"] = MagicMock()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app as flask_app
from app import app, _generate_fallback_ai_insights


class TestAIInsights(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_fallback_ai_insights_generator_with_still_good_savings(self):
        last_7_days = [{"store": "Trader Joe's", "visit_date": "2026-10-10", "items_count": 8}]
        prior_weeks = [{"store": "Trader Joe's", "visit_date": "2026-10-01", "items_count": 12}]
        top_items = [{"name": "Organic Milk", "total_purchases": 5}]
        still_good_stats = {
            "consumed_28d": 4,
            "discarded_28d": 1,
            "active_count": 3
        }

        insight = _generate_fallback_ai_insights(last_7_days, prior_weeks, top_items, still_good_stats)
        self.assertIn("In the last 7 days", insight)
        self.assertIn("$32", insight)  # 4 * $8 saved
        self.assertIn("$8", insight)   # 1 * $8 wasted
        self.assertIn("Still Good", insight)
        self.assertIn("Organic Milk", insight)

    @patch("app.get_db")
    @patch("shared.auth._one")
    @patch("shared.auth.is_logged_in", return_value=True)
    @patch("app._hh")
    def test_analytics_ai_requires_premium(self, mock_hh, mock_logged_in, mock_one, mock_db):
        mock_hh.return_value = 10
        mock_one.return_value = {"is_premium": False}
        res = self.client.post("/api/analytics/ai")
        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertIn("Premium required", data.get("error", ""))

    @patch("urllib.request.urlopen")
    @patch("app.get_db")
    @patch("shared.auth._one")
    @patch("shared.auth.is_logged_in", return_value=True)
    @patch("app._hh")
    def test_analytics_ai_prompt_contains_still_good_and_strictly_lite_models(
        self, mock_hh, mock_logged_in, mock_one, mock_db, mock_urlopen
    ):
        mock_hh.return_value = 10
        mock_one.return_value = {"is_premium": True}

        # Mock DB queries
        db_mock = MagicMock()
        mock_db.return_value = db_mock

        # Cached check returns None
        # visits, top_items, still_good_stats
        def fake_execute(query, params=None):
            m = MagicMock()
            if "ai_insights_cache" in query:
                m.fetchone.return_value = None
            elif "store_visits" in query:
                m.fetchall.return_value = [{"store": "Costco", "visit_date": "2026-10-10", "items_count": 15}]
            elif "item_purchase_stats" in query:
                m.fetchall.return_value = [{"name": "Eggs", "total_purchases": 6}]
            elif "still_good_items" in query:
                m.fetchone.return_value = {
                    "consumed_28d": 5,
                    "discarded_28d": 2,
                    "active_count": 4
                }
            return m

        db_mock.execute.side_effect = fake_execute

        # Mock Gemini success
        gemini_resp = MagicMock()
        gemini_resp.read.return_value = json.dumps({
            "candidates": [{
                "content": {
                    "parts": [{"text": "Great job saving $40 with Still Good! Try store lists next."}]
                }
            }]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = gemini_resp

        with patch.dict(os.environ, {"GEMINI_MODEL_NAME": "gemini-pro,gemini-flash-latest,gemini-3.1-flash-lite"}):
            res = self.client.post("/api/analytics/ai")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("ok"))
            self.assertIn("Still Good", data.get("insight"))

            # Verify Gemini was called with strictly lite model and 25s timeout
            mock_urlopen.assert_called_once()
            req_obj = mock_urlopen.call_args[0][0]
            timeout_val = mock_urlopen.call_args[1].get("timeout")
            self.assertEqual(timeout_val, 25)

            # URL must use gemini-3.1-flash-lite and NOT gemini-pro or gemini-flash-latest
            self.assertIn("gemini-3.1-flash-lite", req_obj.full_url)
            self.assertNotIn("gemini-pro", req_obj.full_url)
            self.assertNotIn("gemini-flash-latest", req_obj.full_url)

            # Request body must contain Still Good stats and feature recommendation
            req_body = json.loads(req_obj.data.decode("utf-8"))
            prompt_text = req_body["contents"][0]["parts"][0]["text"]
            self.assertIn("Still Good (track leftovers & fresh groceries", prompt_text)
            self.assertIn("Meals/Items Enjoyed (Consumed): 5 (~$40 saved)", prompt_text)
            self.assertIn("Items Spoiled/Discarded: 2 (~$16 wasted)", prompt_text)
            self.assertEqual(req_body["generationConfig"]["maxOutputTokens"], 600)

    @patch("urllib.request.urlopen")
    @patch("app.get_db")
    @patch("shared.auth._one")
    @patch("shared.auth.is_logged_in", return_value=True)
    @patch("app._hh")
    def test_analytics_ai_timeout_falls_back_to_heuristic_without_500(
        self, mock_hh, mock_logged_in, mock_one, mock_db, mock_urlopen
    ):
        mock_hh.return_value = 10
        mock_one.return_value = {"is_premium": True}

        db_mock = MagicMock()
        mock_db.return_value = db_mock

        def fake_execute(query, params=None):
            m = MagicMock()
            if "ai_insights_cache" in query:
                m.fetchone.return_value = None
            elif "store_visits" in query:
                m.fetchall.return_value = [{"store": "Costco", "visit_date": "2026-10-10", "items_count": 10}]
            elif "item_purchase_stats" in query:
                m.fetchall.return_value = [{"name": "Coffee", "total_purchases": 3}]
            elif "still_good_items" in query:
                m.fetchone.return_value = {
                    "consumed_28d": 3,
                    "discarded_28d": 1,
                    "active_count": 2
                }
            return m

        db_mock.execute.side_effect = fake_execute

        # Simulate read timeout on all Gemini calls
        mock_urlopen.side_effect = Exception("The read operation timed out")

        res = self.client.post("/api/analytics/ai")
        # Must return HTTP 200 with fallback insight instead of crashing with HTTP 500
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertFalse(data.get("cached"))
        insight = data.get("insight")
        self.assertIn("Still Good", insight)
        self.assertIn("$24", insight)  # 3 * 8
        self.assertIn("$8", insight)   # 1 * 8


if __name__ == "__main__":
    unittest.main()
