#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""夜幕之下抽卡记录采集与分析"""
import time

from nightfall import cli_ui
from nightfall.config import DB_PATH
from nightfall.database import DatabaseManager
from nightfall.monitor import GachaMonitor
from nightfall.network import detect_game_connections
from nightfall.storage import migrate_legacy_data


def wait_for_game(poll_interval=1.0, timeout=120.0):
    deadline = time.time() + timeout
    with cli_ui.waiting_status():
        while time.time() < deadline:
            result = detect_game_connections()
            if result:
                return result
            time.sleep(poll_interval)
    return None


def capture_records():
    """抓包并返回记录列表，失败返回 None"""
    connection = wait_for_game()
    if not connection:
        cli_ui.show_capture_timeout()
        return None

    cli_ui.show_connection(connection)

    monitor = GachaMonitor(connection['endpoints'], connection['interface'])
    try:
        monitor.start()
    except Exception as error:
        cli_ui.show_capture_start_error(error)
        return None

    cli_ui.show_capture_instructions()
    cli_ui.wait_for_capture_stop()

    cli_ui.show_stopping_capture()
    monitor.stop()
    cli_ui.show_processing_capture()

    try:
        records = monitor.process()
    except Exception as error:
        cli_ui.show_parse_error(error)
        import traceback
        traceback.print_exc()
        return None
    finally:
        monitor.cleanup()

    if not records:
        cli_ui.show_no_records(monitor.get_single_pool_count())
        return None

    return records, monitor.get_server_total()


def main():
    migrate_legacy_data()
    cli_ui.show_title()

    result = capture_records()
    if not result:
        return
    records, server_total = result

    cli_ui.show_capture_summary(len(records), server_total)

    db = DatabaseManager(DB_PATH)
    try:
        account_id = cli_ui.select_account(db)
        db.set_active_account(account_id)

        inserted, duplicated, new_records = db.insert_records(account_id, records)
        cli_ui.show_insert_summary(inserted, duplicated)

        if inserted:
            db.save_update_snapshot(
                account_id, inserted, new_records, db.last_position_shift)

        ok, violations, total = db.verify_position_direction(account_id)
        if not ok:
            cli_ui.show_position_direction_warning(violations, total)

        position_range = db.get_position_range(account_id)
        if position_range['missing']:
            cli_ui.show_position_gaps(position_range)

        cli_ui.show_pity(db, account_id)

        stored = db.get_record_count(account_id)
        if server_total and stored < server_total:
            cli_ui.show_server_remaining(stored, server_total)
    finally:
        db.close()


if __name__ == "__main__":
    main()
