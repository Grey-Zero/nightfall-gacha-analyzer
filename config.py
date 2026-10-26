# nightfall/config.py
import json
from pathlib import Path

CONFIG_PATH = Path("config.json")
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
    except:
        # 配置损坏，重置为默认
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
