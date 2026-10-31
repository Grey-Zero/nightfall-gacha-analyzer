"""新版本检测。

只读取 GitHub Releases 的版本信息，不下载、不替换任何文件；
发现新版本时由界面提示用户手动下载。
"""
import json
import re
import urllib.error
import urllib.request

from .config import APP_VERSION

RELEASE_API = (
    "https://api.github.com/repos/Grey-Zero/nightfall-gacha-analyzer"
    "/releases/latest"
)
RELEASE_PAGE = "https://github.com/Grey-Zero/nightfall-gacha-analyzer/releases/latest"
REQUEST_TIMEOUT = 6


def parse_version(text):
    """把 v0.1.5 这类版本号转成可比较的元组，失败返回 None"""
    if not text:
        return None
    match = re.match(r"^\s*v?(\d+(?:\.\d+)*)", str(text))
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def compare_versions(left, right):
    """返回 1/0/-1；无法解析时返回 None"""
    left_parts = parse_version(left)
    right_parts = parse_version(right)
    if left_parts is None or right_parts is None:
        return None
    length = max(len(left_parts), len(right_parts))
    left_parts += (0,) * (length - len(left_parts))
    right_parts += (0,) * (length - len(right_parts))
    if left_parts > right_parts:
        return 1
    if left_parts < right_parts:
        return -1
    return 0


def _fetch_release(timeout=REQUEST_TIMEOUT):
    request = urllib.request.Request(
        RELEASE_API,
        headers={
            "User-Agent": f"NightfallGachaAnalyzer/{APP_VERSION}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def check_update(timeout=REQUEST_TIMEOUT):
    """检查是否有新版本

    返回 {"available", "current", "latest", "url", "notes", "error"}；
    网络失败时 available 为 False 并带上 error，界面可以静默忽略。
    """
    result = {
        "available": False,
        "current": APP_VERSION,
        "latest": None,
        "url": RELEASE_PAGE,
        "notes": None,
        "published_at": None,
        "error": None,
    }
    try:
        release = _fetch_release(timeout)
    except (urllib.error.URLError, OSError, ValueError) as error:
        result["error"] = f"暂时无法检查更新（{error}）"
        return result

    tag = release.get("tag_name") or release.get("name")
    comparison = compare_versions(tag, APP_VERSION)
    if comparison is None:
        result["error"] = "无法识别最新版本号"
        return result

    result.update({
        "latest": str(tag).lstrip("v"),
        "url": release.get("html_url") or RELEASE_PAGE,
        "notes": (release.get("body") or "").strip()[:2000] or None,
        "published_at": release.get("published_at"),
        "available": comparison > 0,
    })
    return result
