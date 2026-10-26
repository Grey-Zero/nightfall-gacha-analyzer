import unittest

from nightfall import database
from nightfall.database import DatabaseManager
from nightfall.pity import (
    PITY_CAP_NORMAL,
    PITY_CAP_STARTER,
    STANDARD_SIX_STARS,
    analyze_limited_guarantee,
    analyze_pity,
    count_pity,
    pity_group,
)


class PityAnalysisTests(unittest.TestCase):
    def test_pity_group_classifies_pool_ranges(self):
        self.assertEqual(pity_group(10000), "starter:10000")
        self.assertEqual(pity_group(20001), "standard")
        self.assertEqual(pity_group(20002), "selection")
        self.assertEqual(pity_group(30000), "limited")
        self.assertEqual(pity_group(40000), "unknown:40000")
        self.assertEqual(database.PITY_CAP_STARTER, PITY_CAP_STARTER)
        self.assertEqual(database.PITY_CAP_NORMAL, PITY_CAP_NORMAL)
        self.assertIs(database.STANDARD_SIX_STARS, STANDARD_SIX_STARS)
        self.assertIs(database.pity_group, pity_group)

    def test_count_pity_returns_intervals_and_current_count(self):
        rows = [
            {"rarity": 4},
            {"rarity": 6},
            {"rarity": 5},
            {"rarity": 6},
            {"rarity": 5},
        ]

        self.assertEqual(count_pity(rows), ([2, 2], 1))

    def test_limited_guarantee_reports_consecutive_off_banner_anomaly(self):
        rows = [
            {"rarity": 6, "result_id": 13001009, "pool_id": 30001},
            {"rarity": 6, "result_id": 90000001, "pool_id": 30001},
            {"rarity": 6, "result_id": 13001012, "pool_id": 30002},
            {"rarity": 6, "result_id": 13001025, "pool_id": 30002},
        ]

        result = analyze_limited_guarantee(rows)

        self.assertTrue(result["guaranteed"])
        self.assertEqual(result["featured_hits"], 1)
        self.assertEqual(result["off_banner"], 3)
        self.assertEqual(len(result["anomalies"]), 1)
        self.assertEqual(result["anomalies"][0]["result_id"], 13001025)

    def test_analyze_pity_preserves_normal_and_starter_result_shapes(self):
        limited_rows = [
            {"rarity": 6, "result_id": 13001009, "pool_id": 30001},
            {"rarity": 5, "result_id": 90000001, "pool_id": 30001},
        ]
        starter_rows = [
            {"rarity": 6 if index == 4 else 5}
            for index in range(PITY_CAP_STARTER)
        ]

        result = analyze_pity({
            "standard": [{"rarity": 5}],
            "limited": limited_rows,
            "starter:10001": starter_rows,
        })

        self.assertEqual(result["standard"]["cap"], PITY_CAP_NORMAL)
        self.assertEqual(result["standard"]["current_pity"], 1)
        self.assertEqual(result["limited"]["current_pity"], 1)
        self.assertTrue(result["limited"]["guarantee"]["guaranteed"])
        self.assertEqual(result["starter:10001"]["pulls"], PITY_CAP_STARTER)
        self.assertEqual(result["starter:10001"]["current_pity"], 0)
        self.assertTrue(result["starter:10001"]["completed"])

    def test_database_manager_keeps_analyze_pity_entry_point(self):
        db = DatabaseManager(":memory:")
        try:
            account_id = db.create_account("test")
            db.conn.execute(
                """
                INSERT INTO records VALUES
                    (?, 30001, ?, 1000, 0, 6, 'card', 'character',
                     'limited', '1970-01-01T00:00:01Z')
                """,
                (account_id, next(iter(STANDARD_SIX_STARS))),
            )
            db.conn.commit()

            result = db.analyze_pity(account_id)
        finally:
            db.close()

        self.assertEqual(result["limited"]["six_star_intervals"], [1])
        self.assertTrue(result["limited"]["guarantee"]["guaranteed"])


if __name__ == "__main__":
    unittest.main()
