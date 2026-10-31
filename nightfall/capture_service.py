"""桌面端抽卡记录采集流程。"""
import threading
import time

from .database import DatabaseManager
from .monitor import GachaMonitor
from .network import detect_game_connections


class CaptureService:
    def __init__(self, db_path, connection_timeout=120):
        self.db_path = db_path
        self.connection_timeout = connection_timeout
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._worker = None
        self._state = {
            "status": "idle",
            "message": "",
            "account_id": None,
            "captured_bytes": 0,
            "result": None,
            "error": None,
        }

    def get_state(self):
        with self._lock:
            state = dict(self._state)
            if state["result"] is not None:
                state["result"] = dict(state["result"])
            return state

    def start(self, account_id):
        account_id = int(account_id)
        db = DatabaseManager(self.db_path)
        try:
            if db.get_account(account_id) is None:
                raise ValueError(f"账号 {account_id} 不存在")
        finally:
            db.close()

        with self._lock:
            if self._state["status"] in {"waiting", "recording", "processing"}:
                raise RuntimeError("当前已有采集任务正在运行")
            self._stop_event = threading.Event()
            self._state = {
                "status": "waiting",
                "message": "正在等待检测到游戏连接；请确保游戏已启动并登录。",
                "account_id": account_id,
                "captured_bytes": 0,
                "result": None,
                "error": None,
            }
            self._worker = threading.Thread(
                target=self._run,
                args=(account_id, self._stop_event),
                name="gacha-capture",
                daemon=True,
            )
            self._worker.start()
        return self.get_state()

    def stop(self):
        with self._lock:
            if self._state["status"] not in {"waiting", "recording"}:
                return self.get_state()
            self._stop_event.set()
            self._state["message"] = "正在停止采集并处理已捕获的数据…"
            return self.get_state()

    def _set_state(self, **updates):
        with self._lock:
            self._state.update(updates)

    def _run(self, account_id, stop_event):
        monitor = None
        result = None
        try:
            deadline = time.monotonic() + self.connection_timeout
            connection = None
            while not stop_event.is_set() and time.monotonic() < deadline:
                connection = detect_game_connections()
                if connection:
                    break
                stop_event.wait(1)

            if stop_event.is_set():
                self._set_state(status="cancelled", message="已取消等待游戏连接。")
                return
            if not connection:
                raise TimeoutError(
                    "等待游戏连接超时。请启动并登录游戏后重试；"
                    "Windows 抓包可能需要以管理员身份运行本工具。"
                )

            monitor = GachaMonitor(
                connection["endpoints"], connection["interface"])
            monitor.start()
            self._set_state(
                status="recording",
                message=(
                    "正在录制。请在游戏里打开「契约 → 契约记录 → 全部记录」，"
                    "逐页翻到最后；完成后点击“停止并解析”。"
                ),
            )

            while not stop_event.wait(0.5):
                if not monitor.is_recording():
                    raise RuntimeError(
                        "TShark 抓包进程意外退出。请检查网卡选择、Wireshark/Npcap "
                        "安装状态和管理员权限后重试。"
                    )
                self._set_state(captured_bytes=monitor.get_captured_size())

            self._set_state(
                status="processing",
                message="正在停止录制、解析数据并导入当前账号…",
                captured_bytes=monitor.get_captured_size(),
            )
            monitor.stop()
            records = monitor.process()
            result = self._save_records(account_id, records, monitor)
        except Exception as error:
            self._set_state(
                status="error",
                message="采集失败，请查看下方提示并按建议重试。",
                error=str(error),
            )
        finally:
            if monitor is not None:
                try:
                    if monitor.is_recording():
                        monitor.stop()
                except Exception as error:
                    self._set_state(
                        status="error",
                        message="停止抓包进程失败。",
                        error=str(error),
                    )
                try:
                    monitor.cleanup()
                except OSError as error:
                    self._set_state(
                        status="error",
                        message="清理临时抓包文件失败。",
                        error=str(error),
                    )
        if result is not None and self.get_state()["status"] != "error":
            self._set_state(
                status="completed",
                message=result["message"],
                result=result,
            )

    def _save_records(self, account_id, records, monitor):
        diagnostics_getter = getattr(monitor, "get_extract_stats", None)
        diagnostics = diagnostics_getter() if diagnostics_getter else {}
        gaps = diagnostics.get("gaps", [])
        if records and gaps:
            gap_text = "、".join(
                f"{start}-{end}" for start, end in gaps
            )
            return {
                "records": 0,
                "inserted": 0,
                "duplicated": 0,
                "server_total": monitor.get_server_total(),
                "single_pool_queries": monitor.get_single_pool_count(),
                "warnings": [],
                "diagnostics": diagnostics,
                "message": (
                    "没有导入记录：抓取到的分页中存在漏页"
                    f"（异常区间：{gap_text}）。请重新完整采集"
                    "「契约记录 → 全部记录」，逐页翻到最后后停止。"
                ),
            }

        if not records:
            single_pool_count = monitor.get_single_pool_count()
            diagnostics_getter = getattr(monitor, "get_extract_stats", None)
            diagnostics = diagnostics_getter() if diagnostics_getter else {}
            mismatch_count = diagnostics.get("offset_mismatch", 0)
            unpaired_count = diagnostics.get("unpaired", 0)
            bad_frame_count = diagnostics.get("bad_frames", 0)
            response_count = diagnostics.get("responses", 0)
            details = []
            if mismatch_count:
                details.append(f"{mismatch_count} 个响应与请求 offset 不一致")
            if unpaired_count:
                details.append(f"{unpaired_count} 个响应没有找到请求")
            if bad_frame_count:
                details.append(f"{bad_frame_count} 个响应帧不完整或无法识别")
            if response_count:
                details.append(f"共解析到 {response_count} 个抽卡响应")
            if single_pool_count:
                message = (
                    "没有导入记录：抓到了单卡池筛选请求。请重新采集，"
                    "并在游戏中进入「契约记录 → 全部记录」后逐页翻阅。"
                )
            else:
                message = (
                    "没有解析到记录。请确认采集期间确实打开并翻阅了"
                    "「契约记录 → 全部记录」。"
                )
            if details:
                message += "\n诊断：" + "；".join(details) + "。"
            return {
                "records": 0,
                "inserted": 0,
                "duplicated": 0,
                "server_total": monitor.get_server_total(),
                "single_pool_queries": single_pool_count,
                "warnings": [],
                "diagnostics": diagnostics,
                "message": message,
            }

        db = DatabaseManager(self.db_path)
        try:
            if db.get_account(account_id) is None:
                raise ValueError(f"导入失败：账号 {account_id} 已不存在")
            db.set_active_account(account_id)
            inserted, duplicated, new_records = db.insert_records(
                account_id, records)
            if inserted:
                db.save_update_snapshot(
                    account_id, inserted, new_records, db.last_position_shift)

            warnings = []
            ok, violations, total_positions = db.verify_position_direction(account_id)
            if not ok:
                warnings.append(
                    f"记录顺序校验异常：{total_positions} 个位置中有 "
                    f"{violations} 处顺序冲突，保底间隔可能不准确。"
                )
            position_range = db.get_position_range(account_id)
            if position_range["missing"]:
                warnings.append(
                    f"记录位置 {position_range['min']}–{position_range['max']} "
                    f"之间缺少 {position_range['missing']} 条。"
                )
            stored = db.get_record_count(account_id)
            server_total = monitor.get_server_total()
            if server_total and stored < server_total:
                warnings.append(
                    f"服务器报告共 {server_total} 条，当前账号已有 {stored} 条；"
                    "如需补全，可继续采集并翻阅剩余记录。"
                )
        finally:
            db.close()

        return {
            "records": len(records),
            "inserted": inserted,
            "duplicated": duplicated,
            "server_total": server_total,
            "single_pool_queries": monitor.get_single_pool_count(),
            "warnings": warnings,
            "message": f"解析到 {len(records)} 条记录，新增 {inserted} 条，重复 {duplicated} 条。",
        }
