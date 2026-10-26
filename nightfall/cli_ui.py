"""命令行交互与终端输出"""
from contextlib import contextmanager

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


console = Console()

GROUP_NAMES = {
    "standard": "常驻",
    "selection": "轮替",
    "limited": "限定",
    "starter:10001": "新手",
}


@contextmanager
def waiting_status():
    with console.status("[cyan]等待游戏启动…[/cyan]"):
        yield


def show_title():
    console.print("[bold cyan]夜幕之下抽卡分析[/bold cyan]\n")


def show_capture_timeout():
    console.print("[bold red]超时：未检测到游戏进程或服务器连接[/bold red]")


def show_connection(connection):
    console.print(f"[green]✓[/green] 进程 PID {connection['pid']}，"
                  f"接口 {connection['interface']}")
    for ip, port in connection['endpoints']:
        console.print(f"    [dim]{ip}:{port}[/dim]")
    console.print()


def show_capture_start_error(error):
    console.print(f"[bold red]录制启动失败: {error}[/bold red]")


def show_capture_instructions():
    console.print(Panel(
        "在游戏中进入 [bold]契约 → 契约记录 → 全部记录[/bold]，然后逐页翻到底\n\n"
        "[yellow]只有「全部记录」的数据会被采集[/yellow]，"
        "单个卡池的筛选结果无效",
        title="操作提示", border_style="cyan"))


def wait_for_capture_stop():
    try:
        console.input("\n[bold]翻完后按回车停止捕获[/bold]")
    except KeyboardInterrupt:
        console.print("\n[yellow]已中断[/yellow]")


def show_stopping_capture():
    console.print("\n[cyan]正在停止录制…[/cyan]")


def show_processing_capture():
    console.print("[cyan]正在解析…[/cyan]\n")


def show_parse_error(error):
    console.print(f"[bold red]解析失败: {error}[/bold red]")


def show_no_records(single_pool_count):
    if single_pool_count:
        console.print(Panel(
            f"检测到 [bold]{single_pool_count}[/bold] 个单池查询，"
            f"但没有「全部记录」数据\n\n"
            f"请走 [bold]契约 → 契约记录 → 全部记录[/bold] 重新翻页",
            title="未采集到数据", border_style="yellow"))
    else:
        console.print("[yellow]未捕获到任何记录[/yellow]")


def show_capture_summary(record_count, server_total):
    console.print(f"[green]✓[/green] 捕获 [bold]{record_count}[/bold] 条记录，"
                  f"覆盖 {record_count}/{server_total}\n")


def show_insert_summary(inserted, duplicated):
    console.print(f"[green]✓[/green] 新增 {inserted} 条，重复 {duplicated} 条")


def show_position_direction_warning(violations, total):
    console.print(f"[bold red]![/bold red] position 时间方向假设不成立："
                  f"{total} 条中 {violations} 处违反，保底间隔可能是反的")


def show_position_gaps(position_range):
    console.print(f"[yellow]![/yellow] position 区间 "
                  f"{position_range['min']}–{position_range['max']} "
                  f"内缺 {position_range['missing']} 条")


def show_server_remaining(stored, server_total):
    console.print(f"\n[dim]库内 {stored} 条，服务器共 {server_total} 条。"
                  f"继续翻页可补全剩余 {server_total - stored} 条。[/dim]")


def select_account(db):
    """选择或创建账号，返回 account_id"""
    accounts = db.get_all_accounts()

    if not accounts:
        console.print("[cyan]首次使用，创建账号[/cyan]")
        nickname = console.input("  昵称: ").strip() or "默认账号"
        uid = console.input("  UID（可选，回车跳过）: ").strip() or None
        account_id = db.create_account(nickname, uid)
        console.print(f"[green]✓[/green] 已创建「{nickname}」\n")
        return account_id

    table = Table(title="选择账号", header_style="bold cyan")
    table.add_column("编号", justify="center", width=6)
    table.add_column("昵称", style="cyan")
    table.add_column("UID", style="dim")
    table.add_column("记录数", justify="right")

    for i, acc in enumerate(accounts, 1):
        table.add_row(str(i), acc['nickname'], acc['uid'] or "-",
                      str(db.get_record_count(acc['account_id'])))
    table.add_section()
    table.add_row("0", "[dim]新建账号[/dim]", "", "")
    console.print(table)

    while True:
        choice = console.input("\n输入编号: ").strip()
        if choice == "0":
            nickname = console.input("  昵称: ").strip()
            if not nickname:
                continue
            uid = console.input("  UID（可选，回车跳过）: ").strip() or None
            try:
                return db.create_account(nickname, uid)
            except Exception as e:
                console.print(f"[red]创建失败: {e}[/red]")
                continue
        try:
            return accounts[int(choice) - 1]['account_id']
        except (ValueError, IndexError):
            console.print("[red]编号无效[/red]")


def show_pity(db, account_id):
    """展示保底分析"""
    console.print()
    results = db.analyze_pity(account_id)
    if not results:
        console.print("[yellow]暂无可分析的记录[/yellow]")
        return

    table = Table(title="保底进度", header_style="bold green")
    table.add_column("保底组", style="cyan")
    table.add_column("抽数", justify="right")
    table.add_column("六星", justify="right")
    table.add_column("已垫", justify="right")

    for group, data in sorted(results.items()):
        pity_text = ("[dim]已关闭[/dim]" if data['completed']
                     else f"{data['current_pity']} / {data['cap']}")

        table.add_row(GROUP_NAMES.get(group, group),
                      str(data['pulls']),
                      str(len(data['six_star_intervals'])),
                      pity_text)

    console.print(table)

    guarantee = results.get("limited", {}).get("guarantee")
    if not guarantee:
        return

    state = ("[bold yellow]大保底[/bold yellow]（下次六星必定是限定）"
             if guarantee['guaranteed']
             else "[green]小保底[/green]（下次六星可能歪成常驻）")

    lines = [
        f"当前状态: {state}",
        f"抽中限定 {guarantee['featured_hits']} 次，"
        f"歪出常驻 {guarantee['off_banner']} 次",
    ]

    if guarantee['anomalies']:
        lines.append(f"[bold red]![/bold red] {len(guarantee['anomalies'])} 处状态矛盾："
                     f"处于大保底却歪出常驻六星\n"
                     f"   说明 STANDARD_SIX_STARS 名单需要补充")

    console.print(Panel("\n".join(lines), title="限定池保底",
                        border_style="magenta"))
