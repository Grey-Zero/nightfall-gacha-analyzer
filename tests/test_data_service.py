import json
import tempfile
import unittest
from pathlib import Path

from nightfall.cards import get_featured_card_id, get_pool
from nightfall.data_service import get_dashboard, get_export_data
from nightfall.database import DatabaseManager


class DataServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db = DatabaseManager(self.db_path)
        self.account_id = self.db.create_account("dashboard-test")

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_featured_pool_metadata_is_loaded(self):
        self.assertEqual(get_featured_card_id(30001), 13001017)
        self.assertEqual(get_featured_card_id(30008), 13001062)
        self.assertIsNone(get_featured_card_id(99999))
        self.assertEqual(get_pool(30008)["name"], "幸福无罪论")

    def test_dashboard_builds_intervals_misses_and_current_pity(self):
        self.db.insert_records(self.account_id, [
            (30001, 13001039, 1000, 3),
            (30001, 13001001, 2000, 2),
            (30001, 13001017, 3000, 1),
            (30001, 13001002, 4000, 0),
            (20001, 13001001, 5000, 4),
            (20001, 13001039, 6000, 3),
            (20004, 13001039, 7000, 2),
            (10001, 13001001, 8000, 1),
            (10001, 13001002, 9000, 0),
        ])

        dashboard = get_dashboard(self.account_id, self.db_path)
        groups = {group["id"]: group for group in dashboard["groups"]}

        self.assertEqual(dashboard["total_records"], 9)
        self.assertEqual(groups["limited"]["pulls"], 4)
        self.assertEqual(groups["limited"]["current_pity"], 1)
        limited_events = groups["limited"]["events"]
        self.assertEqual([event["pulls"] for event in limited_events], [1, 2])
        self.assertTrue(limited_events[0]["miss"])
        self.assertFalse(limited_events[1]["miss"])
        self.assertEqual(groups["standard"]["six_stars"], 1)
        self.assertEqual(groups["selection"]["events"][0]["pulls"], 1)
        self.assertTrue(groups["selection"]["events"][0]["miss"])
        self.assertEqual(groups["starter:10001"]["current_pity"], 2)

    def test_dashboard_includes_five_star_cards_and_summary_metrics(self):
        self.db.insert_records(self.account_id, [
            (30008, 13001001, 1000, 5),
            (30008, 13001002, 2000, 4),
            (30008, 13001062, 3000, 3),
            (30008, 13001002, 4000, 2),
            (30008, 13001039, 5000, 1),
        ])

        dashboard = get_dashboard(self.account_id, self.db_path)
        limited = next(group for group in dashboard["groups"]
                       if group["id"] == "limited")

        self.assertEqual(
            [card["card_name"] for card in limited["events"][0]["five_stars"]],
            ["狂野先锋"],
        )
        self.assertEqual(
            [card["card_name"] for card in limited["events"][1]["five_stars"]],
            ["狂野先锋"],
        )
        self.assertEqual(dashboard["total_records"], 5)
        self.assertEqual(dashboard["total_six_stars"], 2)
        self.assertEqual(dashboard["featured_six_stars"], 2)
        self.assertEqual(dashboard["missed_six_stars"], 1)
        self.assertEqual(dashboard["on_rate"], 0.5)

    def test_export_data_contains_only_the_selected_account_records(self):
        self.db.insert_records(self.account_id, [
            (30008, 13001062, 1000, 0),
        ])

        export = get_export_data(self.account_id, self.db_path)

        self.assertEqual(export["account"]["account_id"], self.account_id)
        self.assertEqual(export["total_records"], 1)
        self.assertEqual(export["records"][0]["result_id"], 13001062)

    def test_pulls_over_cap_are_clamped_for_display(self):
        self.db.insert_records(self.account_id, [
            (30001, 13001001, 1000 + index, 70 - index)
            for index in range(71)
        ] + [(30001, 13001017, 2000, 0)])

        dashboard = get_dashboard(self.account_id, self.db_path)
        limited = next(group for group in dashboard["groups"]
                       if group["id"] == "limited")

        self.assertEqual(limited["events"][0]["actual_pulls"], 72)
        self.assertEqual(limited["events"][0]["pulls"], 70)
        self.assertEqual(limited["events"][0]["value"], 70)

    def test_current_pity_over_cap_is_clamped_for_display(self):
        self.db.insert_records(self.account_id, [
            (30001, 13001001, 1000 + index, 70 - index)
            for index in range(71)
        ])

        dashboard = get_dashboard(self.account_id, self.db_path)
        limited = next(group for group in dashboard["groups"]
                       if group["id"] == "limited")

        self.assertEqual(limited["actual_current_pity"], 71)
        self.assertEqual(limited["current_pity"], 70)

    def test_missing_account_is_reported(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            get_dashboard(-1, self.db_path)

    def test_pool_metadata_has_unique_ids_and_valid_featured_cards(self):
        pools = json.loads(Path("data/pools.json").read_text(encoding="utf-8"))
        cards = {
            card["id"]: card
            for card in json.loads(Path("data/cards.json").read_text(encoding="utf-8"))
        }

        self.assertEqual(len(pools), len({pool["id"] for pool in pools}))
        for pool in pools:
            featured_id = pool.get("featured_card_id")
            if featured_id is not None:
                self.assertEqual(cards[featured_id]["rarity"], 6)


if __name__ == "__main__":
    unittest.main()
