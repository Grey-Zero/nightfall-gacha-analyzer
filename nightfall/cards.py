"""卡牌和卡池数据加载。

数据按优先级取：云端缓存（见 catalog.py）→ 打包内置副本。
缓存由启动时的刷新写入，内置副本保证断网或首次运行时也能分析。
"""
import json
from pathlib import Path

from . import catalog

_DATA_DIR = Path(__file__).parent.parent / "data"
_CARDS = None
_POOLS = None


def _read(name):
    """先读云端缓存，不可用时退回打包内置副本"""
    for directory in (catalog.cache_dir(), _DATA_DIR):
        try:
            data = json.loads((directory / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        problem = (
            catalog.validate_cards(data) if name == "cards.json"
            else catalog.validate_pools(data, list(load_cards().values()))
        )
        if problem is None:
            return data
    raise ValueError(f"{name} 不存在或内容不合法")


def reload():
    """丢弃缓存，下次读取时重新加载（云端卡表更新后调用）"""
    global _CARDS, _POOLS
    _CARDS = None
    _POOLS = None


def load_cards():
    global _CARDS
    if _CARDS is None:
        data = _read("cards.json")
        _CARDS = {card["id"]: card for card in data}
    return _CARDS


def load_pools():
    global _POOLS
    if _POOLS is None:
        data = _read("pools.json")
        _POOLS = {pool["id"]: pool for pool in data}
    return _POOLS


def get_pool(pool_id):
    """获取卡池元数据，未知卡池返回占位数据。"""
    pool = load_pools().get(pool_id)
    if pool:
        return pool
    return {"id": pool_id, "name": f"未知卡池 #{pool_id}"}


def get_featured_card_id(pool_id):
    """获取卡池的 UP 卡 ID；未配置时返回 None。"""
    return get_pool(pool_id).get("featured_card_id")

def get_card(result_id):
    """获取卡牌信息，未知卡返回占位数据"""
    cards = load_cards()
    if result_id in cards:
        return cards[result_id]
    return {
        "id": result_id,
        "name": f"未知卡牌 #{result_id}",
        "character": "?",
        "rarity": None
    }

def get_pool_name(pool_id):
    """获取卡池名称"""
    return get_pool(pool_id)["name"]
