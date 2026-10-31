import unittest
from collections import deque
from unittest.mock import patch

from nightfall.gacha import (
    build_request_index,
    collect_query0_pages,
)


class GachaPageConsistencyTests(unittest.TestCase):
    def test_reused_seq_is_matched_in_request_order(self):
        with patch(
            "nightfall.gacha.parse_c08_request",
            side_effect=[
                (62, 0, 0),
                (62, 0, 1225),
            ],
        ):
            requests, failed = build_request_index([b"first", b"second"])

        page_zero = [(30008, 13001039, 1000)]
        page_1225 = [(30008, 13001044, 2000)]
        with patch(
            "nightfall.gacha.parse_c08_response",
            side_effect=[
                (0, 1226, page_zero),
                (1225, 1226, page_1225),
            ],
        ):
            pages, stats = collect_query0_pages(
                [(62, b"first-response", 0), (62, b"second-response", 0)],
                requests,
            )

        self.assertEqual(failed, 0)
        self.assertEqual(pages, {0: page_zero, 1225: page_1225})

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

    def test_response_offset_mismatch_is_skipped(self):
        with patch(
            "nightfall.gacha.parse_c08_response",
            return_value=(10, 11, [(30008, 13001039, 1000)]),
        ):
            pages, stats = collect_query0_pages(
                [(1, b"wrong-offset", 0)],
                {1: (0, 0)},
            )

        self.assertEqual(pages, {})
        self.assertEqual(stats["offset_mismatch"], 1)

    def test_all_records_request_wins_over_same_offset_single_pool_request(self):
        with patch(
            "nightfall.gacha.parse_c08_response",
            return_value=(5, 6, [(30008, 13001039, 1000)]),
        ):
            pages, stats = collect_query0_pages(
                [(1, b"all-records", 0)],
                {1: deque([(30008, 5), (0, 5)])},
            )

        self.assertEqual(sorted(pages), [5])
        self.assertEqual(stats["total"], 6)

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
