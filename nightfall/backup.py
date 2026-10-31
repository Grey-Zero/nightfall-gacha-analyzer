"""抽卡数据的备份导出与恢复。

备份文件是单个 JSON，包含所有账号及其全部记录。恢复只做增量合并：
已存在的账号按 UID（有则优先）或昵称匹配，记录按
(pool_id, result_id, timestamp_ms) 去重，不会删除现有数据。
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from .database import DatabaseManager

BACKUP_FORMAT = "nightfall-backup"
BACKUP_VERSION = 1


def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_backup(db_path="nightfall.db"):
    """导出全部账号与记录"""
    db = DatabaseManager(db_path)
    try:
        accounts = db.get_all_accounts()
        exported = []
        for account in accounts:
            records = db.get_records(account["account_id"])
            exported.append({
                "nickname": account["nickname"],
                "uid": account["uid"],
                "note": account.get("note"),
                "created_at": account["created_at"],
                "last_active_at": account["last_active_at"],
                "records": [
                    {
                        "pool_id": record["pool_id"],
                        "result_id": record["result_id"],
                        "timestamp_ms": record["timestamp_ms"],
                        "position": record["position"],
                        "rarity": record["rarity"],
                        "name": record["name"],
                        "character": record["character"],
                        "pity_group": record["pity_group"],
                        "timestamp_utc": record["timestamp_utc"],
                    }
                    for record in records
                ],
            })
    finally:
        db.close()

    return {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "exported_at": _utc_now(),
        "account_count": len(exported),
        "record_count": sum(len(account["records"]) for account in exported),
        "accounts": exported,
    }


def _validate(data):
    if not isinstance(data, dict):
        raise ValueError("备份文件内容不是有效的 JSON 对象")
    if data.get("format") != BACKUP_FORMAT:
        raise ValueError("这不是本工具的备份文件")
    try:
        version = int(data.get("version", 0))
    except (TypeError, ValueError):
        version = 0
    if version < 1:
        raise ValueError("备份文件版本无法识别")
    if version > BACKUP_VERSION:
        raise ValueError("备份文件来自更新版本的程序，请先升级后再导入")
    accounts = data.get("accounts")
    if not isinstance(accounts, list):
        raise ValueError("备份文件缺少账号数据")
    return accounts


def _account_records(raw):
    records = []
    for item in raw or ():
        if not isinstance(item, dict):
            continue
        try:
            records.append((
                int(item["pool_id"]),
                int(item["result_id"]),
                int(item["timestamp_ms"]),
                int(item["position"]),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return records


def _find_existing_account(db, uid, nickname):
    """按昵称匹配已有账号

    昵称是账号表的主键（UNIQUE），所以优先按昵称匹配。用户在另一台
    机器上改过昵称时，再退一步：只有当这个 UID 在本机恰好对应唯一
    一个账号时才认为是同一账号，避免把两个账号合并到一起。
    """
    accounts = db.get_all_accounts()
    for account in accounts:
        if account["nickname"] == nickname:
            return account
    if uid:
        candidates = [
            account for account in accounts if account["uid"] == uid
        ]
        if len(candidates) == 1:
            return candidates[0]
    return None


def _fill_missing_profile(db, account, uid, note):
    """匹配到已有账号时，用备份补全本机缺少的 UID / 备注"""
    updates = {}
    if uid and not account.get("uid"):
        updates["uid"] = uid
    if note and not account.get("note"):
        updates["note"] = note
    if not updates:
        return
    db.update_account(
        account["account_id"],
        account["nickname"],
        updates.get("uid", account.get("uid")),
        updates.get("note", account.get("note")),
    )


def _create_imported_account(db, nickname, uid, note):
    """新建导入账号，昵称冲突时自动加后缀"""
    candidates = [nickname, f"{nickname}（导入）"]
    candidates.extend(f"{nickname}（导入 {index}）" for index in range(2, 20))
    for candidate in candidates:
        try:
            return db.create_account(candidate, uid or None, note or None)
        except ValueError:
            continue
    raise ValueError("昵称冲突过多，无法创建导入账号")


def import_backup(db_path, data):
    """把备份合并进本地数据库，返回结果摘要"""
    accounts = _validate(data)
    created = 0
    matched = 0
    inserted_total = 0
    skipped_total = 0
    errors = []

    db = DatabaseManager(db_path)
    try:
        for raw in accounts:
            if not isinstance(raw, dict):
                continue
            nickname = str(raw.get("nickname") or "").strip()
            if not nickname:
                errors.append("跳过一条没有昵称的账号数据")
                continue
            uid = str(raw.get("uid") or "").strip() or None
            note = str(raw.get("note") or "").strip() or None
            records = _account_records(raw.get("records"))

            existing = _find_existing_account(db, uid, nickname)
            if existing is None:
                try:
                    account_id = _create_imported_account(
                        db, nickname, uid, note)
                except ValueError as error:
                    errors.append(f"{nickname}：{error}")
                    continue
                created += 1
            else:
                account_id = existing["account_id"]
                matched += 1
                try:
                    _fill_missing_profile(db, existing, uid, note)
                except ValueError as error:
                    errors.append(f"{nickname}：{error}")

            try:
                inserted, duplicated, new_records = db.insert_records(
                    account_id, records)
            except ValueError as error:
                errors.append(f"{nickname}：{error}")
                continue

            if inserted:
                db.save_update_snapshot(
                    account_id, inserted, new_records,
                    db.last_position_shift)
            inserted_total += inserted
            skipped_total += duplicated
    finally:
        db.close()

    return {
        "accounts_created": created,
        "accounts_matched": matched,
        "records_inserted": inserted_total,
        "records_skipped": skipped_total,
        "errors": errors,
    }


def import_backup_file(db_path, path):
    """从文件导入备份"""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"备份文件不存在：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise ValueError("备份文件不是有效的 JSON") from error
    return import_backup(db_path, data)
