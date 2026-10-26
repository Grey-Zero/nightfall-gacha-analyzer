import unittest
from unittest.mock import patch

from nightfall.gacha import collect_query0_pages


class GachaPageConsistencyTests(unittest.TestCase):
    def test_identical_duplicate_page_is_kept_once(self):
        page = [(30008, 13001039, 1000)]
        with patch(
            "nightfall.gacha.parse_c08_response",
            side_effect=[(0, 1, page), (0, 1, page)],
        ):
            pages, stats = collect_query0_pages(
                [(1, b"first", 0), (2, b"repeat", 0)],
                {1: (0, 0), 2: (0, 0)},
            )

        self.assertEqual(pages, {0: page})
        self.assertEqual(stats["duplicate_pages"], 1)

    def test_conflicting_duplicate_page_is_rejected(self):
        with patch(
            "nightfall.gacha.parse_c08_response",
            side_effect=[
                (0, 1, [(30008, 13001039, 1000)]),
                (0, 1, [(30008, 13001044, 1000)]),
            ],
        ):
            with self.assertRaisesRegex(ValueError, "offset=0"):
                collect_query0_pages(
                    [(1, b"first", 0), (2, b"conflict", 0)],
                    {1: (0, 0), 2: (0, 0)},
                )

    def test_response_offset_must_match_its_request(self):
        with patch(
            "nightfall.gacha.parse_c08_response",
            return_value=(10, 11, [(30008, 13001039, 1000)]),
        ):
            with self.assertRaisesRegex(ValueError, "请求 offset=0"):
                collect_query0_pages(
                    [(1, b"wrong-offset", 0)],
                    {1: (0, 0)},
                )

    def test_total_must_remain_stable_during_capture(self):
        with patch(
            "nightfall.gacha.parse_c08_response",
            side_effect=[
                (0, 2, [(30008, 13001039, 1000)]),
                (1, 3, [(30008, 13001044, 2000)]),
            ],
        ):
            with self.assertRaisesRegex(ValueError, "总数从 2 变为 3"):
                collect_query0_pages(
                    [(1, b"page-zero", 0), (2, b"page-one", 0)],
                    {1: (0, 0), 2: (0, 1)},
                )


if __name__ == "__main__":
    unittest.main()
