#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""夜幕之下抽卡分析桌面应用。"""
import json
from pathlib import Path
import sys
import webbrowser
from datetime import datetime

import webview

from nightfall.data_service import get_accounts, get_dashboard, get_export_data
from nightfall.capture_service import CaptureService
from nightfall.config import APP_VERSION, DB_PATH, CAPTURES_DIR
from nightfall.database import DatabaseManager
from nightfall.backup import build_backup, import_backup_file
from nightfall.diagnostics import (
    build_error_report,
    capture_storage_info,
    clear_capture_files,
)
from nightfall.storage import migrate_legacy_data
from nightfall.updates import RELEASE_PAGE, check_update


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
ICON_PATH = ROOT / "frontend" / "assets" / "nightfall.ico"
capture_service = CaptureService(DB_PATH, captures_dir=CAPTURES_DIR)


class Api:
    def _save_json(self, filename, content):
        path = webview.windows[0].create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=filename,
            file_types=("JSON files (*.json)",),
        )
        if not path:
            return {"cancelled": True}
        Path(path[0]).write_text(
            json.dumps(content, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"cancelled": False, "path": path[0]}

    def _open_json(self):
        path = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN,
            file_types=("JSON files (*.json)",),
        )
        if not path:
            return None
        return path[0]

    def get_accounts(self):
        return get_accounts(DB_PATH)

    def get_dashboard(self, payload):
        account_id = int(payload["account_id"])
        db = DatabaseManager(DB_PATH)
        try:
            db.set_active_account(account_id)
        finally:
            db.close()
        return get_dashboard(account_id, DB_PATH)

    def create_account(self, payload):
        nickname = payload["nickname"].strip()
        if not nickname:
            raise ValueError("账号昵称不能为空")
        uid = (payload.get("uid") or "").strip() or None
        note = (payload.get("note") or "").strip() or None
        db = DatabaseManager(DB_PATH)
        try:
            account_id = db.create_account(nickname, uid, note)
        finally:
            db.close()
        return {"account_id": account_id}

    def update_account(self, payload):
        account_id = int(payload["account_id"])
        nickname = payload["nickname"].strip()
        if not nickname:
            raise ValueError("账号昵称不能为空")
        uid = (payload.get("uid") or "").strip() or None
        note = (payload.get("note") or "").strip() or None
        db = DatabaseManager(DB_PATH)
        try:
            if not db.update_account(account_id, nickname, uid, note):
                raise ValueError(f"账号 {account_id} 不存在")
        finally:
            db.close()
        return {
            "account_id": account_id,
            "nickname": nickname,
            "uid": uid,
            "note": note,
        }

    def delete_account(self, payload):
        account_id = int(payload["account_id"])
        state = capture_service.get_state()
        if state["status"] in {"waiting", "recording", "processing"} \
                and state.get("account_id") == account_id:
            raise ValueError("该账号正在采集记录，请先停止采集再删除")
        db = DatabaseManager(DB_PATH)
        try:
            if not db.delete_account(account_id):
                raise ValueError(f"账号 {account_id} 不存在")
        finally:
            db.close()
        return {"account_id": account_id, "deleted": True}

    def get_capture_state(self):
        return capture_service.get_state()

    def start_capture(self, payload):
        return capture_service.start(payload["account_id"])

    def stop_capture(self):
        return capture_service.stop()

    def export_records(self, payload):
        account_id = int(payload["account_id"])
        export = get_export_data(account_id, DB_PATH)
        return self._save_json(
            f"nightfall-records-account-{account_id}.json",
            export,
        )

    def export_error_report(self, payload=None):
        state = capture_service.get_state()
        last_capture = None
        if state.get("status") != "idle" or state.get("error") \
                or state.get("result"):
            result = state.get("result") or {}
            last_capture = {
                "status": state.get("status"),
                "message": state.get("message"),
                "error": state.get("error"),
                "account_id": state.get("account_id"),
                "result": {
                    key: result.get(key) for key in (
                        "records", "inserted", "duplicated", "server_total",
                        "single_pool_queries", "warnings", "diagnostics",
                    )
                } if result else None,
            }
        report = build_error_report(CAPTURES_DIR, last_capture)
        filename = (
            "nightfall-error-report-"
            f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        )
        return self._save_json(filename, report)

    def undo_last_import(self, payload):
        account_id = int(payload["account_id"])
        state = capture_service.get_state()
        if state["status"] in {"waiting", "recording", "processing"}:
            raise ValueError("正在采集记录，请先停止采集再撤销")
        db = DatabaseManager(DB_PATH)
        try:
            undone, deleted = db.undo_last_update(account_id)
        finally:
            db.close()
        if not undone:
            raise ValueError("当前账号没有可撤销的导入记录")
        return {"undone": True, "deleted": deleted}

    def export_backup(self, payload=None):
        backup = build_backup(DB_PATH)
        filename = (
            "nightfall-backup-"
            f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        )
        result = self._save_json(filename, backup)
        result.update({
            "account_count": backup["account_count"],
            "record_count": backup["record_count"],
        })
        return result

    def import_backup(self, payload=None):
        state = capture_service.get_state()
        if state["status"] in {"waiting", "recording", "processing"}:
            raise ValueError("正在采集记录，请先停止采集再导入备份")
        path = self._open_json()
        if path is None:
            return {"cancelled": True}
        summary = import_backup_file(DB_PATH, path)
        summary.update({"cancelled": False, "path": path})
        return summary

    def clear_error_reports(self, payload=None):
        state = capture_service.get_state()
        if state["status"] in {"waiting", "recording", "processing"}:
            raise ValueError("正在采集记录，请先停止采集再清理")
        return clear_capture_files(CAPTURES_DIR)

    def get_error_storage_info(self, payload=None):
        return capture_storage_info(CAPTURES_DIR)

    def get_app_info(self, payload=None):
        return {
            "version": APP_VERSION,
            "data_dir": str(DB_PATH.parent),
        }

    def check_update(self, payload=None):
        return check_update()

    def open_release_page(self, payload=None):
        url = (payload or {}).get("url") or RELEASE_PAGE
        webbrowser.open(url)
        return {"opened": True}


def main():
    migrate_legacy_data()
    window = webview.create_window(
        "夜幕之下抽卡分析",
        str(ROOT / "frontend" / "index.html"),
        js_api=Api(),
        width=1200,
        height=800,
        min_size=(820, 540),
        resizable=True,
    )
    webview.start(debug=False, icon=str(ICON_PATH))
    return window


if __name__ == "__main__":
    main()
