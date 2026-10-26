"""抽卡保底规则与分析"""

STANDARD_SIX_STARS = {
    13001009,
    13001012,
    13001025,
    13001027,
    13001035,
    13001036,
    13001039,
    13001052,
}

PITY_CAP_STARTER = 30
PITY_CAP_NORMAL = 70


def pity_group(pool_id):
    """确定保底继承组"""
    if 10000 <= pool_id <= 10099:
        return f"starter:{pool_id}"
    if pool_id == 20001:
        return "standard"
    if 20002 <= pool_id <= 29999:
        return "selection"
    if 30000 <= pool_id <= 39999:
        return "limited"
    return f"unknown:{pool_id}"


def count_pity(rows):
    """六星间隔：每次出六星时距上次六星的抽数，以及当前已垫抽数"""
    intervals = []
    pity = 0
    for row in rows:
        pity += 1
        if row["rarity"] == 6:
            intervals.append(pity)
            pity = 0
    return intervals, pity


def analyze_limited_guarantee(rows, observed_standard_six_stars=()):
    """推导限定池的小保底 / 大保底状态"""
    standard_ids = STANDARD_SIX_STARS | set(observed_standard_six_stars)

    guaranteed = False
    featured_hits = 0
    off_banner = 0
    anomalies = []

    for row in rows:
        if row["rarity"] != 6:
            continue

        if row["result_id"] in standard_ids:
            off_banner += 1
            if guaranteed:
                anomalies.append({
                    "result_id": row["result_id"],
                    "pool_id": row["pool_id"],
                    "reason": "处于大保底却歪出常驻六星",
                })
            guaranteed = True
        else:
            featured_hits += 1
            guaranteed = False

    return {
        "guaranteed": guaranteed,
        "featured_hits": featured_hits,
        "off_banner": off_banner,
        "anomalies": anomalies,
    }


def analyze_pity(records_by_group, observed_standard_six_stars=()):
    """根据按时间正序排列的保底组记录生成分析结果"""
    results = {}

    for group in ("standard", "selection", "limited"):
        rows = records_by_group.get(group, [])
        if not rows:
            continue

        intervals, pity = count_pity(rows)
        entry = {
            "pulls": len(rows),
            "current_pity": pity,
            "six_star_intervals": intervals,
            "cap": PITY_CAP_NORMAL,
            "completed": False,
        }

        if group == "limited":
            entry["guarantee"] = analyze_limited_guarantee(
                rows, observed_standard_six_stars)

        results[group] = entry

    for group_name, rows in records_by_group.items():
        if not group_name.startswith("starter:") or not rows:
            continue

        intervals, pity = count_pity(rows)
        pulls = len(rows)
        closed = pulls >= PITY_CAP_STARTER

        results[group_name] = {
            "pulls": pulls,
            "current_pity": 0 if closed else pity,
            "six_star_intervals": intervals,
            "cap": PITY_CAP_STARTER,
            "completed": closed,
        }

    return results
