#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抽卡历史捕获监听器"""
from .capture import PacketCapture
from .gacha import extract_records


class GachaMonitor:
    def __init__(self, endpoints, interface):
        self.capture = PacketCapture(endpoints, interface)
        self.stats = {}

    def start(self):
        return self.capture.start_recording()

    def get_captured_size(self):
        return self.capture.get_captured_size()

    def is_recording(self):
        return self.capture.is_recording()

    def stop(self):
        self.capture.stop_recording()

    def process(self):
        """解析录制数据

        返回: [(pool_id, result_id, timestamp_ms, position), ...]
        """
        streams = self.capture.parse_pcap()
        records, stats = extract_records(streams)
        self.stats = stats
        return records

    def cleanup(self):
        self.capture.cleanup()

    def get_page_count(self):
        return self.stats.get('pages', 0)

    def get_single_pool_count(self):
        """被忽略的单池查询数，用于提示用户走错入口"""
        return self.stats.get('single_pool', 0)

    def get_unpaired_count(self):
        """未配对响应数，偏高说明 seq 解析有问题"""
        return self.stats.get('unpaired', 0)

    def get_server_total(self):
        return self.stats.get('total', 0)

    def get_extract_stats(self):
        """返回本次解析统计，供采集界面诊断丢页或配对失败。"""
        return dict(self.stats)
