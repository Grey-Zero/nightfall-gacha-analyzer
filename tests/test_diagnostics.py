import os
import tempfile
import unittest
from pathlib import Path

from nightfall.diagnostics import (
    analyze_streams,
    build_error_report,
    capture_storage_info,
    clear_capture_files,
    find_latest_capture,
)


SERVER = ("192.0.2.10", 9000)
CLIENT = ("192.0.2.20", 51000)


def varint(value):
    data = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            data.append(byte | 0x80)
        else:
            data.append(byte)
            return bytes(data)


def client_frame(seq, pool_filter, offset):
    body = varint(seq) + b"\x08" + varint(pool_filter) + b"\x10" + varint(offset)
    frame_len = len(body) + 8
    return (
        frame_len.to_bytes(4, "big")
        + b"\x00\x00\x00\x00"
        + (0x0C08).to_bytes(3, "big")
        + b"\x00"
        + body
    )


def server_frame(seq, offset, total, records):
    body = b"\x08" + varint(offset) + b"\x10" + varint(total)
    for pool_id, result_id, timestamp_ms in records:
        record = (
            b"\x08" + varint(pool_id)
            + b"\x10" + varint(result_id)
            + b"\x18" + varint(timestamp_ms)
        )
        body += b"\x1a" + varint(len(record)) + record
    frame_len = len(body) + 8
    return (
        frame_len.to_bytes(4, "big")
        + (0x0C08).to_bytes(3, "big")
        + b"\x00"
        + seq.to_bytes(3, "big")
        + b"\x00"
        + body
    )


def build_streams():
    page_zero = [(30008, 13001062, 2000), (30008, 13001001, 1000)]
    page_two = [(30008, 13001039, 3000)]
    client_data = (
        client_frame(1, 0, 0)
        + client_frame(2, 0, 2)
    )
    server_data = (
        server_frame(1, 0, 3, page_zero)
        + server_frame(2, 2, 3, page_two)
    )
    return [{
        "stream": 7,
        "directions": [
            # 故意先放服务端方向，验证方向判断不依赖顺序
            {"src": SERVER, "dst": CLIENT, "data": server_data, "holes": 0},
            {"src": CLIENT, "dst": SERVER, "data": client_data, "holes": 0},
        ],
    }]


class DiagnosticsTests(unittest.TestCase):
    def test_streams_are_oriented_and_pages_are_expanded(self):
        report = analyze_streams(build_streams())

        self.assertEqual(report["summary"]["records"], 3)
        self.assertEqual(report["summary"]["server_total"], 3)
        self.assertEqual(report["summary"]["pages"], 2)
        self.assertTrue(report["summary"]["checks"]["page_continuous"])
        self.assertTrue(report["summary"]["checks"]["covers_all_records"])
        self.assertEqual(report["warnings"], [])

        stream = report["streams"][0]
        self.assertEqual(stream["client"], "192.0.2.20:51000")
        self.assertEqual(stream["server"], "192.0.2.10:9000")
        self.assertEqual(stream["requests"], 2)
        self.assertEqual(stream["responses"], 2)

        records = report["records"]
        self.assertEqual(records["count"], 3)
        self.assertEqual(records["by_pity_group"][0]["group"], "limited")
        self.assertEqual(records["latest"]["result_id"], 13001039)

    def test_known_server_endpoint_orients_stream_correctly(self):
        report = analyze_streams(build_streams(), server_endpoints={SERVER})

        self.assertEqual(report["summary"]["records"], 3)
        self.assertEqual(report["streams"][0]["server"], "192.0.2.10:9000")

    def test_gap_is_reported(self):
        page_zero = [(30008, 13001062, 1000)]
        client_data = client_frame(1, 0, 0) + client_frame(2, 0, 5)
        server_data = (
            server_frame(1, 0, 6, page_zero)
            + server_frame(2, 5, 6, [(30008, 13001039, 2000)])
        )
        streams = [{
            "stream": 1,
            "directions": [
                {"src": CLIENT, "dst": SERVER, "data": client_data, "holes": 0},
                {"src": SERVER, "dst": CLIENT, "data": server_data, "holes": 0},
            ],
        }]

        report = analyze_streams(streams)

        self.assertFalse(report["summary"]["checks"]["page_continuous"])
        self.assertEqual(report["summary"]["gaps"], [[0, 5]])
        self.assertTrue(any("不连续" in warning for warning in report["warnings"]))

    def test_error_report_without_capture_still_includes_last_state(self):
        with tempfile.TemporaryDirectory() as directory:
            report = build_error_report(
                directory, {"status": "error", "error": "等待游戏连接超时"})

        self.assertIsNone(report["capture"])
        self.assertFalse(report["has_capture_data"])
        self.assertEqual(report["last_capture"]["error"], "等待游戏连接超时")
        self.assertTrue(report["environment"]["app_version"])
        self.assertTrue(report["warnings"])

    def test_latest_capture_prefers_newest_file(self):
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory) / "old.pcap"
            new = Path(directory) / "new.pcapng"
            old.write_bytes(b"old")
            new.write_bytes(b"new")
            os.utime(old, (1000, 1000))
            os.utime(new, (2000, 2000))

            self.assertEqual(find_latest_capture(directory), new)

    def test_storage_info_and_cleanup_only_touch_capture_files(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / "capture-1.pcap").write_bytes(b"a" * 100)
            (directory / "capture-1.json").write_text("{}", encoding="utf-8")
            (directory / "latest-capture.pcap").write_bytes(b"b" * 50)
            (directory / "notes.txt").write_text("keep", encoding="utf-8")

            info = capture_storage_info(directory)

            self.assertEqual(info["files"], 3)
            self.assertEqual(info["bytes"], 152)
            self.assertEqual(info["latest"], "latest-capture.pcap")

            result = clear_capture_files(directory)

            self.assertEqual(result["deleted"], 3)
            self.assertEqual(result["freed_bytes"], 152)
            self.assertEqual(
                sorted(path.name for path in directory.iterdir()),
                ["notes.txt"],
            )
            self.assertEqual(capture_storage_info(directory)["files"], 0)


if __name__ == "__main__":
    unittest.main()
