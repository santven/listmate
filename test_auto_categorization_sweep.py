#!/usr/bin/env python3
"""Automated tests for Issue #465: Multi-tier auto-categorization sweep."""

import unittest
from unittest.mock import MagicMock, patch
import categorize

class TestCategorizeEngine(unittest.TestCase):
    def test_core_grocery_categorization(self):
        cases = [
            ("Egg", "Dairy"),
            ("A2 Whole Milk", "Dairy"),
            ("Fairlife Lactose Free Milk 52 fl oz", "Dairy"),
            ("Bonne Maman Strawberry Preserves 13 oz", "Snacks & Sweets"),
            ("Campbell Condensed Tomato Soup 10.75 oz", "Canned & Jarred"),
            ("Chicken Noodle Soup", "Canned & Jarred"),
            ("Swanson Chicken Broth 32 oz", "Canned & Jarred"),
            ("Claritin 24 Hour Allergy Relief 30 tablets", "Health & Personal Care"),
            ("Flonase Allergy Relief Nasal Spray", "Health & Personal Care"),
            ("Advil Liqui-Gels 200mg 100 ct", "Health & Personal Care"),
            ("Spaghetti Squash", "Produce"),
            ("Red Bull Energy Drink 12 fl oz", "Beverages"),
            ("Oreos Double Stuf Family Size", "Snacks & Sweets"),
            ("Romaine Hearts 3 pack", "Produce"),
            ("Impossible Burger Ground 12 oz", "Meat & Seafood"),
            ("Beyond Meat Beyond Burger", "Meat & Seafood"),
            ("Garlic Bread", "Bakery"),
            ("Banana Bread", "Bakery"),
            ("Apple Pie", "Bakery"),
            ("Grape Juice", "Beverages"),
            ("Strawberry Jam", "Snacks & Sweets"),
            ("Almond Butter", "Snacks & Sweets"),
            ("Foster Farms Fresh Chicken Thighs 3 lb", "Meat & Seafood"),
            ("Silk Pure Almond Milk Unsweetened", "Dairy"),
            ("Rao Homemade Marinara Pasta Sauce 24 oz", "Canned & Jarred"),
            ("Dawn Platinum Dishwashing Foam 16 fl oz", "Household"),
            ("Charmin Ultra Soft Bath Tissue 12 Mega Rolls", "Household"),
            ("Paper Towel 6 rolls", "Household"),
            ("Swad Idli Rava 5 lb", "Indian Specialties"),
            ("Deep Toor Dal 4 lb", "Legumes & Grains"),
        ]
        for name, expected in cases:
            res = categorize.categorize(name)
            self.assertEqual(res, expected, f"Failed for '{name}': expected '{expected}', got '{res}'")

    def test_backfill_uncategorized_items_with_mock_db(self):
        # Mock database with uncategorized items
        mock_db = MagicMock()
        
        # 2 uncategorized store items
        mock_db.execute.side_effect = [
            # store_rows
            MagicMock(fetchall=lambda: [
                {"id": 1, "name": "Organic Whole Milk 1 gal", "household_id": 10, "store_id": 1},
                {"id": 2, "name": "Mystery Peer Item", "household_id": 10, "store_id": 1},
            ]),
            # list_rows
            MagicMock(fetchall=lambda: [
                {"id": 101, "name": "Campbell Condensed Tomato Soup 10.75 oz", "household_id": 10, "store_id": 1},
                {"id": 102, "name": "Charmin Ultra Soft 12 rolls", "household_id": 10, "store_id": 1},
            ]),
            # stat_rows
            MagicMock(fetchall=lambda: [
                {"household_id": 10, "name": "Claritin 24hr Allergy Relief"},
            ]),
            # peer_query
            MagicMock(fetchall=lambda: [
                {"norm_name": "mystery peer item", "category": "Bakery", "cnt": 5},
            ]),
            # db.execute for updates...
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        ]

        import sys
        mock_db_pg = MagicMock()
        mock_db_pg.get_db.return_value = mock_db
        with patch.dict(sys.modules, {"db_pg": mock_db_pg}):
            stats = categorize.backfill_uncategorized_items(use_ai=False)
            
            self.assertEqual(stats["store_items_updated"], 2)
            self.assertEqual(stats["list_items_updated"], 2)
            self.assertEqual(stats["purchase_stats_updated"], 1)
            self.assertEqual(stats["tier1_rule_matched"], 4)  # Milk, Soup, Charmin, Claritin
            self.assertEqual(stats["tier2_peer_matched"], 1)  # Mystery Peer Item -> Bakery
            mock_db.commit.assert_called_once()
            mock_db.close.assert_called_once()

    def test_db_close_called_on_exception(self):
        mock_db = MagicMock()
        mock_db.execute.side_effect = Exception("Database network failure")
        import sys
        mock_db_pg = MagicMock()
        mock_db_pg.get_db.return_value = mock_db
        with patch.dict(sys.modules, {"db_pg": mock_db_pg}):
            stats = categorize.backfill_uncategorized_items(use_ai=False)
            self.assertEqual(stats["store_items_updated"], 0)
            mock_db.close.assert_called_once()

    def test_gemini_batch_fallback_parsing(self):
        mock_response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": '{"Unknown Exotic Fruit": "Produce", "Special Artisan Cookie": "Snacks & Sweets"}'
                    }]
                }
            }]
        }
        with patch("urllib.request.urlopen") as mock_url:
            mock_resp_obj = MagicMock()
            mock_resp_obj.read.return_value = categorize.json.dumps(mock_response).encode("utf-8")
            mock_resp_obj.__enter__.return_value = mock_resp_obj
            mock_url.return_value = mock_resp_obj

            res = categorize.categorize_batch_gemini(
                ["Unknown Exotic Fruit", "Special Artisan Cookie"],
                api_key="test-api-key"
            )
            self.assertEqual(res.get("Unknown Exotic Fruit"), "Produce")
            self.assertEqual(res.get("Special Artisan Cookie"), "Snacks & Sweets")

if __name__ == "__main__":
    unittest.main()
