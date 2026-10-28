#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""夜幕之下协议解析"""
import struct
import lz4.block

CMD_GACHA_HISTORY = 0x0C08

# 记录已报告过的未知字段，避免刷屏
_reported_unknown_fields = set()


def parse_varint(data, offset=0):
    """解析 protobuf varint，返回 (值, 新偏移)"""
    result = 0
    shift = 0
    while offset < len(data):
        b = data[offset]
        result |= (b & 0x7F) << shift
        offset += 1
        if b < 0x80:
            break
        shift += 7
    return result, offset


def parse_wire_field(data, offset=0):
    """解析单个 protobuf 字段，返回 (字段号, wire type, 值, 新偏移)"""
    if offset >= len(data):
        return None

    tag, offset = parse_varint(data, offset)
    field_num = tag >> 3
    wire_type = tag & 0x07

    if wire_type == 0:
        value, offset = parse_varint(data, offset)
    elif wire_type == 2:
        length, offset = parse_varint(data, offset)
        if offset + length > len(data):
            raise ValueError("长度前缀越界")
        value = data[offset:offset + length]
        offset += length
    elif wire_type == 5:
        if offset + 4 > len(data):
            raise ValueError("fixed32 越界")
        value = data[offset:offset + 4]
        offset += 4
    elif wire_type == 1:
        if offset + 8 > len(data):
            raise ValueError("fixed64 越界")
        value = data[offset:offset + 8]
        offset += 8
    else:
        raise ValueError(f"不支持的 wire type {wire_type}")

    return field_num, wire_type, value, offset


def parse_server_frame(data):
    """解析服务器→客户端的帧

    帧布局: [0:4]长度  [4:7]cmd  [7]flag  [8:11]seq  [11]ctr  [12:]body

    返回: (cmd, seq, ctr, body_raw, flag, frame_size)
    """
    if len(data) < 12:
        return None

    frame_len = struct.unpack(">I", data[0:4])[0]
    if frame_len < 8 or len(data) < 4 + frame_len:
        return None

    cmd = int.from_bytes(data[4:7], 'big')
    flag = data[7]
    seq = int.from_bytes(data[8:11], 'big')
    ctr = data[11]
    body_raw = data[12:4 + frame_len]

    return cmd, seq, ctr, body_raw, flag, 4 + frame_len


def parse_client_frame(data):
    """解析客户端→服务器的帧

    帧布局与服务端不同构: [0:4]长度  [4:8]?  [8:11]cmd  [11]flag  [12:]body
    body 开头是 varint 编码的 seq（见 parse_c08_request）

    返回: (cmd, flag, body_raw, frame_size)
    """
    if len(data) < 12:
        return None

    frame_len = struct.unpack(">I", data[0:4])[0]
    if frame_len < 8 or len(data) < 4 + frame_len:
        return None

    cmd = int.from_bytes(data[8:11], 'big')
    flag = data[11]
    body_raw = data[12:4 + frame_len]

    return cmd, flag, body_raw, 4 + frame_len


def decompress_lz4_tolerant(data):
    """容错 LZ4 解压（跳过可变长度的 varint 前缀）"""
    offset = 0
    while offset < len(data) and offset < 5:
        if data[offset] < 0x80:
            offset += 1
            break
        offset += 1

    for start in range(offset, min(offset + 10, len(data))):
        try:
            return lz4.block.decompress(data[start:], uncompressed_size=1024 * 1024)
        except Exception:
            continue

    raise ValueError("无法解压 LZ4 数据")


def parse_c08_request(body):
    """解析 0xc08 抽卡历史请求

    body 布局:
        varint          seq，与服务端响应帧头的 seq 对应，用于配对
        field 1 varint  pool_filter，0 表示「全部记录」，其余为指定卡池
        field 2 varint  req_offset，请求的起始位置

    返回: (seq, pool_filter, req_offset)，解析失败返回 None
    """
    if not body:
        return None

    try:
        seq, pos = parse_varint(body, 0)

        pool_filter = None
        req_offset = None

        while pos < len(body):
            result = parse_wire_field(body, pos)
            if not result:
                break
            field_num, wire_type, value, pos = result

            if field_num == 1 and wire_type == 0:
                pool_filter = value
            elif field_num == 2 and wire_type == 0:
                req_offset = value

        return seq, pool_filter, req_offset

    except Exception:
        return None


def parse_c08_response(body):
    """解析 0xc08 抽卡历史响应

    body 布局:
        field 1 varint    offset，本次查询结果的起始位置
        field 2 varint    total，本次查询条件下的记录总数
        field 3 repeated  records
            field 1 varint  pool_id
            field 2 varint  result_id
            field 3 varint  timestamp_ms

    返回: (offset, total, records)
          records 保持服务器返回的原始顺序，不排序不去重
    """
    offset_val = None
    total = None
    records = []

    off = 0
    while off < len(body):
        result = parse_wire_field(body, off)
        if not result:
            break
        field_num, wire_type, value, off = result

        if field_num == 1 and wire_type == 0:
            offset_val = value
        elif field_num == 2 and wire_type == 0:
            total = value
        elif field_num == 3 and wire_type == 2:
            rec_off = 0
            pool_id = result_id = timestamp_ms = None
            while rec_off < len(value):
                rec_result = parse_wire_field(value, rec_off)
                if not rec_result:
                    break
                f, wt, v, rec_off = rec_result
                if f == 1:
                    pool_id = v
                elif f == 2:
                    result_id = v
                elif f == 3:
                    timestamp_ms = v
                else:
                    _reported_unknown_fields.add(f)

            if pool_id and result_id and timestamp_ms:
                records.append((pool_id, result_id, timestamp_ms))

    return offset_val, total, records
