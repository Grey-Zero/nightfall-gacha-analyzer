"""启动前的运行环境检查。

界面依赖 pywebview，而 pywebview 在 Windows 上要通过 pythonnet 加载 .NET。
环境缺少 .NET Framework 或程序文件不完整时，PyInstaller 只会弹出一段
Python 调用堆栈，用户看不出该怎么处理，所以这里先做检查并给出中文提示。
"""
import ctypes
import os
import sys
import traceback
from pathlib import Path

# Python.Runtime.dll 是 netstandard2.0 程序集，.NET Framework 4.7.2 起才自带 netstandard 支持
MIN_DOTNET_RELEASE = 461808
# 发行包里这个 dll 约 440 KB，明显偏小说明解压不完整或被安全软件改过
MIN_RUNTIME_DLL_BYTES = 100_000
APP_NAME = "NightfallGachaAnalyzer"
DOTNET_URL = "https://dotnet.microsoft.com/download/dotnet-framework/net48"

# 阈值从高到低，取第一个不大于实际 Release 的版本
DOTNET_RELEASE_NAMES = (
    (533320, "4.8.1"),
    (528040, "4.8"),
    (461808, "4.7.2"),
    (461308, "4.7.1"),
    (460798, "4.7"),
    (394802, "4.6.2"),
    (394254, "4.6.1"),
    (393295, "4.6"),
    (379893, "4.5.2"),
    (378758, "4.5.1"),
)

_UNSET = object()


def is_frozen_app():
    return bool(getattr(sys, "frozen", False))


def read_dotnet_release():
    """读取 HKLM 里 .NET Framework 4.x 的 Release 值，读不到返回 None"""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full",
        ) as key:
            return int(winreg.QueryValueEx(key, "Release")[0])
    except (OSError, ValueError):
        return None


def dotnet_version_name(release):
    """把 Release 值翻译成人类可读的版本号"""
    if release is None:
        return None
    for threshold, name in DOTNET_RELEASE_NAMES:
        if release >= threshold:
            return name
    return "4.5 或更低"


def bundled_runtime_dll(root=None):
    """定位随程序一起打包的 Python.Runtime.dll"""
    if root is None:
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return Path(root) / "pythonnet" / "runtime" / "Python.Runtime.dll"


def diagnose_startup(release=_UNSET, runtime_dll=_UNSET, is_frozen=_UNSET):
    """返回启动环境的问题列表，空列表表示没发现问题"""
    if is_frozen is _UNSET:
        is_frozen = is_frozen_app()
    if release is _UNSET:
        release = read_dotnet_release()
    if runtime_dll is _UNSET:
        runtime_dll = bundled_runtime_dll()
    if isinstance(runtime_dll, str):
        runtime_dll = Path(runtime_dll)

    problems = []

    if release is None:
        problems.append(
            "没有检测到 .NET Framework 4.x。程序界面依赖它启动，"
            "请安装 .NET Framework 4.8 后再试。"
        )
    elif release < MIN_DOTNET_RELEASE:
        name = dotnet_version_name(release)
        problems.append(
            f"系统的 .NET Framework 版本是 {name}，程序需要 4.7.2 或更高版本，"
            "请安装 .NET Framework 4.8 后再试。"
        )

    # 从源码运行时 dll 在 site-packages 里，只有发行包才检查程序目录
    if is_frozen:
        try:
            size = runtime_dll.stat().st_size
        except OSError:
            size = 0
        if size == 0:
            problems.append(
                f"程序目录里找不到 {runtime_dll}。请把 ZIP 完整解压后运行，"
                "不要只把 exe 单独拖出来。"
            )
        elif size < MIN_RUNTIME_DLL_BYTES:
            problems.append(
                f"{runtime_dll.name} 只有 {size} 字节，可能解压不完整或被安全软件改动。"
                "请重新解压完整安装包，或把程序目录加入杀毒软件白名单。"
            )

    return problems


