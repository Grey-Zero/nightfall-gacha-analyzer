import sqlite3
import tempfile
import unittest
from pathlib import Path

from nightfall.cards import get_card
from nightfall.cli_ui import GROUP_NAMES
from nightfall.database import DatabaseManager


class PositionValidationTests(unittest.TestCase):
    def test_pity_group_labels_distinguish_rotation_and_starter_pools(self):
        self.assertEqual(GROUP_NAMES["standard"], "常驻")
        self.assertEqual(GROUP_NAMES["selection"], "轮替")
        self.assertEqual(GROUP_NAMES["starter:10001"], "新手")

    def test_new_six_star_cards_are_in_the_card_catalog(self):
        self.assertEqual(
            get_card(13001029),
            {"id": 13001029, "name": "杯中藏锋", "character": "某某人", "rarity": 6},
        )
        self.assertEqual(
            get_card(13001063),
            {"id": 13001063, "name": "执剑人", "character": "骑士", "rarity": 6},
        )

    def setUp(self):
        self.db = DatabaseManager(":memory:")
        self.account_id = self.db.create_account("position-test")

    def tearDown(self):
        self.db.close()

    def test_position_range_counts_distinct_positions(self):
        self.db.insert_records(self.account_id, [
            (30001, 13001001, 3000, 0),
            (30001, 13001002, 2000, 0),
            (30001, 13001003, 1000, 1),
        ])

        self.assertEqual(
            self.db.get_position_range(self.account_id),
            {"min": 0, "max": 1, "count": 2, "missing": 0},
        )

    def test_direction_check_collapses_records_with_same_position(self):
        self.db.insert_records(self.account_id, [
            (30001, 13001001, 3000, 0),
            (30001, 13001002, 2000, 0),
            (30001, 13001003, 1000, 1),
        ])

        self.assertEqual(
            self.db.verify_position_direction(self.account_id),
            (True, 0, 2),
        )

    def test_position_range_reports_gaps_between_unique_positions(self):
        self.db.insert_records(self.account_id, [
            (30001, 13001001, 3000, 0),
            (30001, 13001002, 1000, 2),
        ])

        self.assertEqual(
            self.db.get_position_range(self.account_id),
            {"min": 0, "max": 2, "count": 2, "missing": 1},
        )

    def test_new_records_shift_existing_positions_and_deduplicate_overlap(self):
        old_records = [
            (30001, 13001001, 1000, 0),
            (30001, 13001002, 2000, 1),
            (30001, 13001003, 3000, 2),
        ]
        self.db.insert_records(self.account_id, old_records)

        inserted, duplicated, new_records = self.db.insert_records(
            self.account_id,
            [
                (30001, 13001005, 5000, 0),
                (30001, 13001004, 4000, 1),
                (30001, 13001001, 1000, 2),
                (30001, 13001002, 2000, 3),
                (30001, 13001003, 3000, 4),
            ],
        )

        self.assertEqual((inserted, duplicated), (2, 3))
        self.assertEqual(self.db.last_position_shift, 2)
        self.assertEqual([record["position"] for record in new_records], [0, 1])
        self.assertEqual(
            self.db.get_position_range(self.account_id),
            {"min": 0, "max": 4, "count": 5, "missing": 0},
        )

        self.db.save_update_snapshot(
            self.account_id, inserted, new_records, self.db.last_position_shift)
        self.assertEqual(self.db.undo_last_update(self.account_id), (True, 2))
        self.assertEqual(
            self.db.get_position_range(self.account_id),
            {"min": 0, "max": 2, "count": 3, "missing": 0},
        )
        self.assertEqual(self.db.get_record_count(self.account_id), 3)

    def test_new_conflicting_position_without_safe_overlap_is_rejected(self):
        self.db.insert_records(self.account_id, [
            (30001, 13001001, 1000, 0),
        ])

        with self.assertRaisesRegex(ValueError, "位置"):
            self.db.insert_records(self.account_id, [
                (30001, 13001002, 2000, 0),
            ])

        self.assertEqual(self.db.get_record_count(self.account_id), 1)
        self.assertEqual(self.db.last_position_shift, 0)

    def test_account_nickname_and_uid_can_be_updated(self):
        self.assertTrue(self.db.update_account(
            self.account_id, "沂倌的主账号", "123456789"))
        account = self.db.get_account(self.account_id)

        self.assertEqual(account["nickname"], "沂倌的主账号")
        self.assertEqual(account["uid"], "123456789")
        self.assertTrue(self.db.update_account(
            self.account_id, "主账号", None))
        self.assertIsNone(self.db.get_account(self.account_id)["uid"])
        self.assertFalse(self.db.update_account(-1, "不存在"))

    def test_account_note_is_optional_and_updatable(self):
        account = self.db.get_account(self.account_id)
        self.assertIsNone(account["note"])

        self.db.update_account(self.account_id, "主账号", None, "国服主号")
        self.assertEqual(
            self.db.get_account(self.account_id)["note"], "国服主号")

        self.db.update_account(self.account_id, "主账号", None, None)
        self.assertIsNone(self.db.get_account(self.account_id)["note"])

    def test_note_column_is_added_to_existing_database(self):
        legacy_path = Path(tempfile.mkdtemp()) / "legacy.db"
        conn = sqlite3.connect(legacy_path)
        conn.execute("""
            CREATE TABLE accounts (
                account_id INTEGER PRIMARY KEY AUTOINCREMENT,
                nickname TEXT NOT NULL UNIQUE,
                uid TEXT,
                created_at TEXT NOT NULL,
                last_active_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO accounts (nickname, uid, created_at, last_active_at) "
            "VALUES ('旧账号', NULL, '2026-01-01T00:00:00Z', "
            "'2026-01-01T00:00:00Z')")
        conn.commit()
        conn.close()

        db = DatabaseManager(legacy_path)
        try:
            account = db.get_all_accounts()[0]
            self.assertEqual(account["nickname"], "旧账号")
            self.assertIsNone(account["note"])
            db.update_account(account["account_id"], "旧账号", None, "迁移后")
            self.assertEqual(
                db.get_account(account["account_id"])["note"], "迁移后")
        finally:
            db.close()

    def test_account_rename_rejects_a_duplicate_nickname(self):
        self.db.create_account("已有账号")
        with self.assertRaisesRegex(ValueError, "昵称已被其他账号使用"):
            self.db.update_account(self.account_id, "已有账号")

    def test_delete_account_cascades_records_and_updates(self):
        self.db.insert_records(self.account_id, [
            (30001, 13001001, 1000, 0),
        ])
        self.db.save_update_snapshot(self.account_id, 1, [{
            "pool_id": 30001,
            "result_id": 13001001,
            "timestamp_ms": 1000,
            "position": 0,
        }])

        self.assertTrue(self.db.delete_account(self.account_id))
        self.assertIsNone(self.db.get_account(self.account_id))
        self.assertEqual(self.db.get_record_count(self.account_id), 0)
        self.assertIsNone(self.db.get_last_update(self.account_id))
        self.assertFalse(self.db.delete_account(self.account_id))


if __name__ == "__main__":
    unittest.main()
