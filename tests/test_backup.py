import json
import tempfile
import unittest
from pathlib import Path

from nightfall.backup import (
    BACKUP_FORMAT,
    BACKUP_VERSION,
    build_backup,
    import_backup,
    import_backup_file,
)
from nightfall.database import DatabaseManager

RECORDS = [
    (30008, 13001062, 3000, 0),
    (30008, 13001001, 2000, 1),
    (20001, 13001039, 1000, 2),
]


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.source_path = Path(self.temp_dir.name) / "source.db"
        db = DatabaseManager(self.source_path)
        self.account_id = db.create_account("主账号", "10001", "国服主号")
        db.insert_records(self.account_id, RECORDS)
        db.create_account("空账号")
        db.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_backup_contains_all_accounts_and_records(self):
        backup = build_backup(self.source_path)

        self.assertEqual(backup["format"], BACKUP_FORMAT)
        self.assertEqual(backup["version"], BACKUP_VERSION)
        self.assertEqual(backup["account_count"], 2)
        self.assertEqual(backup["record_count"], 3)
        account = next(
            item for item in backup["accounts"] if item["nickname"] == "主账号")
        self.assertEqual(account["uid"], "10001")
        self.assertEqual(account["note"], "国服主号")
        self.assertEqual(
            sorted(record["result_id"] for record in account["records"]),
            [13001001, 13001039, 13001062],
        )

    def test_import_into_empty_database_restores_everything(self):
        backup = build_backup(self.source_path)
        target_path = Path(self.temp_dir.name) / "target.db"

        summary = import_backup(target_path, backup)

        self.assertEqual(summary["accounts_created"], 2)
        self.assertEqual(summary["accounts_matched"], 0)
        self.assertEqual(summary["records_inserted"], 3)
        self.assertEqual(summary["records_skipped"], 0)
        self.assertEqual(summary["errors"], [])

        db = DatabaseManager(target_path)
        try:
            accounts = {item["nickname"]: item for item in db.get_all_accounts()}
            self.assertEqual(accounts["主账号"]["uid"], "10001")
            self.assertEqual(accounts["主账号"]["note"], "国服主号")
            self.assertEqual(
                db.get_record_count(accounts["主账号"]["account_id"]), 3)
        finally:
            db.close()

    def test_import_matches_existing_account_without_duplicates(self):
        target_path = Path(self.temp_dir.name) / "target.db"
        import_backup(target_path, build_backup(self.source_path))

        summary = import_backup(target_path, build_backup(self.source_path))

        self.assertEqual(summary["accounts_created"], 0)
        self.assertEqual(summary["accounts_matched"], 2)
        self.assertEqual(summary["records_inserted"], 0)
        self.assertEqual(summary["records_skipped"], 3)

    def test_import_matches_by_nickname_not_by_uid(self):
        target_path = Path(self.temp_dir.name) / "target.db"
        db = DatabaseManager(target_path)
        # 本机同名账号的 UID 与备份不同，仍应视为同一个账号
        db.create_account("主账号", "99999")
        db.close()

        summary = import_backup(target_path, build_backup(self.source_path))

        self.assertEqual(summary["accounts_created"], 1)
        self.assertEqual(summary["accounts_matched"], 1)
        self.assertEqual(summary["records_inserted"], 3)

        db = DatabaseManager(target_path)
        try:
            accounts = {item["nickname"]: item for item in db.get_all_accounts()}
            self.assertEqual(len(accounts), 2)
            # 已有的 UID 不会被备份覆盖，缺失的备注会被补全
            self.assertEqual(accounts["主账号"]["uid"], "99999")
            self.assertEqual(accounts["主账号"]["note"], "国服主号")
        finally:
            db.close()

    def test_import_falls_back_to_unique_uid_after_rename(self):
        target_path = Path(self.temp_dir.name) / "target.db"
        db = DatabaseManager(target_path)
        db.create_account("改名后的账号", "10001")
        db.close()

        summary = import_backup(target_path, build_backup(self.source_path))

        self.assertEqual(summary["accounts_created"], 1)  # 只有空账号是新建的
        self.assertEqual(summary["accounts_matched"], 1)
        self.assertEqual(summary["records_inserted"], 3)

        db = DatabaseManager(target_path)
        try:
            names = {item["nickname"] for item in db.get_all_accounts()}
            self.assertEqual(names, {"改名后的账号", "空账号"})
        finally:
            db.close()

    def test_ambiguous_uid_creates_a_new_account(self):
        target_path = Path(self.temp_dir.name) / "target.db"
        db = DatabaseManager(target_path)
        db.create_account("账号甲", "10001")
        db.create_account("账号乙", "10001")
        db.close()

        summary = import_backup(target_path, build_backup(self.source_path))

        self.assertEqual(summary["accounts_created"], 2)
        self.assertEqual(summary["accounts_matched"], 0)

        db = DatabaseManager(target_path)
        try:
            names = {item["nickname"] for item in db.get_all_accounts()}
            self.assertEqual(names, {"账号甲", "账号乙", "主账号", "空账号"})
        finally:
            db.close()

    def test_import_adds_only_new_records_to_existing_account(self):
        target_path = Path(self.temp_dir.name) / "target.db"
        db = DatabaseManager(target_path)
        account_id = db.create_account("主账号", "10001")
        db.insert_records(account_id, [(30008, 13001062, 3000, 0)])
        db.close()

        summary = import_backup(target_path, build_backup(self.source_path))

        self.assertEqual(summary["accounts_matched"], 1)
        self.assertEqual(summary["accounts_created"], 1)
        self.assertEqual(summary["records_inserted"], 2)
        db = DatabaseManager(target_path)
        try:
            self.assertEqual(db.get_record_count(account_id), 3)
        finally:
            db.close()

    def test_import_rejects_foreign_files(self):
        with self.assertRaisesRegex(ValueError, "不是本工具的备份"):
            import_backup(Path(self.temp_dir.name) / "x.db", {"accounts": []})
        with self.assertRaisesRegex(ValueError, "更新版本"):
            import_backup(
                Path(self.temp_dir.name) / "x.db",
                {"format": BACKUP_FORMAT, "version": 99, "accounts": []},
            )

    def test_import_file_reads_json_and_reports_bad_json(self):
        target_path = Path(self.temp_dir.name) / "target.db"
        backup_path = Path(self.temp_dir.name) / "backup.json"
        backup_path.write_text(
            json.dumps(build_backup(self.source_path), ensure_ascii=False),
            encoding="utf-8",
        )

        summary = import_backup_file(target_path, backup_path)
        self.assertEqual(summary["records_inserted"], 3)

        bad_path = Path(self.temp_dir.name) / "bad.json"
        bad_path.write_text("{not json", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "有效的 JSON"):
            import_backup_file(target_path, bad_path)


if __name__ == "__main__":
    unittest.main()
