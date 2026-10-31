#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抓包录制与解析（TShark 写文件，事后解析，避免实时处理丢包）"""
import os
import subprocess
import tempfile
import time
from pathlib import Path

import pyshark

from .network import find_tshark


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
        断线重连产生的新流同样需要隔离

        返回: [(client_stream, server_stream), ...] 按流分组
        """
        import asyncio

        pcap_path = pcap_path or self.pcap_path
        if not pcap_path or not Path(pcap_path).exists():
            return []

        # pyshark 在 __del__ 里会用到 event loop，先备好一个
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        original_popen = None
        if os.name == "nt":
            original_popen = subprocess.Popen

            def popen_hidden(*args, **kwargs):
                kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
                return original_popen(*args, **kwargs)

            subprocess.Popen = popen_hidden

            if hasattr(asyncio, "create_subprocess_exec"):
                original_create_subprocess_exec = asyncio.create_subprocess_exec

                async def create_subprocess_exec_hidden(*args, **kwargs):
                    kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
                    return await original_create_subprocess_exec(*args, **kwargs)

                asyncio.create_subprocess_exec = create_subprocess_exec_hidden

        capture = pyshark.FileCapture(
            pcap_path, display_filter="tcp",
            tshark_path=self.tshark_path, keep_packets=False)

        server_set = set(self.endpoints)
        streams = {}        # {stream_id: {"client": bytearray, "server": bytearray}}
        packet_count = 0

        try:
            for packet in capture:
                if not hasattr(packet, "tcp") or not hasattr(packet.tcp, "payload"):
                    continue

                try:
                    stream_id = int(packet.tcp.stream)
                    src_ip = packet.ip.src
                    dst_ip = packet.ip.dst
                    src_port = int(packet.tcp.srcport)
                    dst_port = int(packet.tcp.dstport)
                    payload = bytes.fromhex(packet.tcp.payload.replace(":", ""))
                except (AttributeError, ValueError):
                    continue

                if (src_ip, src_port) in server_set:
                    direction = "server"
                elif (dst_ip, dst_port) in server_set:
                    direction = "client"
                else:
                    continue

                packet_count += 1
                if stream_id not in streams:
                    streams[stream_id] = {
                        "client": bytearray(), "server": bytearray()}
                streams[stream_id][direction] += payload
        finally:
            try:
                capture.close()
            except Exception:
                pass
            if os.name == "nt" and "original_create_subprocess_exec" in locals():
                asyncio.create_subprocess_exec = original_create_subprocess_exec
            if os.name == "nt" and original_popen is not None:
                subprocess.Popen = original_popen
            try:
                loop.close()
            except Exception:
                pass
            asyncio.set_event_loop(None)

        return [(d["client"], d["server"]) for _, d in sorted(streams.items())]

    def cleanup(self):
        """删除临时 pcap"""
        if self.pcap_path:
            try:
                Path(self.pcap_path).unlink(missing_ok=True)
            except OSError:
                pass
            self.pcap_path = None
