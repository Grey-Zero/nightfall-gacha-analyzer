import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nightfall import cards, catalog

VALID_CARDS = [
    {"id": 13001001, "name": "灾厄小姐", "character": "火烛", "rarity": 4},
    {"id": 13001999, "name": "测试六星", "character": "替罪羊", "rarity": 6},
]
VALID_POOLS = [
    {"id": 30009, "name": "羊群安息处", "featured_card_id": 13001999},
]


class CatalogValidationTests(unittest.TestCase):
    def test_valid_tables_pass(self):
        self.assertIsNone(catalog.validate_cards(VALID_CARDS))
        self.assertIsNone(catalog.validate_pools(VALID_POOLS, VALID_CARDS))

    def test_cards_reject_bad_payloads(self):
        self.assertIsNotNone(catalog.validate_cards([]))
        self.assertIsNotNone(catalog.validate_cards({"id": 1}))
        self.assertIsNotNone(catalog.validate_cards(
            [{"id": 1, "name": "x", "character": "y", "rarity": 3}]))
        self.assertIsNotNone(catalog.validate_cards(
            [{"id": 1, "name": "x", "rarity": 6}]))
        self.assertIsNotNone(catalog.validate_cards(
            [{"id": True, "name": "x", "character": "y", "rarity": 6}]))
        self.assertIsNotNone(catalog.validate_cards(VALID_CARDS + VALID_CARDS))

    def test_pools_reject_unknown_featured_card(self):
        self.assertIsNotNone(catalog.validate_pools(
            [{"id": 30009, "name": "池", "featured_card_id": 123}], VALID_CARDS))
        self.assertIsNotNone(catalog.validate_pools(
            [{"id": 30009, "name": ""}], VALID_CARDS))


class CatalogRefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._previous = catalog.cache_dir()
        catalog.set_cache_dir(self.tmp)
        cards.reload()

    def tearDown(self):
        catalog.set_cache_dir(self._previous)
        cards.reload()

    def _fetch(self, cards_data=None, pools_data=None):
        def fake(url, timeout):
            if url.endswith("cards.json"):
                return cards_data
            return pools_data
        return mock.patch.object(catalog, "_fetch", side_effect=fake)

    def test_refresh_writes_cache_and_cards_prefer_it(self):
        with self._fetch(VALID_CARDS, VALID_POOLS):
            result = catalog.refresh()

        self.assertTrue(result["updated"])
        self.assertIsNotNone(result["source"])
        self.assertTrue((self.tmp / "cards.json").is_file())

        cards.reload()
        self.assertEqual(cards.get_card(13001999)["name"], "测试六星")
        self.assertEqual(cards.get_pool_name(30009), "羊群安息处")
        self.assertEqual(
            list(self.tmp.glob("*.tmp")), [], "临时文件应被替换掉")

    def test_failed_refresh_keeps_existing_cache(self):
        with self._fetch(VALID_CARDS, VALID_POOLS):
            catalog.refresh()

        with self._fetch(None, None):
            result = catalog.refresh()

        self.assertFalse(result["updated"])
        self.assertIsNotNone(result["error"])
        cards.reload()
        self.assertEqual(cards.get_card(13001999)["name"], "测试六星")

    def test_invalid_payload_is_not_written(self):
        with self._fetch(
            [{"id": 1, "name": "x", "character": "y", "rarity": 9}],
            VALID_POOLS,
        ):
            result = catalog.refresh()

        self.assertFalse(result["updated"])
        self.assertIn("校验", result["error"])
        self.assertFalse((self.tmp / "cards.json").exists())

    def test_corrupt_cache_falls_back_to_bundled_data(self):
        (self.tmp / "cards.json").write_text("{not json", encoding="utf-8")

        cards.reload()
        self.assertEqual(cards.get_card(13001001)["name"], "灾厄小姐")

    def test_corrupt_pools_cache_falls_back_to_bundled_data(self):
        (self.tmp / "pools.json").write_text("[1, 2]", encoding="utf-8")

        cards.reload()
        self.assertEqual(cards.get_pool_name(30008), "幸福无罪论")


if __name__ == "__main__":
    unittest.main()
