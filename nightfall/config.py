"""配置文件管理"""
import json
import os
import sys
from pathlib import Path

APP_ROOT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent.parent
)

APP_NAME = "NightfallGachaAnalyzer"


def user_data_root():
    """用户数据目录：程序目录可随时替换，数据不能跟着走"""
    base = os.environ.get("APPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_NAME


DATA_ROOT = user_data_root()
CONFIG_PATH = DATA_ROOT / "config.json"
DB_PATH = DATA_ROOT / "nightfall.db"
CAPTURES_DIR = DATA_ROOT / "captures"

# 程序版本号：发布新版本时更新，供更新检测和错误报告使用
APP_VERSION = "0.2.0"

DEFAULT_CONFIG = {
    "last_account_id": None,
    "interface": "以太网"
}


def load_config():
    """加载配置，如果不存在则创建默认配置"""
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()


def save_config(config):
    """保存配置"""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def get_last_account_id():
    """获取上次使用的账号ID"""
    config = load_config()
    return config.get("last_account_id")


def set_last_account_id(account_id):
    """保存当前账号ID"""
    config = load_config()
    config["last_account_id"] = account_id
    save_config(config)
