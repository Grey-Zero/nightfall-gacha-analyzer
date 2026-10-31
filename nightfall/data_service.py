"""前端使用的只读抽卡数据服务。"""
from collections import defaultdict
from datetime import datetime, timezone
from .cards import get_card, get_featured_card_id, get_pool_name
from .database import DatabaseManager


GROUPS = (
    ("limited", "活动契约", 70),
    ("standard", "常驻契约", 70),
    ("selection", "遴选契约", 70),
)


def _format_date(timestamp_ms):
    value = datetime.fromtimestamp(
        timestamp_ms / 1000, timezone.utc).astimezone()
    return value.strftime("%Y-%m-%d %H:%M")


def _is_miss(group, pool_id, result_id):
    if group not in ("limited", "selection"):
        return False
    featured_id = get_featured_card_id(pool_id)
    return featured_id is not None and result_id != featured_id


def _build_group(group, label, cap, rows):
    rows = sorted(rows, key=lambda row: (row["timestamp_ms"], -row["position"]))
    events = []
    five_stars = []
    pity = 0
    for row in rows:
        pity += 1
        if row["rarity"] == 5:
            card = get_card(row["result_id"])
            five_stars.append({
                "card_name": card["name"],
                "character": card["character"],
            })
            continue
        if row["rarity"] != 6:
            continue
        card = get_card(row["result_id"])
        events.append({
            "pulls": min(pity, cap),
            "value": min(pity, cap),
            "actual_pulls": pity,
            "card_name": card["name"],
            "character": card["character"],
            "result_id": row["result_id"],
            "pool_id": row["pool_id"],
            "pool_name": get_pool_name(row["pool_id"]),
            "timestamp_ms": row["timestamp_ms"],
            "date": _format_date(row["timestamp_ms"]),
            "miss": _is_miss(group, row["pool_id"], row["result_id"]),
            "five_stars": five_stars,
        })
        five_stars = []
        pity = 0

    return {
        "id": group,
        "label": label,
        "cap": cap,
        "pulls": len(rows),
        "six_stars": len(events),
        "current_pity": min(pity, cap),
        "actual_current_pity": pity,
        "events": events,
    }


def _build_starter_group(group, rows):
    result = _build_group(group, "新手池", 30, rows)
    result["completed"] = result["pulls"] >= 30
    return result


def get_accounts(db_path="nightfall.db"):
    db = DatabaseManager(db_path)
    try:
        return db.get_all_accounts()
    finally:
        db.close()


def get_dashboard(account_id, db_path="nightfall.db"):
    db = DatabaseManager(db_path)
    try:
        rows = db.get_records(account_id)
        account = db.get_account(account_id)
        last_update = db.get_last_update(account_id)
    finally:
        db.close()
    if account is None:
        raise ValueError(f"Account {account_id} does not exist")

    grouped = defaultdict(list)
    for row in rows:
        grouped[row["pity_group"]].append(row)

    groups = []
    for group, label, cap in GROUPS:
        groups.append(_build_group(group, label, cap, grouped[group]))

    for group in sorted(grouped):
        if group.startswith("starter:"):
            groups.append(_build_starter_group(group, grouped[group]))

    six_stars = [
        event
        for group in groups
        for event in group["events"]
    ]
    featured_events = [
        event
        for event in six_stars
        if 20002 <= event["pool_id"] < 40000
        and get_featured_card_id(event["pool_id"]) is not None
    ]
    misses = sum(event["miss"] for event in featured_events)

    return {
        "account": account,
        "groups": groups,
        "total_records": len(rows),
        "total_six_stars": len(six_stars),
        "featured_six_stars": len(featured_events),
        "missed_six_stars": misses,
        "on_rate": (
            (len(featured_events) - misses) / len(featured_events)
            if featured_events else None
        ),
        "last_import": _build_last_import(last_update),
    }


def _build_last_import(last_update):
    if not last_update:
        return None
    update_time = last_update["update_time"]
    try:
        display = datetime.fromisoformat(
            update_time.replace("Z", "+00:00")).astimezone().strftime(
                "%Y-%m-%d %H:%M")
    except ValueError:
        display = update_time
    return {
        "update_time": update_time,
        "display_time": display,
        "records_added": last_update["records_added"],
    }


def get_export_data(account_id, db_path="nightfall.db"):
    db = DatabaseManager(db_path)
    try:
        account = db.get_account(account_id)
        if account is None:
            raise ValueError(f"Account {account_id} does not exist")
        records = db.get_records(account_id)
    finally:
        db.close()
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": account,
        "total_records": len(records),
        "records": records,
    }
