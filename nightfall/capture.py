#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抓包录制与解析（TShark 写文件，事后解析，避免实时处理丢包）"""
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .network import find_tshark


# 读取 TCP 段需要的字段，顺序与 read_tcp_segments 的解包顺序对应
SEGMENT_FIELDS = (
    "tcp.stream",
    "ip.src",
    "tcp.srcport",
    "ip.dst",
    "tcp.dstport",
    "ipv6.src",
    "ipv6.dst",
    "tcp.seq",
    "tcp.payload",
)

TCP_SEQ_MASK = 0xFFFFFFFF
TCP_SEQ_HALF = 0x7FFFFFFF


def _join_segments(segments):
    """把 {seq: payload} 拼成连续字节流

    重传段按序号去重（保留首次收到的负载），乱序段按序号重排，
    序号跳变处计为空洞 —— 空洞意味着抓包丢了段，字节流已经断了。

    返回: (数据, 空洞数)
    """
    if not segments:
        return b"", 0

    base = next(iter(segments))
    rels = [((seq - base) & TCP_SEQ_MASK) for seq in segments]
    # 序号回绕或首包不是最小段时，把落在基准之前的段折回负数区间
    if rels and max(rels) > TCP_SEQ_HALF:
        rels = [rel - 0x100000000 if rel > TCP_SEQ_HALF else rel for rel in rels]

    ordered = sorted(zip(rels, segments.values()), key=lambda item: item[0])

    out = bytearray()
    holes = 0
    expected = None
    for rel, payload in ordered:
        if expected is not None:
            if rel < expected:
                overlap = expected - rel
                if overlap >= len(payload):
                    continue
                payload = payload[overlap:]
                rel = expected
            elif rel > expected:
                holes += 1
        out += payload
        expected = rel + len(payload)

    return bytes(out), holes


def assemble_streams(segments, endpoints):
    """把 TCP 段重组成按流、按方向的字节流

    segments: [(stream_id, (src_ip, src_port), (dst_ip, dst_port), seq, payload)]

    返回: [{"stream", "client", "server", "incomplete", "holes"}, ...]
    """
    server_set = set(endpoints)
    collected = {}

    for stream_id, src, dst, seq, payload in segments:
        if src in server_set:
            direction = "server"
        elif dst in server_set:
            direction = "client"
        else:
            continue
        buckets = collected.setdefault(
            stream_id, {"client": {}, "server": {}})
        # 同一序号重复出现就是重传，保留首次收到的负载
        buckets[direction].setdefault(seq, payload)

    streams = []
    for stream_id in sorted(collected):
        item = {
            "stream": stream_id,
            "client": b"",
            "server": b"",
            "incomplete": False,
            "holes": 0,
        }
        for direction in ("client", "server"):
            data, holes = _join_segments(collected[stream_id][direction])
            item[direction] = data
            item["holes"] += holes
            if holes:
                item["incomplete"] = True
        streams.append(item)

    return streams


def read_tcp_segments(tshark_path, pcap_path):
    """用 TShark 逐行读取带负载的 TCP 段

    直接取字段而不是走 PDML，大抓包时更快，也不会把整个文件读进内存
    """
    cmd = [
        str(tshark_path),
        "-r", str(pcap_path),
        "-n",
        "-Y", "tcp.len > 0",
        "-T", "fields",
        "-E", "separator=\t",
        "-E", "occurrence=f",
    ]
    for field in SEGMENT_FIELDS:
        cmd.extend(("-e", field))

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )

    try:
        for raw_line in process.stdout:
            parts = raw_line.decode("utf-8", "replace").rstrip("\r\n").split("\t")
            if len(parts) != len(SEGMENT_FIELDS):
                continue
            (stream_id, src_ip, src_port, dst_ip, dst_port,
             src_v6, dst_v6, seq, payload) = parts
            src_ip = src_ip or src_v6
            dst_ip = dst_ip or dst_v6
            if not (stream_id and src_ip and dst_ip and seq and payload):
                continue
            try:
                yield (
                    int(stream_id),
                    (src_ip, int(src_port)),
                    (dst_ip, int(dst_port)),
                    int(seq),
                    bytes.fromhex(payload.replace(":", "")),
                )
            except ValueError:
                continue
    finally:
        process.stdout.close()
        process.wait()


