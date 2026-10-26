"""卡牌和卡池数据加载"""
import json
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_CARDS = None
_POOLS = None

def load_cards():
    global _CARDS
    if _CARDS is None:
        data = json.loads((_DATA_DIR / "cards.json").read_text(encoding="utf-8"))
        _CARDS = {card["id"]: card for card in data}
    return _CARDS

def load_pools():
    global _POOLS
    if _POOLS is None:
        data = json.loads((_DATA_DIR / "pools.json").read_text(encoding="utf-8"))
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
