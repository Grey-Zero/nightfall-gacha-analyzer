#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抽卡记录提取：请求响应配对、只保留「全部记录」查询、展开分页"""
from collections import Counter

from .protocol import (
    CMD_GACHA_HISTORY,
    parse_client_frame,
    parse_server_frame,
    parse_c08_request,
    parse_c08_response,
    decompress_lz4_tolerant,
)

# pool_filter == 0 表示「全部记录」，是我们唯一采用的查询
QUERY_ALL = 0


def _merge_page(pages, offset, records, stats):
    existing = pages.get(offset)
    if existing is not None:
        if existing != records:
            raise ValueError(
                f"同一抽卡记录 offset={offset} 返回了不同内容；"
                "可能采集期间记录列表发生变化。本次未导入，请重新完整采集。"
            )
        stats["duplicate_pages"] += 1
        return
    pages[offset] = records


def split_frames(client_stream, server_stream):
    """从两个方向的 TCP 流中提取帧

    客户端和服务端帧头不同构，必须分别解析

    返回: (client_c08_bodies, server_c08_frames)
           client_c08_bodies = [body, ...]
           server_c08_frames = [(seq, body_raw, flag), ...]
    """
    client_bodies = []
    buf = bytes(client_stream)
    pos = 0
    while pos < len(buf):
        result = parse_client_frame(buf[pos:])
        if not result:
            pos += 1
            continue
        cmd, flag, body_raw, frame_size = result
        if cmd == CMD_GACHA_HISTORY:
            client_bodies.append(body_raw)
        pos += frame_size

    server_frames = []
    buf = bytes(server_stream)
    pos = 0
    while pos < len(buf):
        result = parse_server_frame(buf[pos:])
        if not result:
            pos += 1
            continue
        cmd, seq, ctr, body_raw, flag, frame_size = result
        if cmd == CMD_GACHA_HISTORY:
            server_frames.append((seq, body_raw, flag))
        pos += frame_size

    return client_bodies, server_frames


def build_request_index(client_bodies):
    """建立 seq → (pool_filter, req_offset) 索引

    返回: ({seq: (pool_filter, req_offset)}, 解析失败数)
    """
    requests = {}
    failed = 0

    for body in client_bodies:
        parsed = parse_c08_request(body)
        if not parsed:
            failed += 1
            continue
        seq, pool_filter, req_offset = parsed
        if pool_filter is None:
            failed += 1
            continue
        # seq 重复时后者覆盖前者（同一 seq 不应对应不同查询）
        requests[seq] = (pool_filter, req_offset)

    return requests, failed


def collect_query0_pages(server_frames, requests):
    """收集「全部记录」查询的分页数据

    dict 的 key 天然完成页级去重：同一页被重复抓到只保留一份。
    命名空间收窄到单一查询后，offset 语义唯一，无需任何内容去重 ——
    同一毫秒的两张相同卡在一页里出现两次，就是两条真实记录。

    返回: ({offset: records}, stats)
    """
    pages = {}
    stats = Counter()

    for seq, body_raw, flag in server_frames:
        stats['responses'] += 1

        if flag == 1:
            try:
                body = decompress_lz4_tolerant(body_raw)
            except Exception:
                stats['decompress_failed'] += 1
                continue
        else:
            body = body_raw

        try:
            offset, total, records = parse_c08_response(body)
        except Exception:
            stats['parse_failed'] += 1
            continue

        # offset/total 缺失说明是 TCP 重组错帧
        if offset is None or total is None or not records:
            stats['bad_frames'] += 1
            continue

        request = requests.get(seq)

        if request is None:
            # 配不上请求：请求发生在录制开始之前，或 seq 解析有误
            stats['unpaired'] += 1
            continue

        pool_filter, requested_offset = request
        if pool_filter != QUERY_ALL:
            # 单池筛选查询，不采用
            stats['single_pool'] += 1
            continue

        if requested_offset is not None and offset != requested_offset:
            raise ValueError(
                f"抽卡历史请求 offset={requested_offset}，"
                f"响应却返回 offset={offset}（seq={seq}）；"
                "请求响应配对不一致，本次未导入。"
            )

        previous_total = stats.get('total')
        if previous_total is not None and previous_total != total:
            raise ValueError(
                f"采集期间服务器抽卡记录总数从 {previous_total} 变为 {total}；"
                "为避免混合不同版本的分页数据，本次未导入，请重新完整采集。"
            )

        _merge_page(pages, offset, records, stats)
        stats['total'] = total

    return pages, stats


def expand_pages(pages):
    """把分页数据展开成记录列表

    position = offset + 页内下标，是记录在「全部记录」结果中的绝对位置，
    在单一查询命名空间内唯一，可直接用作主键的一部分。

    返回: [(pool_id, result_id, timestamp_ms, position), ...] 按时间升序
    """
    records = []
    for offset in sorted(pages):
        for index, (pool_id, result_id, timestamp_ms) in enumerate(pages[offset]):
            records.append((pool_id, result_id, timestamp_ms, offset + index))

    records.sort(key=lambda r: (r[2], r[3]))
    return records


def find_gaps(pages):
    """检查 offset 覆盖是否连续，返回缺口列表 [(前一页offset, 下一页offset), ...]"""
    offsets = sorted(pages)
    gaps = []
    for a, b in zip(offsets, offsets[1:]):
        if b - a != len(pages[a]):
            gaps.append((a, b))
    return gaps


def extract_records(streams, verbose=False):
    """从多条 TCP 流中提取抽卡记录

    streams: [(client_stream, server_stream), ...]

    seq 是连接内计数，请求索引必须按流独立建立；
    但 query 0 的 offset 命名空间是全局的，页可以跨流合并

    返回: (records, stats)
           records = [(pool_id, result_id, timestamp_ms, position), ...]
    """
    pages = {}
    stats = Counter()
    server_total = 0

    for index, (client_stream, server_stream) in enumerate(streams):
        client_bodies, server_frames = split_frames(client_stream, server_stream)

        if not client_bodies and not server_frames:
            continue

        requests, req_failed = build_request_index(client_bodies)
        stream_pages, stream_stats = collect_query0_pages(server_frames, requests)

        stream_total = stream_stats.get('total', 0)
        if server_total and stream_total and server_total != stream_total:
            raise ValueError(
                f"不同 TCP 流报告的抽卡记录总数不一致："
                f"{server_total} 与 {stream_total}；本次未导入。"
            )

        for offset, records in stream_pages.items():
            _merge_page(pages, offset, records, stats)

        server_total = max(server_total, stream_total)
        stream_stats.pop('total', None)

        stats['requests'] += len(client_bodies)
        stats['request_parse_failed'] += req_failed
        stats.update(stream_stats)

    records = expand_pages(pages)
    gaps = find_gaps(pages)

    stats['total'] = server_total
    stats['pages'] = len(pages)
    stats['records'] = len(records)

    stats['gaps'] = gaps
    return records, stats