class PacketCapture:
    def __init__(self, endpoints, interface="WLAN", tshark_path=None):
        """endpoints: [(ip, port), ...] 全部候选服务器端点"""
        self.endpoints = [tuple(e) for e in endpoints]
        self.interface = interface
        self.tshark_process = None
        self.pcap_path = None

        self.tshark_path = tshark_path or find_tshark()
        if not self.tshark_path:
            raise FileNotFoundError(
                "找不到 TShark，请安装 Wireshark 或放到项目 tshark/ 目录")

    def _capture_filter(self):
        """BPF 捕获过滤器，涵盖所有候选端点"""
        parts = [f"(host {ip} and tcp port {port})" for ip, port in self.endpoints]
        return " or ".join(parts)

    def start_recording(self):
        """启动录制，双向抓包（需要客户端请求来判断查询条件）"""
        tmp = tempfile.NamedTemporaryFile(suffix=".pcap", delete=False)
        self.pcap_path = tmp.name
        tmp.close()

        cmd = [
            self.tshark_path,
            "-i", self.interface,
            "-B", "256",                    # 大型全量采集需要更大的内核缓冲区
            "-f", self._capture_filter(),
            "-w", self.pcap_path,
        ]

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.tshark_process = subprocess.Popen(
            cmd,
            cwd=str(Path(self.tshark_path).parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )

        # 过滤器语法错误或权限不足会立刻退出，早点暴露
        time.sleep(1.0)
        if self.tshark_process.poll() is not None:
            stderr = self.tshark_process.stderr.read().decode("utf-8", "replace")
            raise RuntimeError(f"TShark 启动失败:\n{stderr.strip()}")

        return self.pcap_path

    def is_recording(self):
        return self.tshark_process is not None and self.tshark_process.poll() is None

    def get_captured_size(self):
        """已录制字节数

        tshark 写文件带缓冲，这个值只能粗略判断有无流量，
        不能反映实时帧数或页数
        """
        if not self.pcap_path:
            return 0
        try:
            return Path(self.pcap_path).stat().st_size
        except OSError:
            return 0

    def stop_recording(self):
        """停止录制"""
        if not self.tshark_process:
            return

        self.tshark_process.terminate()
        try:
            self.tshark_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.tshark_process.kill()
            self.tshark_process.wait(timeout=3)

        self.tshark_process = None
        time.sleep(0.3)     # 等文件系统刷完缓冲

    def parse_pcap(self, pcap_path=None):
        """解析 pcap，按 TCP 流和方向分别重组

        每条流独立重组：不同连接的字节拼在一起会让帧解析错位，
        断线重连产生的新流同样需要隔离。

        按 TCP 序号去重和排序，不能按包到达顺序直接拼接：
        抓大段记录时会出现重传和乱序，直接拼接会让后续帧头全部错位。

        返回: [{"stream", "client", "server", "incomplete", "holes"}, ...]
        """
        pcap_path = pcap_path or self.pcap_path
        if not pcap_path or not Path(pcap_path).exists():
            return []

        segments = read_tcp_segments(self.tshark_path, pcap_path)
        return assemble_streams(segments, self.endpoints)

    def preserve(self, target_dir):
        """把本次抓包另存一份用于排查，返回文件路径"""
        if not self.pcap_path or not Path(self.pcap_path).exists():
            return None

        target_dir = Path(target_dir)
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / time.strftime("capture-%Y%m%d-%H%M%S.pcap")
            shutil.copy2(self.pcap_path, target)
        except OSError:
            return None
        return str(target)

    def cleanup(self):
        """删除临时 pcap"""
        if self.pcap_path:
            try:
                Path(self.pcap_path).unlink(missing_ok=True)
            except OSError:
                pass
            self.pcap_path = None
