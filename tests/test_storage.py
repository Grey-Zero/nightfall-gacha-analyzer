import tempfile
import unittest
from pathlib import Path

from nightfall.storage import data_paths, migrate_legacy_data


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.legacy = root / "app"
        self.target = root / "appdata"
        self.legacy.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_database_config_and_captures_are_moved(self):
        (self.legacy / "nightfall.db").write_bytes(b"db")
        (self.legacy / "nightfall.db-wal").write_bytes(b"wal")
        (self.legacy / "config.json").write_text("{}", encoding="utf-8")
        captures = self.legacy / "captures"
        captures.mkdir()
        (captures / "latest-capture.pcap").write_bytes(b"pcap")

        result = migrate_legacy_data(self.legacy, self.target)

        self.assertFalse(result["failed"])
        self.assertEqual(
            sorted(result["migrated"]),
            ["captures/latest-capture.pcap", "config.json",
             "nightfall.db", "nightfall.db-wal"],
        )
        self.assertEqual((self.target / "nightfall.db").read_bytes(), b"db")
        self.assertTrue(
            (self.target / "captures" / "latest-capture.pcap").is_file())
        self.assertFalse((self.legacy / "nightfall.db").exists())
        self.assertFalse(captures.exists())

    def test_existing_target_data_is_never_overwritten(self):
        (self.legacy / "nightfall.db").write_bytes(b"old")
        (self.legacy / "captures").mkdir()
        (self.legacy / "captures" / "latest-capture.pcap").write_bytes(b"old")
        self.target.mkdir()
        (self.target / "nightfall.db").write_bytes(b"new")
        (self.target / "captures").mkdir()
        (self.target / "captures" / "latest-capture.pcap").write_bytes(b"new")

        result = migrate_legacy_data(self.legacy, self.target)

        self.assertEqual(result["migrated"], [])
        self.assertEqual((self.target / "nightfall.db").read_bytes(), b"new")
        self.assertEqual(
            (self.target / "captures" / "latest-capture.pcap").read_bytes(),
            b"new",
        )
        self.assertEqual((self.legacy / "nightfall.db").read_bytes(), b"old")

    def test_fresh_install_creates_target_directory(self):
        result = migrate_legacy_data(self.legacy, self.target)

        self.assertFalse(result["failed"])
        self.assertEqual(result["migrated"], [])
        self.assertTrue(self.target.is_dir())

    def test_data_paths_live_under_the_data_root(self):
        paths = data_paths(self.target)

        self.assertEqual(paths["db"], self.target / "nightfall.db")
        self.assertEqual(paths["captures"], self.target / "captures")


if __name__ == "__main__":
    unittest.main()
