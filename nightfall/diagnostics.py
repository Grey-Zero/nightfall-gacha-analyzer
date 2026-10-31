"""最近一次抓包的分析报告。

与采集时的即时诊断不同，这里直接读取已经保存的 pcap，重新做一遍
TCP 重组、协议配对和分页检查，输出可导出的 JSON 报告。报告只包含
分析所需的信息，不附带原始流量。
"""
import json
import platform
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .capture import assemble_streams_by_direction, read_tcp_segments
from .cards import get_card, get_pool_name
from .config import APP_VERSION, CAPTURES_DIR
from .gacha import (
    build_request_index,
    collect_query0_pages,
    expand_pages,
    find_gaps,
    split_frames,
)
from .network import find_tshark
from .pity import pity_group


CAPTURE_SUFFIXES = {".pcap", ".pcapng"}


def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _local_time(value):
    return value.astimezone().isoformat()


def _format_timestamp(timestamp_ms):
    if timestamp_ms is None:
        return None
    return datetime.fromtimestamp(
        timestamp_ms / 1000, timezone.utc).astimezone().strftime(
            "%Y-%m-%d %H:%M:%S")


def _is_elevated():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def find_latest_capture(captures_dir=None):
    """在 captures 目录下找最近修改的 pcap/pcapng 文件"""
    captures_dir = Path(captures_dir or CAPTURES_DIR)
    if not captures_dir.is_dir():
        return None

    candidates = [
        path for path in captures_dir.iterdir()
        if path.is_file() and path.suffix.lower() in CAPTURE_SUFFIXES
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def clear_capture_files(captures_dir=None):
    """删除保存的历史抓包及说明文件，返回删除数量与释放空间"""
    captures_dir = Path(captures_dir or CAPTURES_DIR)
    if not captures_dir.is_dir():
        return {"deleted": 0, "freed_bytes": 0}

    deleted = 0
    freed = 0
    for path in captures_dir.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() not in CAPTURE_SUFFIXES | {".json"}:
            continue
        try:
            size = path.stat().st_size
            path.unlink()
        except OSError:
            continue
        deleted += 1
        freed += size
    return {"deleted": deleted, "freed_bytes": freed}


def capture_storage_info(captures_dir=None):
    """已保存的历史抓包占用情况"""
    captures_dir = Path(captures_dir or CAPTURES_DIR)
    if not captures_dir.is_dir():
        return {"files": 0, "bytes": 0, "latest": None, "latest_modified": None}

    files = [
        path for path in captures_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() in CAPTURE_SUFFIXES | {".json"}
    ]
    total_bytes = 0
    for path in files:
        try:
            total_bytes += path.stat().st_size
        except OSError:
            continue

    captures = [
        path for path in files if path.suffix.lower() in CAPTURE_SUFFIXES
    ]
    latest = None
    latest_modified = None
    if captures:
        latest_path = max(captures, key=lambda path: path.stat().st_mtime)
        latest = latest_path.name
        latest_modified = _local_time(
            datetime.fromtimestamp(latest_path.stat().st_mtime, timezone.utc))
    return {
        "files": len(files),
        "bytes": total_bytes,
        "latest": latest,
        "latest_modified": latest_modified,
    }


def _read_sidecar(capture_path):
    sidecar = capture_path.with_suffix(".json")
    if not sidecar.is_file():
        return None
    try:
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return metadata if isinstance(metadata, dict) else None


def _endpoints_from_metadata(metadata):
    endpoints = set()
    for endpoint in (metadata or {}).get("endpoints") or ():
        try:
            ip, port = endpoint
            endpoints.add((str(ip), int(port)))
        except (TypeError, ValueError):
            continue
    return endpoints


def _stat_dict(stats):
    result = {}
    for key, value in stats.items():
        if value is None or isinstance(value, (int, float, str, bool)):
            result[key] = value
        elif isinstance(value, (list, tuple)):
            result[key] = [
                list(item) if isinstance(item, (list, tuple)) else item
                for item in value
            ]
        else:
            result[key] = str(value)
    result.pop("total", None)
    return result


def _score_orientation(client, server):
    """尝试把两个方向分别当作客户端/服务端，返回配对质量"""
    client_bodies, server_frames = split_frames(
        client["data"], server["data"])
    requests, request_parse_failed = build_request_index(client_bodies)
    request_count = sum(len(queue) for queue in requests.values())
    return {
        "score": (
            len(server_frames) * 3
            + request_count * 2
            + len(client_bodies)
        ),
        "client": client,
        "server": server,
        "client_bodies": client_bodies,
        "server_frames": server_frames,
        "requests": requests,
        "request_count": request_count,
        "request_parse_failed": request_parse_failed,
    }


def _choose_orientation(stream, server_endpoints):
    """确定一条 TCP 流中哪个方向是服务端

    有 sidecar 记录的端点时优先使用；否则根据帧头能否解析出
    抽卡协议来判断，这样用户手工保存的抓包也能分析。
    """
    directions = stream.get("directions") or []
    if len(directions) < 2:
        return None

    preferred_servers = [
        item for item in directions
        if (item["src"][0], item["src"][1]) in server_endpoints
        and (item["dst"][0], item["dst"][1]) not in server_endpoints
    ]

    pairs = []
    if preferred_servers:
        for server in preferred_servers:
            pairs.extend(
                (client, server) for client in directions if client is not server
            )
    if not pairs:
        pairs = [
            (client, server)
            for client in directions
            for server in directions
            if client is not server
        ]

    best = None
    for client, server in pairs:
        candidate = _score_orientation(client, server)
        if best is None or candidate["score"] > best["score"]:
            best = candidate
    if best is None or best["score"] <= 0:
        return None
    return best


def _analyze_stream(stream, server_endpoints):
    orientation = _choose_orientation(stream, server_endpoints)
    if orientation is None:
        return None

    client = orientation["client"]
    server = orientation["server"]
    requests = orientation["requests"]
    try:
        pages, stats = collect_query0_pages(
            orientation["server_frames"], requests)
        error = None
    except ValueError as exc:
        pages, stats, error = {}, Counter(), str(exc)

    gaps = find_gaps(pages)
    stats_dict = _stat_dict(stats)
    return {
        "stream": stream["stream"],
        "client": f"{client['src'][0]}:{client['src'][1]}",
        "server": f"{server['src'][0]}:{server['src'][1]}",
        "client_bytes": len(client["data"]),
        "server_bytes": len(server["data"]),
        "holes": client["holes"] + server["holes"],
        "incomplete": bool(client["holes"] or server["holes"]),
        "client_c08_frames": len(orientation["client_bodies"]),
        "server_c08_frames": len(orientation["server_frames"]),
        "requests": orientation["request_count"],
        "request_parse_failed": orientation["request_parse_failed"],
        "responses": int(stats.get("responses", 0)),
        "pages": len(pages),
        "records": sum(len(page) for page in pages.values()),
        "server_total": int(stats.get("total", 0)),
        "gaps": [[int(start), int(end)] for start, end in gaps],
        "stats": stats_dict,
        "error": error,
        "_pages": pages,
    }


def _record_entry(row):
    pool_id, result_id, timestamp_ms, position = row
    card = get_card(result_id)
    return {
        "pool_id": pool_id,
        "pool_name": get_pool_name(pool_id),
        "result_id": result_id,
        "card_name": card.get("name"),
        "character": card.get("character"),
        "rarity": card.get("rarity"),
        "pity_group": pity_group(pool_id),
        "position": position,
        "timestamp_ms": timestamp_ms,
        "timestamp": _format_timestamp(timestamp_ms),
    }


def _record_summary(rows):
    by_pool = Counter()
    by_group = Counter()
    by_rarity = Counter()
    for pool_id, result_id, _, _ in rows:
        by_pool[pool_id] += 1
        by_group[pity_group(pool_id)] += 1
        rarity = get_card(result_id).get("rarity")
        by_rarity[str(rarity) if rarity is not None else "unknown"] += 1

    newest = [_record_entry(row) for row in reversed(rows[-10:])]
    return {
        "count": len(rows),
        "by_rarity": dict(sorted(by_rarity.items())),
        "by_pool": [
            {"pool_id": pool_id, "pool_name": get_pool_name(pool_id),
             "records": count}
            for pool_id, count in by_pool.most_common()
        ],
        "by_pity_group": [
            {"group": group, "records": count}
            for group, count in by_group.most_common()
        ],
        "earliest": _record_entry(rows[0]) if rows else None,
        "latest": _record_entry(rows[-1]) if rows else None,
        "newest_sample": newest,
    }


def _build_warnings(stream_reports, aggregate, totals, gaps,
                    server_total, covered_end, record_count,
                    conflicting_pages, incomplete_streams):
    warnings = []
    if not stream_reports:
        warnings.append(
            "抓包中没有找到抽卡协议帧：确认录制期间确实打开了"
            "「契约记录 → 全部记录」并翻动了列表。")
    if incomplete_streams:
        warnings.append(
            f"{incomplete_streams} 条 TCP 数据流存在丢包，字节流可能不完整。")
    if len(set(totals)) > 1:
        warnings.append(
            "不同数据流报告的服务器记录总数不一致："
            + "、".join(str(total) for total in sorted(set(totals))) + "。")
    if gaps:
        warning_gaps = "、".join(f"{start}-{end}" for start, end in gaps)
        warnings.append(f"分页 offset 不连续，缺少区间 {warning_gaps}。")
    if server_total and covered_end < server_total:
        warnings.append(
            f"只覆盖到第 {covered_end}/{server_total} 条，可能没有翻到最后一页。")
    if aggregate.get("unpaired"):
        warnings.append(
            f"{aggregate['unpaired']} 个响应没有找到对应请求，"
            "通常是录制开始前的请求或 seq 解析异常。")
    if aggregate.get("offset_mismatch"):
        warnings.append(
            f"{aggregate['offset_mismatch']} 个响应与请求的 offset 不一致。")
    if aggregate.get("bad_frames"):
        warnings.append(
            f"{aggregate['bad_frames']} 个响应帧不完整或缺少 offset/total。")
    if aggregate.get("decompress_failed"):
        warnings.append(
            f"{aggregate['decompress_failed']} 个响应解压失败。")
    if aggregate.get("parse_failed"):
        warnings.append(
            f"{aggregate['parse_failed']} 个响应体解析失败。")
    if aggregate.get("request_parse_failed"):
        warnings.append(
            f"{aggregate['request_parse_failed']} 个请求体解析失败。")
    if aggregate.get("single_pool"):
        warnings.append(
            f"包含 {aggregate['single_pool']} 个单池筛选响应，"
            "这类数据不会被导入。")
    if conflicting_pages:
        warnings.append(
            f"{conflicting_pages} 个 offset 在不同数据流中内容不一致。")
    if server_total and record_count != server_total:
        warnings.append(
            f"去重后的记录数为 {record_count}，服务器报告 {server_total}。")
    return warnings


def analyze_streams(streams, server_endpoints=(), metadata=None):
    """分析已重组的 TCP 流，返回不含文件信息的报告主体"""
    server_endpoints = set(server_endpoints)
    stream_reports = []
    pages = {}
    aggregate = Counter()
    totals = []
    duplicate_pages = 0
    conflicting_pages = 0
    incomplete_streams = 0
    total_requests = 0

    for stream in streams:
        report = _analyze_stream(stream, server_endpoints)
        if report is None:
            continue

        stream_pages = report.pop("_pages")
        for offset, page in stream_pages.items():
            existing = pages.get(offset)
            if existing is None:
                pages[offset] = page
            elif existing == page:
                duplicate_pages += 1
            else:
                conflicting_pages += 1

        for key, value in report["stats"].items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                aggregate[key] += value
        total_requests += report["requests"]
        aggregate["request_parse_failed"] += report["request_parse_failed"]
        if report["server_total"]:
            totals.append(report["server_total"])
        if report["incomplete"]:
            incomplete_streams += 1
        stream_reports.append(report)

    aggregate["duplicate_pages"] += duplicate_pages
    rows = expand_pages(pages)
    gaps = find_gaps(pages)
    server_total = max(totals) if totals else 0
    covered_end = (
        max(offset + len(page) for offset, page in pages.items())
        if pages else 0
    )

    summary = {
        "streams_with_gacha": len(stream_reports),
        "incomplete_streams": incomplete_streams,
        "requests": total_requests,
        "responses": aggregate.get("responses", 0),
        "pages": len(pages),
        "records": len(rows),
        "server_total": server_total,
        "covered_end": covered_end,
        "gaps": [[int(start), int(end)] for start, end in gaps],
        "stats": dict(sorted(aggregate.items())),
        "checks": {
            "page_continuous": not gaps,
            "covers_all_records": (
                covered_end >= server_total if server_total else None),
            "records_match_server_total": (
                len(rows) == server_total if server_total else None),
            "totals_consistent": len(set(totals)) <= 1,
            "conflicting_pages": conflicting_pages,
        },
    }

    page_map = [
        {
            "offset": int(offset),
            "records": len(page),
            "first_timestamp": (
                _format_timestamp(page[0][2]) if page else None),
            "last_timestamp": (
                _format_timestamp(page[-1][2]) if page else None),
        }
        for offset, page in sorted(pages.items())
    ]

    return {
        "summary": summary,
        "streams": stream_reports,
        "pages": page_map,
        "records": _record_summary(rows),
        "warnings": _build_warnings(
            stream_reports, aggregate, totals, gaps, server_total,
            covered_end, len(rows), conflicting_pages, incomplete_streams),
        "sidecar": metadata,
    }


def analyze_capture(capture_path):
    """解析指定 pcap/pcapng，返回可导出的诊断报告"""
    capture_path = Path(capture_path)
    if not capture_path.is_file():
        raise FileNotFoundError(f"抓包文件不存在：{capture_path}")

    tshark_path = find_tshark()
    if not tshark_path:
        raise RuntimeError(
            "找不到 TShark，无法分析抓包。请安装 Wireshark，"
            "或把 tshark 放到程序的 tshark/ 目录。")

    metadata = _read_sidecar(capture_path)
    server_endpoints = _endpoints_from_metadata(metadata)
    segments = list(read_tcp_segments(tshark_path, capture_path))
    streams = assemble_streams_by_direction(segments)

    report = analyze_streams(streams, server_endpoints, metadata)
    stat = capture_path.stat()
    report["generated_at"] = _utc_now()
    report["capture"] = {
        "file": str(capture_path),
        "name": capture_path.name,
        "size_bytes": stat.st_size,
        "modified_at": _local_time(
            datetime.fromtimestamp(stat.st_mtime, timezone.utc)),
        "segments": len(segments),
        "streams": len(streams),
        "endpoints_from_metadata": [
            {"ip": ip, "port": port}
            for ip, port in sorted(server_endpoints)
        ],
    }
    report["environment"] = _build_environment(tshark_path)
    report["has_capture_data"] = bool(report["streams"])
    return report


def _build_environment(tshark_path=None):
    return {
        "app_version": APP_VERSION,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "elevated": _is_elevated(),
        "tshark": tshark_path,
    }


def analyze_latest_capture(captures_dir=None):
    """分析 captures 目录下最近的一次抓包"""
    capture_path = find_latest_capture(captures_dir)
    if capture_path is None:
        raise FileNotFoundError(
            "还没有可分析的数据。请先在首页采集一次记录，"
            "或把 pcap/pcapng 文件放进 captures 目录。")
    return analyze_capture(capture_path)


def build_error_report(captures_dir=None, capture_state=None):
    """生成反馈用的错误信息报告

    没有历史抓包时仍然导出程序信息和最近一次采集结果，
    这样「等待游戏连接超时」这类错误也能提供有效线索。
    """
    try:
        report = analyze_latest_capture(captures_dir)
    except FileNotFoundError:
        report = {
            "generated_at": _utc_now(),
            "capture": None,
            "summary": None,
            "streams": [],
            "pages": [],
            "records": None,
            "sidecar": None,
            "has_capture_data": False,
            "environment": _build_environment(find_tshark()),
            "warnings": [
                "没有找到历史抓包文件，本报告只包含程序信息和"
                "最近一次采集的结果。",
            ],
        }
    if capture_state is not None:
        report["last_capture"] = capture_state
    return report