def environment_summary(release=_UNSET, runtime_dll=_UNSET):
    """一行环境摘要，方便用户截图或回传日志"""
    if release is _UNSET:
        release = read_dotnet_release()
    if runtime_dll is _UNSET:
        runtime_dll = bundled_runtime_dll()
    runtime_dll = Path(runtime_dll)

    name = dotnet_version_name(release)
    if name is None:
        dotnet = "未检测到 .NET Framework 4.x"
    else:
        dotnet = f".NET Framework {name}（Release {release}）"

    try:
        size = runtime_dll.stat().st_size
        dll = f"{runtime_dll.name} {size} 字节"
    except OSError:
        dll = f"{runtime_dll.name} 不存在"

    return f"{dotnet}；{dll}"


def user_data_dir():
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_NAME


def write_startup_log(text, log_dir=None):
    """把启动失败的详细信息写到用户目录，方便用户回传"""
    directory = Path(log_dir) if log_dir else user_data_dir()
    path = directory / "startup-error.log"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path
    except OSError:
        return None


def _ask(text, title):
    """弹出确认框，返回用户是否点了「是」"""
    try:
        # 4 = MB_YESNO，0x10 = 错误图标
        return ctypes.windll.user32.MessageBoxW(0, text, title, 0x10 | 0x04) == 6
    except Exception:
        return False


def _open_path(target):
    try:
        os.startfile(str(target))
        return True
    except Exception:
        return False


def _error_headline(error):
    if error is None:
        return ""
    return f"{type(error).__name__}: {error}".splitlines()[0]


def _program_dir():
    if is_frozen_app():
        return Path(sys.executable).resolve().parent
    return None


def report_startup_failure(error=None, problems=None, log_dir=None, during_startup=True):
    """界面无法打开时给出读得懂的中文提示，并留下日志

    面向装好就用、不看命令行的用户：对话框里只写「现在该做什么」，
    原始堆栈写进日志，用户点一下就打开。
    """
    if error is None:
        error = sys.exc_info()[1]
    if problems is None:
        problems = diagnose_startup()

    lines = ["程序无法启动，界面组件没有加载成功。" if during_startup
             else "程序遇到错误，需要关闭。", ""]
    target = "log"
    if problems:
        lines.append("原因：")
        lines.extend(f"· {item}" for item in problems)
        if any(".NET" in item for item in problems):
            target = "dotnet"
        elif _program_dir() is not None:
            # 文件缺失/不完整时，直接打开程序文件夹让用户重新解压
            target = "folder"
    else:
        lines.append(
            "原因：没能确定具体原因，通常是安全软件拦截了程序依赖，"
            "或系统组件不完整。"
        )
    lines.append("")

    lines.append(f"环境信息：{environment_summary()}")
    headline = _error_headline(error)
    if headline:
        lines.append(f"错误信息：{headline}")

    detail = (
        "".join(traceback.format_exception(type(error), error, error.__traceback__))
        if error is not None
        else ""
    )
    log_path = write_startup_log("\n".join(lines) + "\n\n" + detail, log_dir=log_dir)

    lines.append("")
    if target == "dotnet":
        lines.append(f"下载地址：{DOTNET_URL}")
        lines.append("装好后再打开程序即可，账号数据不会丢。")
    elif target == "folder":
        lines.append("请重新下载 ZIP 并完整解压，覆盖到程序文件夹。")
        lines.append("账号数据在用户目录，重新解压不会丢。")
    elif during_startup:
        lines.append("可以把下面的错误信息截图发给开发者。")
    else:
        lines.append("请把详细信息发给开发者。")
    if log_path is not None:
        lines.append("")
        lines.append(f"详细信息已保存到：{log_path}")

    if target == "dotnet":
        action = "点「是」打开 .NET Framework 4.8 下载页"
    elif target == "folder":
        action = "点「是」打开程序文件夹"
    else:
        action = "点「是」打开详细信息"
    lines.extend(["", f"{action}，点「否」直接关闭。"])

    text = "\n".join(lines)
    title = "夜幕之下抽卡分析 启动失败" if during_startup else "夜幕之下抽卡分析 出错"
    if _ask(text, title):
        if target == "dotnet":
            _open_path(DOTNET_URL)
        elif target == "folder":
            _open_path(_program_dir())
        else:
            _open_path(log_path)
    return text


def ensure_environment(log_dir=None):
    """启动前检查 .NET 和程序文件，有问题就提示并返回 False"""
    problems = diagnose_startup()
    if not problems:
        return True
    report_startup_failure(error=None, problems=problems, log_dir=log_dir)
    return False

