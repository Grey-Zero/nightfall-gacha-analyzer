# 夜幕之下抽卡分析

一个面向 Windows 的本地抽卡记录采集与分析工具。它通过 TShark 捕获游戏网络流量中的抽卡历史，再将记录保存在本地 SQLite 数据库中，并用桌面界面查看各契约类别的保底记录。

## 功能

- 从游戏网络流量采集「全部记录」并导入本地数据库
- 支持多个本地账号、昵称和 UID 管理
- 查看活动、常驻、遴选和新手契约的抽卡记录及六星间隔
- 统计首页概览，并导出抽卡记录或诊断信息
- 可切换昼夜主题，以及记录获取时间、途中五星的显示

## 项目结构

```text
desktop.py          桌面应用入口及前端 API
main.py             命令行采集入口
nightfall/          抓包、协议解析、数据库和分析服务
frontend/           PyWebView 前端和图标资源
data/cards.json     卡牌元数据
data/pools.json     卡池及 UP 卡映射
tests/              自动化回归测试
tools/clicker.py    Windows 点击器辅助工具（也由对应测试使用）
```

本地数据库、配置、原始抓包和导出记录都只保存在本机，不应提交到代码仓库。

## 环境要求

- Windows 10/11
- Python 3.10 或更新版本
- Wireshark（需包含 TShark）和 Npcap
- Windows 抓包可能需要管理员权限；只有权限不足时才尝试以管理员身份启动

程序会先查找项目目录下的 `tshark/tshark.exe`，再查找常见的 Wireshark 安装路径。为避免把第三方二进制文件提交进仓库，`tshark/` 目录已加入 `.gitignore`。推荐安装 Wireshark 与 Npcap，而不是把 DLL/EXE 复制进项目。

## 安装与运行

在项目根目录打开 PowerShell：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python desktop.py
```

首次运行会在项目根目录创建本地数据库 `nightfall.db`。启动后创建或选择账号，再开始采集。

采集时请启动并登录游戏，在确认窗口出现后开始采集；随后打开「契约记录 → 全部记录」并逐页翻阅。完成后回到工具点击「停止并解析」。请勿使用单个卡池筛选。

## 测试

安装开发测试依赖并运行：

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

测试源码集中在 `tests/`。测试不需要真实账号数据库或原始抓包文件；真实抓包附件不会放入仓库。

## Git 提交前检查

当前仓库忽略本地数据库、配置、抓包/导出附件、构建产物和 Python 缓存。请在初始化 Git 后检查待提交文件：

```powershell
git status --short
git check-ignore -v nightfall.db config.json captures\gacha.yaml dist\NightfallClicker.exe
```

应提交应用源码、前端、卡牌/卡池元数据、测试和依赖清单；不要提交真实用户的数据库、UID、原始网络抓包或诊断导出文件。
