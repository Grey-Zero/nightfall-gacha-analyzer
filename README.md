<img src="frontend/assets/nightfall.svg" width="88" alt="夜幕之下抽卡分析">

# 夜幕之下抽卡分析

一个面向 Windows 的本地抽卡记录工具。它读取本机网卡上与游戏服务器的通信，解析出「契约记录」里的抽卡历史，保存到本地 SQLite 数据库，并按契约类别统计六星间隔和保底进度。

工具不修改游戏文件，也不注入游戏进程，只通过系统抓包驱动读取网络流量。所有记录只保存在本机，不会上传到任何服务器。

## 功能

**采集**

- 一次读取「契约记录 → 全部记录」的全部分页
- 按 TCP 序号重组数据流，重传和乱序不会破坏解析
- 自动校验分页是否连续、是否翻到最后一页
- 支持多个账号，各自独立保存记录

**分析**

- 首页概览：总抽数、六星数量、限定/遴选不歪率、各契约类别进度、最近获得的六星
- 按活动契约、常驻契约、遴选契约、新手池分类查看每一次六星的抽数与间隔
- 可切换显示获取时间和途中获得的五星
- 昼夜主题切换
- 导出抽卡记录和诊断信息（JSON 格式）

## 系统要求

- Windows 10 / 11
- [Npcap](https://npcap.com/) 抓包驱动（安装时保持默认选项即可）

从 Releases 下载的发行包已内置 TShark，不需要另外安装 Wireshark。

## 安装与使用

1. 在 [Releases](https://github.com/Grey-Zero/nightfall-gacha-analyzer/releases) 下载最新版 ZIP，**完整解压**后再运行，不要只把 exe 单独拖出来，程序依赖同目录下的文件。
2. 如果还没装 Npcap，先安装它。
3. 启动游戏并登录。
4. 打开 `NightfallGachaAnalyzer.exe`，新建或选择一个账号。
5. 点击「开始采集记录」，确认清单后点击「我已准备好，开始」。
6. 回到游戏，进入**契约 → 契约记录 → 全部记录**，一直翻到最后一页。
7. 切回工具，点击「停止并解析」，记录会写入当前账号。

采集期间请注意：

- 必须使用「全部记录」，选择单个卡池的查询不会被导入。
- 一定要翻到最后一页再停止。中途停止会被判定为漏页并拒绝导入，避免写入残缺数据。
- 翻页时等列表显示出来再继续，不用太快。
- 如果提示权限不足，请关闭程序后以管理员身份重新启动。

## 常见问题

**提示「没有解析到记录」**

确认采集期间进入的是「契约记录 → 全部记录」而不是某个单独卡池，并且确实翻动了列表。如果是从其他页面开始录制的，重新采集一次即可。

**提示「分页中存在漏页」**

说明某一页没有抓到，通常是翻页太快或提前停止了采集。重新采集一次，逐页翻到最底部再停止。

**提示「抓包丢失了部分数据流」**

系统在录制期间丢包。用管理员身份运行通常能解决；采集时也请避免同时下载文件或看视频。直接重试即可。

**提示「没有找到游戏连接」**

游戏需要先启动并登录，工具才能检测到服务器地址。

**采集失败后留下的 `captures/` 是什么？**

解析失败时，程序会把本次原始抓包保存到程序目录下的 `captures/`，方便定位原因。文件只在本机，可以随时删除；反馈问题时附上它最有用。

**数据存在哪里？**

数据库 `nightfall.db` 和配置 `config.json` 都在程序目录下。删除它们等于清空所有账号和记录，建议先导出备份。

**卸载会不会删掉记录？**

程序没有安装过程，删除文件夹即可。记得先导出记录或保留 `nightfall.db`。

## 从源码运行

需要 Python 3.10 或更新版本：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python desktop.py
```

首次运行会在项目根目录创建 `nightfall.db`。

如果习惯命令行，也可以使用 `python main.py` 完成一次采集并查看统计。

## 项目结构

```text
desktop.py               桌面应用入口和前端 API
main.py                  命令行采集入口
nightfall/
  capture.py             抓包录制、TCP 重组
  gacha.py               帧解析、请求响应配对、分页展开
  protocol.py            通信协议与压缩解析
  capture_service.py     采集流程与状态管理
  monitor.py             采集监听器
  network.py             游戏连接与网卡检测
  database.py            SQLite 存储
  data_service.py        首页与记录页数据
  pity.py                保底与六星间隔统计
  cards.py               卡牌与卡池数据加载
  cli_ui.py              命令行界面
frontend/                PyWebView 界面（HTML/CSS/JS）与图标
data/                    卡牌与卡池元数据
tests/                   回归测试
tools/                   开发辅助脚本
NightfallGachaAnalyzer.spec   PyInstaller 打包配置
```

数据库、配置、原始抓包和构建产物都在 `.gitignore` 中，不会进入仓库。

## 构建发行包

安装开发依赖并打包：

```powershell
python -m pip install -r requirements-dev.txt
python -m PyInstaller --noconfirm NightfallGachaAnalyzer.spec
```

产物在 `dist/NightfallGachaAnalyzer/`。打包脚本会优先使用项目内的 `tshark/`，没有则使用本机安装的 Wireshark，并把完整的 TShark 运行文件、界面资源、卡牌数据一起复制进去。

发布时请把**整个目录**压缩成 ZIP 上传，单发 exe 无法运行。用户仍然需要自行安装 Npcap。

## 测试

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

测试不依赖真实账号数据库或抓包文件，仓库中也不保存真实流量。

## 参与贡献

欢迎提交 Issue 反馈问题。如果是解析失败，请附上程序目录 `captures/` 里对应的 pcap 文件，它能直接定位原因。

## 致谢

抓包依赖 [Wireshark / TShark](https://www.wireshark.org/) 与 [Npcap](https://npcap.com/)。

## 免责声明

本工具仅用于分析自己的抽卡记录。使用第三方工具可能违反游戏的用户协议，请自行判断并承担相应风险。
