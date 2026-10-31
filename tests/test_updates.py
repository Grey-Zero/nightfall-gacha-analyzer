import unittest
from unittest.mock import patch

from nightfall import updates


class VersionTests(unittest.TestCase):
    def test_versions_are_compared_numerically(self):
        self.assertEqual(updates.compare_versions("v0.2.0", "0.1.5"), 1)
        self.assertEqual(updates.compare_versions("0.1.5", "v0.1.5"), 0)
        self.assertEqual(updates.compare_versions("0.1.10", "0.1.9"), 1)
        self.assertEqual(updates.compare_versions("0.1", "0.1.0"), 0)
        self.assertIsNone(updates.compare_versions("nightly", "0.1.5"))
        self.assertIsNone(updates.compare_versions(None, "0.1.5"))

    def test_newer_release_is_reported(self):
        current = updates.parse_version(updates.APP_VERSION)
        newer = f"{current[0] + 1}.0.0"
        with patch.object(updates, "_fetch_release", return_value={
            "tag_name": f"v{newer}",
            "html_url": "https://example.test/release",
            "body": "更新说明",
            "published_at": "2026-11-01T00:00:00Z",
        }):
            result = updates.check_update()

        self.assertTrue(result["available"])
        self.assertEqual(result["latest"], newer)
        self.assertEqual(result["url"], "https://example.test/release")
        self.assertEqual(result["notes"], "更新说明")
        self.assertIsNone(result["error"])

    def test_same_version_is_not_an_update(self):
        with patch.object(updates, "_fetch_release", return_value={
            "tag_name": f"v{updates.APP_VERSION}",
        }):
            result = updates.check_update()

        self.assertFalse(result["available"])
        self.assertIsNone(result["error"])

    def test_network_failure_is_reported_without_raising(self):
        with patch.object(
            updates, "_fetch_release", side_effect=OSError("网络不可用")
        ):
            result = updates.check_update()

        self.assertFalse(result["available"])
        self.assertIn("网络不可用", result["error"])
        self.assertEqual(result["current"], updates.APP_VERSION)


if __name__ == "__main__":
    unittest.main()
