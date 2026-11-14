"""云端卡表与卡池表。

卡牌和卡池数据只有几 KB，放在仓库里随代码维护，程序启动时拉取一次，
新增卡牌就不必为了一张卡重发整个安装包。

读取顺序见 cards.py：本地缓存 → 云端。云端只在启动时刷新一次，
网络不可用时保持原样，分析照旧用缓存或打包内置副本。
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from . import config

NAMES = ("cards.json", "pools.json")

# 官方 raw 为主，jsDelivr 是国内更快的镜像；两个都失败就保持现状
REMOTE_BASES = (
    "https://raw.githubusercontent.com/Grey-Zero/nightfall-gacha-analyzer/main/data",
    "https://cdn.jsdelivr.net/gh/Grey-Zero/nightfall-gacha-analyzer@main/data",
)

REQUEST_TIMEOUT = 6
MAX_BYTES = 512 * 1024
RARITIES = (4, 5, 6)

_cache_dir = None


def cache_dir():
    """云端卡表的本地缓存目录"""
    global _cache_dir
    if _cache_dir is None:
        _cache_dir = config.DATA_ROOT / "catalog"
    return Path(_cache_dir)


def set_cache_dir(path):
    """测试用：把缓存目录指向临时目录"""
    global _cache_dir
    _cache_dir = Path(path)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_text(value):
    return isinstance(value, str) and value.strip() != ""


def validate_cards(data):
    """校验卡表，返回错误说明；没问题返回 None"""
    if not isinstance(data, list) or not data:
        return "卡表不是非空数组"
    seen = set()
    for card in data:
        if not isinstance(card, dict):
            return "卡表条目不是对象"
        if not _is_int(card.get("id")):
            return "卡牌 id 不是整数"
        if not _is_text(card.get("name")) or not _is_text(card.get("character")):
            return f"卡牌 {card['id']} 缺少名称或角色"
        if card.get("rarity") not in RARITIES:
            return f"卡牌 {card['id']} 的稀有度不是 4/5/6"
        if card["id"] in seen:
            return f"卡牌 {card['id']} 重复"
        seen.add(card["id"])
    return None


def validate_pools(data, cards=None):
    """校验卡池表；给了卡表时一并检查 UP 卡是否存在"""
    if not isinstance(data, list) or not data:
        return "卡池表不是非空数组"
    known = None if cards is None else {card["id"] for card in cards}
    seen = set()
    for pool in data:
        if not isinstance(pool, dict):
            return "卡池条目不是对象"
        if not _is_int(pool.get("id")):
            return "卡池 id 不是整数"
        if not _is_text(pool.get("name")):
            return f"卡池 {pool['id']} 缺少名称"
        featured = pool.get("featured_card_id")
        if featured is not None:
            if not _is_int(featured):
                return f"卡池 {pool['id']} 的 UP 卡不是整数"
            if known is not None and featured not in known:
                return f"卡池 {pool['id']} 的 UP 卡 {featured} 不在卡表里"
        if pool["id"] in seen:
            return f"卡池 {pool['id']} 重复"
        seen.add(pool["id"])
    return None


def _fetch(url, timeout):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"NightfallGachaAnalyzer/{config.APP_VERSION}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("响应超过大小上限")
    return json.loads(raw.decode("utf-8"))


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def refresh(timeout=REQUEST_TIMEOUT):
    """拉取并校验云端卡表和卡池表，全部通过才写入缓存

    返回 {"updated", "source", "error"}；失败时保留旧缓存不动。
    """
    last_error = "没有配置云端地址"
    for base in REMOTE_BASES:
        cards = pools = None
        try:
            cards = _fetch(f"{base}/cards.json", timeout)
            pools = _fetch(f"{base}/pools.json", timeout)
        except (urllib.error.URLError, OSError, ValueError) as error:
            last_error = f"暂时无法更新卡表（{error}）"
            continue

        problem = validate_cards(cards) or validate_pools(pools, cards)
        if problem:
            last_error = f"云端卡表校验未通过：{problem}"
            continue

        try:
            _write(cache_dir() / "cards.json", cards)
            _write(cache_dir() / "pools.json", pools)
        except OSError as error:
            return {"updated": False, "source": base, "error": f"写入缓存失败（{error}）"}

        return {"updated": True, "source": base, "error": None}

    return {"updated": False, "source": None, "error": last_error}
