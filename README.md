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
frontend/assets/    Windows 应用图标和界面图标
data/cards.json     卡牌元数据
data/pools.json     卡池及 UP 卡映射
tests/              自动化回归测试
tools/clicker.py    Windows 点击器辅助工具（也由对应测试使用）
```

本地数据库、配置、原始抓包和导出记录都只保存在本机，不应提交到代码仓库。
Windows 桌面窗口使用 `frontend/assets/nightfall.ico` 作为原生窗口图标；该图标由项目提供的原图裁切生成。

## 环境要求

- Windows 10/11
- Python 3.10 或更新版本
- Npcap（运行抓包功能时需要 Windows 捕获驱动）
- Windows 抓包可能需要管理员权限；只有权限不足时才尝试以管理员身份启动

发行包内已捆绑 TShark，程序会优先使用 `tshark/tshark.exe`。项目源码目录中的 `tshark/` 为本地构建附件，已加入 `.gitignore`，源码不直接提交第三方二进制文件。仍需在 Windows 上安装 Npcap 捕获驱动；若系统已有 Npcap，可以无需额外安装。

## 下载使用

在 GitHub Releases 下载最新版 ZIP，解压后运行 `NightfallGachaAnalyzer.exe`。

首次使用需要安装 Npcap，然后启动并登录游戏。在工具中选择账号并点击「开始采集记录」，再到游戏的「契约记录 → 全部记录」逐页翻阅，最后点击「停止并解析」。

采集到的记录和账号数据保存在本机，不会上传到服务器。

### 采集失败怎么办

如果提示「没有解析到记录」或「分页中存在漏页」，按下面顺序排查：

1. 确认采集期间进入的是「契约记录 → 全部记录」，不是某个单独卡池；停止前要把列表翻到最后。
2. 以管理员身份运行程序，采集期间不要同时下载或看视频，避免抓包丢包。
3. 提示「抓包丢失了部分数据流」时说明抓包被系统丢了数据，直接重试通常就好。
4. 抓取全部记录时数据量大，翻页不要过快，等列表显示出来再继续往下翻。

解析失败时程序会把本次抓包保存到程序目录下的 `captures/`，反馈问题时附上该文件能直接定位原因。这些文件只在本机，可以随时删除。

## 从源码运行

在项目根目录打开 PowerShell：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python desktop.py
```

首次运行会在项目根目录创建本地数据库 `nightfall.db`。启动后创建或选择账号，再开始采集。

`requirements.txt` 是运行所需依赖；`requirements-dev.txt` 是开发所需依赖，包含测试和 PyInstaller，并通过 `-r requirements.txt` 自动包含运行依赖。

## 构建 Windows 发行目录

```powershell
python -m pip install -r requirements-dev.txt
python -m PyInstaller --noconfirm NightfallGachaAnalyzer.spec
```

发行目录位于 `dist/NightfallGachaAnalyzer/`。打包配置优先使用项目内的 `tshark/`；若不存在，则使用本机安装的 Wireshark，并将完整 TShark 运行文件放入发行目录。卡牌/卡池数据、前端资源和 `nightfall.ico` 也会一并打包。将整个目录压缩为 ZIP 后发布；数据库和配置保存在 EXE 旁边。用户仍需安装 Npcap 才能创建网络捕获接口。

采集时请启动并登录游戏，在确认窗口出现后开始采集；随后打开「契约记录 → 全部记录」并逐页翻阅。完成后回到工具点击「停止并解析」。请勿使用单个卡池筛选。

## 测试

安装开发测试依赖并运行：

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

测试源码集中在 `tests/`。测试不需要真实账号数据库或原始抓包文件；真实抓包附件不会放入仓库。

