#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""网络连接检测"""
import re
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import psutil

from .config import load_config, save_config

GAME_PROCESS = "ReignofNightfall.exe"

# 排除明显不是游戏主连接的端口（HTTP/HTTPS 类接口）
EXCLUDED_PORTS = {80, 443, 8080, 8443}


def find_game_process(process_name=GAME_PROCESS):
    """查找游戏进程"""
    for proc in psutil.process_iter(['pid', 'name']):
        if proc.info['name'] == process_name:
            return proc
    return None


def detect_game_connections(process_name=GAME_PROCESS):
    """检测游戏进程的所有候选连接

    游戏会同时连接多个服务（登录、网关、公告等），无法从连接信息本身
    判断哪条承载抽卡协议。这里返回全部候选，由抓包解析阶段筛选。

    返回 None 表示进程未运行或无可用连接；否则:
        {"pid": int, "interface": str, "endpoints": [(ip, port), ...]}
    """
    proc = find_game_process(process_name)
    if not proc:
        return None

    try:
        connections = proc.net_connections(kind='inet')
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return None

    endpoints = []
    local_ips = []

    for conn in connections:
        if conn.status != psutil.CONN_ESTABLISHED or not conn.raddr:
            continue

        ip, port = conn.raddr.ip, conn.raddr.port

        if ip.startswith('127.') or ip == '::1':
            continue
        if port in EXCLUDED_PORTS:
            continue

        if (ip, port) not in endpoints:
            endpoints.append((ip, port))
            if conn.laddr:
                local_ips.append(conn.laddr.ip)

    if not endpoints:
        return None

    interface = None
    for local_ip in local_ips:
        interface = get_interface_by_ip(local_ip)
        if interface:
            break

    return {
        "pid": proc.pid,
        "interface": interface or "WLAN",
        "endpoints": endpoints,
    }


def get_interface_by_ip(local_ip):
    """根据本地 IP 找到网络接口，返回 TShark 可用的名称"""
    for interface, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family == socket.AF_INET and addr.address == local_ip:
                return map_interface_name(interface)
    return None


def find_tshark():
    """查找 TShark，优先项目内捆绑版本"""
    project_tshark = Path(__file__).parent.parent / "tshark" / "tshark.exe"
    if project_tshark.exists():
        return str(project_tshark)

    for path in (r"C:\Program Files\Wireshark\tshark.exe",
                 r"C:\Program Files (x86)\Wireshark\tshark.exe"):
        if Path(path).exists():
            return path

    return None


def map_interface_name(friendly_name):
    """把 Windows 适配器名映射成 TShark 接口名

    tshark -D 输出形如:
        1. \\Device\\NPF_{GUID} (Wi-Fi)
    优先返回 \\Device\\NPF_{GUID} 形式 —— 这个 TShark 一定认，
    而友好名称在某些系统语言环境下会失配
    """
    tshark_path = find_tshark()
    if not tshark_path:
        return friendly_name

    try:
        output = subprocess.run(
            [tshark_path, "-D"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return friendly_name

    pattern = re.compile(r"^\s*\d+\.\s+(\S+)\s+\((.+)\)\s*$")

    for line in output.splitlines():
        match = pattern.match(line)
        if match and match.group(2).strip() == friendly_name:
            return match.group(1)

    return friendly_name


def get_game_connection(process_name=GAME_PROCESS):
    """获取游戏连接，结果缓存到配置

    返回: {"interface": str, "endpoints": [[ip, port], ...], "pid": int}
    """
    result = detect_game_connections(process_name)

    if not result:
        config = load_config()
        cached = config.get("game_connection")
        if cached:
            print(f"[!] 未检测到活动连接，使用缓存: "
                  f"{len(cached.get('endpoints', []))} 个端点")
            return cached
        raise RuntimeError(
            f"未找到游戏进程 {process_name} 或其网络连接\n\n"
            f"请确保游戏已启动并登录。"
        )

    print(f"[✓] 游戏进程 PID {result['pid']}，接口 {result['interface']}")
    for ip, port in result["endpoints"]:
        print(f"    候选连接 {ip}:{port}")

    config = load_config()
    config["game_connection"] = {
        "interface": result["interface"],
        "endpoints": [list(e) for e in result["endpoints"]],
        "detected_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    save_config(config)

    return result
