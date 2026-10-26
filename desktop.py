#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""夜幕之下抽卡分析桌面应用。"""
import ctypes
import json
import platform
from pathlib import Path
import sys
from datetime import datetime, timezone

import webview

from nightfall.data_service import get_accounts, get_dashboard, get_export_data
from nightfall.capture_service import CaptureService
from nightfall.database import DatabaseManager
from nightfall.network import find_tshark


ROOT = Path(__file__).parent
DB_PATH = ROOT / "nightfall.db"
capture_service = CaptureService(DB_PATH)


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
        db = DatabaseManager(DB_PATH)
        try:
            account_id = db.create_account(nickname, uid or None)
        finally:
            db.close()
        return {"account_id": account_id}

    def update_account(self, payload):
        account_id = int(payload["account_id"])
        nickname = payload["nickname"].strip()
        if not nickname:
            raise ValueError("账号昵称不能为空")
        uid = (payload.get("uid") or "").strip() or None
        db = DatabaseManager(DB_PATH)
        try:
            if not db.update_account(account_id, nickname, uid):
                raise ValueError(f"账号 {account_id} 不存在")
        finally:
            db.close()
        return {"account_id": account_id, "nickname": nickname, "uid": uid}

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

    def export_diagnostics(self, payload):
        account_id = int(payload["account_id"])
        db = DatabaseManager(DB_PATH)
        try:
            account = db.get_account(account_id)
        finally:
            db.close()
        if account is None:
            raise ValueError(f"账号 {account_id} 不存在")

        try:
            elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except AttributeError:
            elevated = False
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "account": {
                "account_id": account_id,
                "nickname": account["nickname"],
            },
            "application": {
                "python_version": sys.version,
                "platform": platform.platform(),
                "elevated": elevated,
                "tshark_available": bool(find_tshark()),
            },
            "capture_state": capture_service.get_state(),
        }
        return self._save_json("nightfall-diagnostics.json", report)


def main():
    window = webview.create_window(
        "夜幕之下抽卡分析",
        str(ROOT / "frontend" / "index.html"),
        js_api=Api(),
        width=1080,
        height=740,
        min_size=(720, 520),
        resizable=True,
    )
    webview.start(debug=False)
    return window


if __name__ == "__main__":
    main()
