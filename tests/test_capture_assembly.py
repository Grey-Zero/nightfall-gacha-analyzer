import unittest

from nightfall.capture import _join_segments, assemble_streams

SERVER = ("192.0.2.10", 9000)
CLIENT = ("192.0.2.20", 51000)


def segment(stream_id, src, dst, seq, payload):
    return (stream_id, src, dst, seq, payload)


class JoinSegmentsTests(unittest.TestCase):
    def test_retransmitted_segment_is_kept_once(self):
        segments = {
            100: b"abcd",
            104: b"efgh",
        }
        data, holes = _join_segments(segments)
        self.assertEqual(data, b"abcdefgh")
        self.assertEqual(holes, 0)

    def test_out_of_order_segments_are_sorted(self):
        segments = {}
        for seq, payload in ((108, b"ij"), (100, b"abcd"), (104, b"efgh")):
            segments[seq] = payload
        data, holes = _join_segments(segments)
        self.assertEqual(data, b"abcdefghij")
        self.assertEqual(holes, 0)

    def test_missing_segment_is_reported_as_hole(self):
        segments = {100: b"abcd", 200: b"efgh"}
        data, holes = _join_segments(segments)
        self.assertEqual(holes, 1)
        self.assertEqual(data, b"abcdefgh")

    def test_partial_retransmission_does_not_duplicate_bytes(self):
        segments = {100: b"abcdef", 104: b"efgh"}
        data, holes = _join_segments(segments)
        self.assertEqual(data, b"abcdefgh")
        self.assertEqual(holes, 0)

    def test_sequence_wrap_is_joined_in_order(self):
        segments = {0xFFFFFFFE: b"abcd", 2: b"efgh"}
        data, holes = _join_segments(segments)
        self.assertEqual(data, b"abcdefgh")
        self.assertEqual(holes, 0)


class AssembleStreamsTests(unittest.TestCase):
    def test_retransmission_in_capture_does_not_corrupt_stream(self):
        segments = [
            segment(0, CLIENT, SERVER, 100, b"abc"),
            segment(0, CLIENT, SERVER, 100, b"abc"),   # 重传
            segment(0, CLIENT, SERVER, 103, b"def"),
        ]
        streams = assemble_streams(segments, [SERVER])

        self.assertEqual(len(streams), 1)
        self.assertEqual(streams[0]["client"], b"abcdef")
        self.assertFalse(streams[0]["incomplete"])

    def test_direction_is_split_by_endpoint(self):
        segments = [
            segment(0, CLIENT, SERVER, 1, b"request"),
            segment(0, SERVER, CLIENT, 500, b"response"),
        ]
        streams = assemble_streams(segments, [SERVER])

        self.assertEqual(streams[0]["client"], b"request")
        self.assertEqual(streams[0]["server"], b"response")

    def test_lossy_stream_is_marked_incomplete(self):
        segments = [
            segment(0, SERVER, CLIENT, 500, b"first"),
            segment(0, SERVER, CLIENT, 900, b"second"),
        ]
        streams = assemble_streams(segments, [SERVER])

        self.assertTrue(streams[0]["incomplete"])
        self.assertEqual(streams[0]["holes"], 1)

    def test_unrelated_stream_is_ignored(self):
        segments = [segment(0, ("10.0.0.1", 1), ("10.0.0.2", 2), 1, b"x")]
        self.assertEqual(assemble_streams(segments, [SERVER]), [])


if __name__ == "__main__":
    unittest.main()
