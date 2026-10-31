#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抽卡记录数据库存取（支持多账号）"""
import sqlite3
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from .cards import get_card
from . import pity as _pity

# Preserve the rules exports historically available from this module.
PITY_CAP_NORMAL = _pity.PITY_CAP_NORMAL
PITY_CAP_STARTER = _pity.PITY_CAP_STARTER
STANDARD_SIX_STARS = _pity.STANDARD_SIX_STARS
pity_group = _pity.pity_group

def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_from_ms(timestamp_ms):
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc) \
                   .isoformat().replace("+00:00", "Z")


class DatabaseManager:
    def __init__(self, db_path="nightfall.db"):
        self.db_path = Path(db_path)
        self.conn = self._init_database()
        self.current_account_id = None
        self.last_position_shift = 0

    def _init_database(self):
        """初始化数据库（三张表）"""
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        # 账号表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                account_id INTEGER PRIMARY KEY AUTOINCREMENT,
                nickname TEXT NOT NULL UNIQUE,
                uid TEXT,
                note TEXT,
                created_at TEXT NOT NULL,
                last_active_at TEXT NOT NULL
            )
        """)

        # 记录表
        #
        # position 是记录在「全部记录」查询结果中的绝对位置（offset + 页内下标）。
        # 服务器返回的 offset=0 是最新一条，position 越大越早，
        # 因此按时间正序排列应为 timestamp_ms ASC, position DESC。
        #
        # position 单列即可唯一标识一条记录，主键里保留完整列组合是为了
        # 在 offset 解析出错时能通过冲突暴露问题，而不是静默写入脏数据。
        conn.execute("""
            CREATE TABLE IF NOT EXISTS records (
                account_id INTEGER NOT NULL,
                pool_id INTEGER NOT NULL,
                result_id INTEGER NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                position INTEGER NOT NULL,
                rarity INTEGER,
                name TEXT,
                character TEXT,
                pity_group TEXT,
                timestamp_utc TEXT,
                PRIMARY KEY (account_id, pool_id, result_id, timestamp_ms, position),
                FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
            )
        """)

        # 更新历史表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS updates (
                update_id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                update_time TEXT NOT NULL,
                records_added INTEGER NOT NULL,
                snapshot TEXT NOT NULL,
                FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
            )
        """)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_records_account "
                     "ON records(account_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_records_position "
                     "ON records(account_id, position)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_records_group "
                     "ON records(account_id, pity_group, timestamp_ms, position)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_updates_account "
                     "ON updates(account_id, update_time DESC)")

        self._migrate(conn)
        conn.commit()
        return conn

    @staticmethod
    def _migrate(conn):
        """为旧数据库补齐后续版本新增的列"""
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(accounts)")
        }
        if "note" not in columns:
            conn.execute("ALTER TABLE accounts ADD COLUMN note TEXT")

    # ==================== 账号管理 ====================

    def create_account(self, nickname, uid=None, note=None):
        """创建账号，返回 account_id"""
        now = _utc_now()
        try:
            cursor = self.conn.execute("""
                INSERT INTO accounts (nickname, uid, note, created_at, last_active_at)
                VALUES (?, ?, ?, ?, ?)
            """, (nickname, uid, note, now, now))
        except sqlite3.IntegrityError as error:
            raise ValueError("该昵称已被其他账号使用") from error
        self.conn.commit()
        return cursor.lastrowid

    def update_account(self, account_id, nickname, uid=None, note=None):
        """更新账号昵称、UID 和备注，返回是否存在该账号"""
        try:
            cursor = self.conn.execute("""
                UPDATE accounts
                SET nickname = ?, uid = ?, note = ?
                WHERE account_id = ?
            """, (nickname, uid, note, account_id))
        except sqlite3.IntegrityError as error:
            raise ValueError("该昵称已被其他账号使用") from error
        self.conn.commit()
        return cursor.rowcount > 0

    def get_all_accounts(self):
        """获取所有账号，按最近活跃排序"""
        cursor = self.conn.execute("""
            SELECT account_id, nickname, uid, note, created_at, last_active_at
            FROM accounts
            ORDER BY last_active_at DESC
        """)
        return [dict(row) for row in cursor.fetchall()]

    def get_account(self, account_id):
        """获取单个账号"""
        cursor = self.conn.execute(
            "SELECT * FROM accounts WHERE account_id = ?", (account_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def set_active_account(self, account_id):
        """设置当前活跃账号"""
        self.current_account_id = account_id
        self.conn.execute(
            "UPDATE accounts SET last_active_at = ? WHERE account_id = ?",
            (_utc_now(), account_id))
        self.conn.commit()

    def get_last_active_account(self):
        """获取最后活跃的账号 ID"""
        cursor = self.conn.execute(
            "SELECT account_id FROM accounts ORDER BY last_active_at DESC LIMIT 1")
        row = cursor.fetchone()
        return row[0] if row else None

    def delete_account(self, account_id):
        """删除账号（级联删除记录和更新历史），返回是否存在该账号"""
        cursor = self.conn.execute(
            "DELETE FROM accounts WHERE account_id = ?", (account_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    # ==================== 记录管理 ====================

    def insert_records(self, account_id, records):
        """插入记录，并识别新增记录导致的服务端位置整体偏移。

        records: [(pool_id, result_id, timestamp_ms, position), ...]
                 position 由抓包侧算出；较新的记录插到列表头部时，
                 已有记录的 position 会整体后移。

        返回: (新增数, 重复数, 新增记录列表)
        """
        records = list(records)
        self.last_position_shift = 0
        if not records:
            return 0, 0, []

        existing_rows = self.conn.execute("""
            SELECT pool_id, result_id, timestamp_ms, position
            FROM records WHERE account_id = ?
        """, (account_id,)).fetchall()
        existing_by_identity = defaultdict(list)
        for row in existing_rows:
            existing_by_identity[
                (row["pool_id"], row["result_id"], row["timestamp_ms"])
            ].append(row["position"])

        incoming_by_identity = defaultdict(list)
        for pool_id, result_id, timestamp_ms, position in records:
            incoming_by_identity[
                (pool_id, result_id, timestamp_ms)
            ].append(position)

        deltas = []
        for identity, incoming_positions in incoming_by_identity.items():
            old_positions = existing_by_identity.get(identity, [])
            if len(old_positions) == len(incoming_positions):
                deltas.extend(
                    new_position - old_position
                    for new_position, old_position in zip(
                        sorted(incoming_positions), sorted(old_positions))
                )

        position_shift = 0
        if deltas:
            delta_counts = Counter(deltas)
            candidate, agreement = delta_counts.most_common(1)[0]
            required_agreement = max(3, (len(deltas) * 4 + 4) // 5)
            if candidate > 0 and agreement >= required_agreement:
                position_shift = candidate

        remaining_existing = Counter(
            (row["pool_id"], row["result_id"], row["timestamp_ms"])
            for row in existing_rows
        )
        new_input = []
        for record in records:
            identity = record[:3]
            if remaining_existing[identity]:
                remaining_existing[identity] -= 1
            else:
                new_input.append(record)

        if position_shift and not new_input:
            position_shift = 0

        occupied_positions = {
            row["position"] + position_shift for row in existing_rows
        }
        collisions = [
            record[3] for record in new_input
            if record[3] in occupied_positions
        ]
        if collisions:
            if not position_shift and any(delta > 0 for delta in deltas):
                raise ValueError(
                    "检测到抽卡记录位置发生变化，但重叠记录不足以安全推算偏移；"
                    "本次没有导入，请重新采集「全部记录」后再试。"
                )
            raise ValueError(
                "新记录的位置与已有记录冲突；为避免重复统计，本次没有导入。"
            )

        inserted = 0
        new_records = []
        self.conn.execute("SAVEPOINT insert_records")
        try:
            if position_shift:
                self._shift_positions(account_id, position_shift)

            for pool_id, result_id, timestamp_ms, position in new_input:
                card = get_card(result_id)
                row = (
                    account_id,
                    pool_id,
                    result_id,
                    timestamp_ms,
                    position,
                    card.get("rarity"),
                    card.get("name"),
                    card.get("character"),
                    pity_group(pool_id),
                    _utc_from_ms(timestamp_ms),
                )
                try:
                    self.conn.execute(
                        "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        row,
                    )
                except sqlite3.IntegrityError:
                    continue
                inserted += 1
                new_records.append({
                    "pool_id": pool_id,
                    "result_id": result_id,
                    "timestamp_ms": timestamp_ms,
                    "position": position,
                })

            self.conn.execute("RELEASE SAVEPOINT insert_records")
            self.conn.commit()
        except Exception:
            self.conn.execute("ROLLBACK TO SAVEPOINT insert_records")
            self.conn.execute("RELEASE SAVEPOINT insert_records")
            self.conn.commit()
            self.last_position_shift = 0
            raise

        self.last_position_shift = position_shift
        return inserted, len(records) - inserted, new_records

    def _shift_positions(self, account_id, delta):
        if not delta:
            return
        row = self.conn.execute(
            "SELECT COALESCE(MAX(position), -1) FROM records WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        temporary_offset = max(0, row[0]) + abs(delta) + 1
        self.conn.execute(
            "UPDATE records SET position = position + ? WHERE account_id = ?",
            (temporary_offset, account_id),
        )
        self.conn.execute(
            "UPDATE records SET position = position - ? + ? WHERE account_id = ?",
            (temporary_offset, delta, account_id),
        )

    def get_record_count(self, account_id):
        """获取账号的总记录数"""
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM records WHERE account_id = ?", (account_id,))
        return cursor.fetchone()[0]

    def get_records(self, account_id, limit=None):
        """按时间正序取记录"""
        sql = """
            SELECT * FROM records
            WHERE account_id = ?
            ORDER BY timestamp_ms ASC, position DESC
        """
        params = [account_id]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)

        cursor = self.conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_position_range(self, account_id):
        """返回已覆盖的 position 区间和缺口数

        position 应该从 0 开始连续递增；重复 position 只计为一个位置。
        """
        cursor = self.conn.execute("""
            SELECT MIN(position), MAX(position), COUNT(DISTINCT position)
            FROM records WHERE account_id = ?
        """, (account_id,))
        lo, hi, count = cursor.fetchone()

        if lo is None:
            return {"min": None, "max": None, "count": 0, "missing": 0}

        return {
            "min": lo,
            "max": hi,
            "count": count,
            "missing": (hi - lo + 1) - count,
        }

    def verify_position_direction(self, account_id):
        """校验「position 越大时间越早」这个假设

        抓包侧假定服务器 offset=0 返回最新记录。如果假设不成立，
        保底分析的排序方向就是反的，间隔计算会出错。重复 position
        先合并成一个位置，避免同一位置的多条记录互相制造误报。

        返回: (是否一致, 违反次数, 不同 position 数)
        """
        cursor = self.conn.execute("""
            SELECT position, MIN(timestamp_ms), MAX(timestamp_ms)
            FROM records
            WHERE account_id = ?
            GROUP BY position
            ORDER BY position ASC
        """, (account_id,))
        positions = cursor.fetchall()

        violations = sum(
            1 for previous, current in zip(positions, positions[1:])
            if current[2] > previous[1]
        )
        return violations == 0, violations, len(positions)

    # ==================== 更新历史 ====================

    def save_update_snapshot(
        self, account_id, records_added, new_records, position_shift=0
    ):
        """保存更新快照，供撤销使用"""
        snapshot = new_records
        if position_shift:
            snapshot = {
                "version": 2,
                "added": new_records,
                "position_shift": position_shift,
            }
        self.conn.execute("""
            INSERT INTO updates (account_id, update_time, records_added, snapshot)
            VALUES (?, ?, ?, ?)
        """, (account_id, _utc_now(), records_added,
              json.dumps(snapshot, ensure_ascii=False)))
        self.conn.commit()

    def get_last_update(self, account_id):
        """获取最后一次更新"""
        cursor = self.conn.execute("""
            SELECT * FROM updates
            WHERE account_id = ?
            ORDER BY update_time DESC, update_id DESC
            LIMIT 1
        """, (account_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def undo_last_update(self, account_id):
        """撤销最后一次更新，返回 (是否成功, 删除的记录数)"""
        last_update = self.get_last_update(account_id)
        if not last_update:
            return False, 0

        snapshot = json.loads(last_update["snapshot"])
        if isinstance(snapshot, dict):
            new_records = snapshot["added"]
            position_shift = snapshot.get("position_shift", 0)
        else:
            new_records = snapshot
            position_shift = 0

        deleted = 0
        self.conn.execute("SAVEPOINT undo_last_update")
        try:
            for rec in new_records:
                cursor = self.conn.execute("""
                    DELETE FROM records
                    WHERE account_id = ? AND pool_id = ? AND result_id = ?
                      AND timestamp_ms = ? AND position = ?
                """, (account_id, rec["pool_id"], rec["result_id"],
                      rec["timestamp_ms"], rec["position"]))
                deleted += cursor.rowcount

            if position_shift:
                self._shift_positions(account_id, -position_shift)
            self.conn.execute("DELETE FROM updates WHERE update_id = ?",
                              (last_update["update_id"],))
            self.conn.execute("RELEASE SAVEPOINT undo_last_update")
            self.conn.commit()
        except Exception:
            self.conn.execute("ROLLBACK TO SAVEPOINT undo_last_update")
            self.conn.execute("RELEASE SAVEPOINT undo_last_update")
            self.conn.commit()
            raise
        return True, deleted

    # ==================== 保底分析 ====================

    def _fetch_group_records(self, account_id, pity_group_value):
        """按时间正序取某个保底组的记录

        timestamp_ms ASC 定大方向，position DESC 处理同毫秒内的先后 ——
        同一毫秒的两次抽卡，position 大的那条更早
        """
        cursor = self.conn.execute("""
            SELECT pool_id, result_id, timestamp_ms, position, rarity
            FROM records
            WHERE account_id = ? AND pity_group = ?
            ORDER BY timestamp_ms ASC, position DESC
        """, (account_id, pity_group_value))
        return cursor.fetchall()

    @staticmethod
    def _count_pity(rows):
        return _pity.count_pity(rows)

    def _observed_standard_six_stars(self, account_id):
        """从抽卡记录反推常驻六星

        常驻池和遴选池只产出常驻六星，凡在这两类池出现过的六星必然是常驻。
        用来自动补全 STANDARD_SIX_STARS，官方新增常驻六星时不必手动登记
        """
        cursor = self.conn.execute("""
            SELECT DISTINCT result_id FROM records
            WHERE account_id = ? AND rarity = 6
              AND pity_group IN ('standard', 'selection')
        """, (account_id,))
        return {row[0] for row in cursor.fetchall()}

    def analyze_limited_guarantee(self, account_id, rows):
        """推导限定池的小保底 / 大保底状态

        rows: 限定组记录，按时间正序

        判定：歪出常驻六星 → 下次必出限定（大保底）；命中限定 → 回到小保底。
        限定池保底跨池继承，limited 组已含所有限定池且按时间排序，顺序遍历即可

        返回: {"guaranteed", "featured_hits", "off_banner", "anomalies"}
        """
        observed = self._observed_standard_six_stars(account_id)
        return _pity.analyze_limited_guarantee(rows, observed)

    def analyze_pity(self, account_id):
        """分析保底进度

        保底规则:
          新手池  30 抽必出自选六星，抽满后关闭
          其余池  70 抽保底，同类型池之间跨池继承
          限定池  额外有 50/50 大小保底

        返回: {group: {"pulls", "current_pity", "six_star_intervals",
                       "cap", "completed", "fifty_fifty"?}}
        """
        records_by_group = {}

        for group in ("standard", "selection", "limited"):
            records_by_group[group] = self._fetch_group_records(account_id, group)

        cursor = self.conn.execute("""
            SELECT DISTINCT pity_group FROM records
            WHERE account_id = ? AND pity_group LIKE 'starter:%'
        """, (account_id,))

        for (group_name,) in cursor.fetchall():
            records_by_group[group_name] = self._fetch_group_records(
                account_id, group_name)

        observed = (
            self._observed_standard_six_stars(account_id)
            if records_by_group["limited"] else ()
        )
        return _pity.analyze_pity(records_by_group, observed)

    def close(self):
        """关闭连接"""
        self.conn.close()
