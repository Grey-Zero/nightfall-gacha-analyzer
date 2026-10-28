"""配置文件管理"""
import json
import sys
from pathlib import Path

APP_ROOT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent.parent
)
CONFIG_PATH = APP_ROOT / "config.json"

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
