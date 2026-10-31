"""数据文件位置与旧版本迁移。

数据库、配置和抓包以前都放在程序目录里，解压新版本就会被数据“搬家”
问题卡住。现在统一放到 %APPDATA%\\NightfallGachaAnalyzer，
程序目录只保留可执行文件，覆盖升级不再影响数据。
"""
import shutil
from pathlib import Path

from .config import APP_ROOT, DATA_ROOT

DATA_FILES = (
    "nightfall.db",
    "nightfall.db-wal",
    "nightfall.db-shm",
    "config.json",
)
CAPTURES_DIRNAME = "captures"


def _move_if_missing(source, target):
    if not source.is_file() or target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return True


def _move_captures(legacy_dir, target_dir):
    """把旧的 captures 文件搬过去，同名文件保留目标目录里的那份"""
    moved = []
    if not legacy_dir.is_dir():
        return moved
    target_dir.mkdir(parents=True, exist_ok=True)
    for item in legacy_dir.iterdir():
        if not item.is_file():
            continue
        destination = target_dir / item.name
        if destination.exists():
            continue
        try:
            shutil.move(str(item), str(destination))
        except OSError:
            continue
        moved.append(item.name)
    try:
        legacy_dir.rmdir()
    except OSError:
        pass
    return moved


def migrate_legacy_data(legacy_root=None, target_root=None):
    """把程序目录里的旧数据搬到用户数据目录

    返回 {"target", "migrated", "failed"}。已经迁移过或没有旧数据时
    migrated 为空；目标目录不可写时 failed 为 True，调用方可以回退到
    旧位置继续工作。
    """
    legacy = Path(legacy_root or APP_ROOT)
    target = Path(target_root or DATA_ROOT)
    result = {"target": str(target), "migrated": [], "failed": False}

    if legacy.resolve() == target.resolve():
        return result

    has_legacy_data = (legacy / "nightfall.db").is_file() or \
        (legacy / "config.json").is_file() or \
        (legacy / CAPTURES_DIRNAME).is_dir()
    if not has_legacy_data:
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError:
            result["failed"] = True
        return result

    try:
        target.mkdir(parents=True, exist_ok=True)
        for name in DATA_FILES:
            if _move_if_missing(legacy / name, target / name):
                result["migrated"].append(name)
        captures = _move_captures(
            legacy / CAPTURES_DIRNAME, target / CAPTURES_DIRNAME)
        result["migrated"].extend(
            f"{CAPTURES_DIRNAME}/{name}" for name in captures)
    except OSError:
        result["failed"] = True
    return result


def data_paths(target_root=None):
    """数据库与抓包目录的位置"""
    target = Path(target_root or DATA_ROOT)
    return {
        "root": target,
        "db": target / "nightfall.db",
        "captures": target / CAPTURES_DIRNAME,
    }
