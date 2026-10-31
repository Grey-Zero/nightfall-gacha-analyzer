<img src="frontend/assets/nightfall.svg" width="88" alt="夜幕之下抽卡分析">

# 夜幕之下抽卡分析

一个面向 Windows 的本地抽卡记录工具。它读取本机网卡上与游戏服务器的通信，解析出「契约记录」里的抽卡历史，保存到本地 SQLite 数据库，并按契约类别统计六星间隔和保底进度。

工具不修改游戏文件，也不注入游戏进程，只通过系统抓包驱动读取网络流量。所有记录只保存在本机，不会上传到任何服务器。

## 功能

**采集**

- 一次读取「契约记录 → 全部记录」的全部分页
- 按 TCP 序号重组数据流，重传和乱序不会破坏解析
- 自动校验分页是否连续、是否翻到最后一页
- 支持多个账号（昵称必填，UID 与备注可选），各自独立保存记录，删除账号前会二次确认
- 误导入时可以撤销上一次导入，只移除那次新增的记录

**数据管理**

- 导出抽卡记录（JSON 格式）
- 导出/导入备份（单个 JSON 包含所有账号与记录，换电脑或重装后一键恢复）
- 导出错误信息（JSON 格式），随时重新分析最近一次采集的数据，便于反馈问题
- 清理历史报错文件，释放磁盘空间

**分析**

- 首页概览：总抽数、六星数量、限定/遴选不歪率、各契约类别进度、最近获得的六星
- 按活动契约、常驻契约、遴选契约、新手池分类查看每一次六星的抽数与间隔
- 可切换显示获取时间和途中获得的五星
- 昼夜主题切换

**维护**

- 启动时检查 GitHub Releases，发现新版本会提示并给出下载页，不自动替换任何文件
- 账号数据、配置和抓包都保存在用户目录，解压新版本覆盖程序文件夹不会影响数据

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

升级方式：下载新的 ZIP 解压后覆盖原来的程序文件夹。账号数据保存在 `%APPDATA%\NightfallGachaAnalyzer\`，覆盖程序不会丢数据。

升级注意：从 0.1.x 升级后，首次启动会自动把程序目录里的 `nightfall.db`、`config.json` 和 `captures/` 搬到 `%APPDATA%\NightfallGachaAnalyzer\`，不需要手动迁移。

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

解析失败时，程序会把本次原始抓包保存到用户目录下的 `captures/`，方便定位原因。每次采集结束还会覆盖保存一份 `latest-capture.pcap`，首页的「导出错误信息」会读取它并导出一份报告；如果 `captures/` 里有更新的 pcap/pcapng，则优先使用最新的那个。文件只在本机，问题解决后可以用「清理历史报错」一键删除。

报告包含本机与服务器的网络端点、请求响应配对统计、分页覆盖情况和记录摘要，不包含原始流量。分享前请留意其中的本机 IP 等信息。

**导入了错误的记录怎么办？**

首页「数据管理 → 最近一次导入」会显示上一次导入的时间和新增条数，点「撤销上一次导入」即可移除那次新增的记录。只会处理最近一次导入，更早的记录不会被动。

**换电脑了，记录怎么迁移？**

在旧电脑点「导出备份」，把生成的 JSON 拷到新电脑，在「数据管理」里点「导入备份」。备份包含所有账号（含 UID 和备注）和全部抽卡记录；导入只做合并，重复记录会自动跳过。匹配规则是昵称优先（昵称是账号的唯一标识），如果本机改过昵称，则在这个 UID 恰好只对应一个账号时按 UID 匹配，避免误合并。

**数据存在哪里？**

数据库 `nightfall.db`、配置 `config.json` 和抓包都在用户目录，和程序文件夹分开：

```text
%APPDATA%\NightfallGachaAnalyzer\
  nightfall.db
  config.json
  captures\
```

旧版本把数据放在程序目录里，首次启动新版本会自动搬到上面的位置。删除这个文件夹等于清空所有账号和记录，建议先导出备份。

**升级要重新装一遍吗？**

不用安装。下载新的 ZIP，解压后覆盖原来的程序文件夹即可，数据在用户目录里不受影响。程序启动时会检查有没有新版本，发现更新会在首页顶部提示并给出下载页。

**卸载会不会删掉记录？**

删除程序文件夹即可，用户目录里的数据会保留。如果想彻底清空，再手动删除 `%APPDATA%\NightfallGachaAnalyzer`。

## 从源码运行

需要 Python 3.10 或更新版本：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python desktop.py
```

首次运行会在 `%APPDATA%\NightfallGachaAnalyzer\` 创建 `nightfall.db`；如果程序目录里有旧版本的数据，会自动迁移过去。

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
  diagnostics.py         错误信息报告与历史文件管理
  backup.py              备份导出与恢复
  storage.py             用户数据目录与旧版本数据迁移
  updates.py             新版本检测
  network.py             游戏连接与网卡检测
  database.py            SQLite 存储
  data_service.py        首页与记录页数据
  pity.py                保底与六星间隔统计
  cards.py               卡牌与卡池数据加载
  cli_ui.py              命令行界面
frontend/                PyWebView 界面（HTML/CSS/JS）与图标
data/                    卡牌与卡池元数据（部分由历史记录归纳而来）
tests/                   回归测试
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

发布前请把 `nightfall/config.py` 里的 `APP_VERSION` 改成新版本号，它会写进错误信息报告，也用于后续的更新检测。

## 测试

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

测试不依赖真实账号数据库或抓包文件，仓库中也不保存真实流量。

## 参与贡献

欢迎提交 Issue 反馈问题。如果是解析失败，请附上用户目录 `captures/` 里对应的 pcap 文件，或在首页点「导出错误信息」导出报告，它能直接定位原因。

## 致谢

- 抓包依赖 [Wireshark / TShark](https://www.wireshark.org/) 与 [Npcap](https://npcap.com/)。
- [nightfall-gacha-export](https://github.com/MILImusic/nightfall-gacha-export)：本项目的卡牌表和卡池表有相当一部分来自分析它导出的历史记录。那个项目用 JavaScript + WinDivert 接管流量，体积超过 300 MB，还要做流量重定向，风险和维护成本都不低；这也是本项目改用 Python 只做被动监听的原因——不修改游戏文件、不注入进程、不改动连接，只读取本机网卡上已有的数据。
- 本项目的代码与文档在Copilot的协助下完成，使用 DeepSeek API。它不是人，所以不该出现在贡献者列表里，但确实一起熬了不少夜，谢谢它。

## 免责声明

本工具仅用于分析自己的抽卡记录。使用第三方工具可能违反游戏的用户协议，请自行判断并承担相应风险。
