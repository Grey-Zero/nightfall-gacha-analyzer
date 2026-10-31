import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from nightfall.capture_service import CaptureService
from nightfall.database import DatabaseManager


class FakeMonitor:
    def __init__(self, records, extract_stats=None):
        self.records = records
        self.extract_stats = extract_stats
        self.recording = False
        self.preserved = None

    def start(self):
        self.recording = True

    def is_recording(self):
        return self.recording

    def get_captured_size(self):
        return 4096

    def stop(self):
        self.recording = False

    def process(self):
        return self.records

    def get_single_pool_count(self):
        return 0

    def get_server_total(self):
        if self.extract_stats and self.extract_stats.get("total"):
            return self.extract_stats["total"]
        return len(self.records)

    def get_extract_stats(self):
        if self.extract_stats is not None:
            return self.extract_stats
        if self.records:
            return {"total": len(self.records)}
        return {"responses": 3, "offset_mismatch": 2, "unpaired": 1}

    def get_capture_metadata(self):
        return {"endpoints": [["192.0.2.1", 9000]], "interface": "test"}

    def preserve_latest(self, target_dir, metadata=None):
        self.preserved = (target_dir, metadata)
        return None

    def cleanup(self):
        pass


class CaptureServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "capture-test.db"
        db = DatabaseManager(self.db_path)
        self.account_id = db.create_account("capture-test")
        db.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def wait_for_status(self, service, expected):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = service.get_state()
            if state["status"] == expected:
                return state
            if state["status"] == "error":
                self.fail(state["error"])
            time.sleep(0.01)
        self.fail(f"Timed out waiting for {expected}: {service.get_state()}")

    def test_capture_records_are_imported_into_selected_account(self):
        monitor = FakeMonitor([(30001, 13001017, 1000, 0)])
        service = CaptureService(self.db_path)
        with patch(
            "nightfall.capture_service.detect_game_connections",
            return_value={"endpoints": [("192.0.2.1", 9000)], "interface": "test"},
        ), patch("nightfall.capture_service.GachaMonitor", return_value=monitor):
            service.start(self.account_id)
            self.wait_for_status(service, "recording")
            service.stop()
            state = self.wait_for_status(service, "completed")

        self.assertEqual(state["result"]["records"], 1)
        self.assertEqual(state["result"]["inserted"], 1)
        db = DatabaseManager(self.db_path)
        try:
            self.assertEqual(db.get_record_count(self.account_id), 1)
            self.assertIsNotNone(db.get_last_update(self.account_id))
        finally:
            db.close()

    def test_gap_pages_are_not_imported(self):
        monitor = FakeMonitor(
            [(30001, 13001017, 1000, 0)],
            {"responses": 4, "gaps": [(5, 15)], "total": 20},
        )
        service = CaptureService(self.db_path)
        with patch(
            "nightfall.capture_service.detect_game_connections",
            return_value={"endpoints": [("192.0.2.1", 9000)], "interface": "test"},
        ), patch("nightfall.capture_service.GachaMonitor", return_value=monitor):
            service.start(self.account_id)
            self.wait_for_status(service, "recording")
            service.stop()
            state = self.wait_for_status(service, "completed")

        self.assertEqual(state["result"]["records"], 0)
        self.assertIn("漏页", state["result"]["message"])
        db = DatabaseManager(self.db_path)
        try:
            self.assertEqual(db.get_record_count(self.account_id), 0)
        finally:
            db.close()

    def test_incomplete_stream_is_not_imported(self):
        monitor = FakeMonitor(
            [(30001, 13001017, 1000, 0)],
            {"responses": 4, "incomplete_streams": 1, "total": 1276,
             "covered_end": 120},
        )
        service = CaptureService(self.db_path)
        with patch(
            "nightfall.capture_service.detect_game_connections",
            return_value={"endpoints": [("192.0.2.1", 9000)], "interface": "test"},
        ), patch("nightfall.capture_service.GachaMonitor", return_value=monitor):
            service.start(self.account_id)
            self.wait_for_status(service, "recording")
            service.stop()
            state = self.wait_for_status(service, "completed")

        self.assertEqual(state["result"]["records"], 0)
        self.assertIn("丢", state["result"]["message"])
        db = DatabaseManager(self.db_path)
        try:
            self.assertEqual(db.get_record_count(self.account_id), 0)
        finally:
            db.close()

    def test_latest_capture_is_preserved_after_capture(self):
        monitor = FakeMonitor([(30001, 13001017, 1000, 0)])
        service = CaptureService(
            self.db_path, captures_dir=Path(self.temp_dir.name))
        with patch(
            "nightfall.capture_service.detect_game_connections",
            return_value={"endpoints": [("192.0.2.1", 9000)], "interface": "test"},
        ), patch("nightfall.capture_service.GachaMonitor", return_value=monitor):
            service.start(self.account_id)
            self.wait_for_status(service, "recording")
            service.stop()
            self.wait_for_status(service, "completed")

        self.assertIsNotNone(monitor.preserved)
        target_dir, metadata = monitor.preserved
        self.assertEqual(str(target_dir), self.temp_dir.name)
        self.assertEqual(metadata["account_id"], self.account_id)
        self.assertEqual(metadata["endpoints"], [["192.0.2.1", 9000]])
        self.assertEqual(metadata["extract_stats"]["total"], 1)

    def test_cancel_waiting_for_game_connection(self):
        service = CaptureService(self.db_path)
        with patch(
            "nightfall.capture_service.detect_game_connections",
            return_value=None,
        ):
            service.start(self.account_id)
            service.stop()
            state = self.wait_for_status(service, "cancelled")
        self.assertEqual(state["account_id"], self.account_id)


if __name__ == "__main__":
    unittest.main()
