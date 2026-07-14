"""CLI 入口 — 基于 Click 框架。

命令列表:
    setup         一次性初始化（数据库 + 飞书多维表格）
    test-feishu   测试飞书连接
    test-collect  测试数据采集（干跑）
    run           执行一次完整的采集→同步
    start         启动定时调度器
    status        查看调度器状态
"""

import sys
from pathlib import Path

# Windows GBK 编码兼容
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import click

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@click.group()
@click.version_option(version="0.1.0", prog_name="xhs-feishu")
def cli():
    """小红书 → 飞书多维表格 数据自动同步工具。

    自动采集小红书账号数据，统计后同步到飞书多维表格。
    """
    pass


@cli.command()
def setup():
    """一次性初始化：创建本地数据库和飞书多维表格结构。"""
    from src.core.config import load_config
    from src.core.logging import setup_logging

    config = load_config()
    setup_logging(config.logging)

    click.echo("=" * 60)
    click.echo("  初始化 — 小红书 → 飞书数据同步工具")
    click.echo("=" * 60)

    # 1. 初始化 SQLite
    click.echo("\n[1/2] 初始化本地数据库...")
    from src.storage.sqlite import Database

    db = Database(config.storage.sqlite_path)
    db.init()
    click.echo(f"  ✓ SQLite 数据库已就绪: {db.db_path}")

    # 2. 初始化飞书多维表格
    click.echo("\n[2/2] 初始化飞书多维表格...")
    try:
        from src.loaders.bitable_schema import BitableSchemaManager

        manager = BitableSchemaManager()
        table_ids = manager.setup_all_tables()
        click.echo(f"  ✓ 飞书多维表格已就绪: {len(table_ids)} 张表")
        for key, tid in table_ids.items():
            click.echo(f"    - {key}: {tid}")
    except Exception as e:
        click.echo(f"  ⚠ 飞书初始化失败 (请检查 .env 配置): {e}")

    click.echo(f"\n✓ 初始化完成！")


@cli.command()
def test_feishu():
    """测试飞书多维表格连接和权限。"""
    from src.core.config import load_config
    from src.core.logging import setup_logging

    config = load_config()
    setup_logging(config.logging)

    click.echo("测试飞书多维表格连接...")

    try:
        from src.loaders.bitable_client import BitableClient

        client = BitableClient(config.feishu)
        token = client.ensure_token()
        click.echo(f"  ✓ Token 获取成功 (前8位: {token[:8]}...)")

        tables = client.list_tables()
        click.echo(f"  ✓ 多维表格访问成功，共 {len(tables)} 张表:")
        for t in tables:
            click.echo(f"    - [{t['table_id']}] {t['name']}")

        click.echo("\n✓ 飞书连接测试通过！")
    except Exception as e:
        click.echo(f"\n✗ 连接测试失败: {e}")
        sys.exit(1)


@cli.command()
@click.option("--account", "-a", default=None, help="仅测试指定账号ID")
def test_collect(account: str | None):
    """测试数据采集（干跑模式，输出到控制台/日志）。"""
    import asyncio
    import logging

    from src.core.config import load_accounts, load_config
    from src.core.logging import setup_logging

    config = load_config()
    setup_logging(config.logging)
    logger = logging.getLogger(__name__)
    accounts_cfg = load_accounts()

    all_accounts = accounts_cfg.all_accounts
    if account:
        all_accounts = [a for a in all_accounts if a.account_id == account]
        if not all_accounts:
            click.echo(f"✗ 找不到账号: {account}")
            sys.exit(1)

    click.echo(f"将采集 {len(all_accounts)} 个账号的数据（干跑模式）:\n")
    for acc in all_accounts:
        tag = "🏷 自有" if not acc.competitor else "🔍 竞品"
        click.echo(f"  [{tag}] {acc.display_name} (ID: {acc.xhs_user_id})")

    click.echo(f"\n采集策略: {config.collection.strategy}")

    async def _test():
        from src.collectors.factory import create_collector

        collector = create_collector()
        valid = await collector.validate_connection()
        if valid:
            click.echo("  ✓ 数据源连接正常")
        else:
            click.echo("  ⚠ 数据源连接失败，请检查配置")

        for acc in all_accounts:
            click.echo(f"\n--- {acc.display_name} ---")
            try:
                result = await collector.collect_all(acc)
                if result.profile:
                    click.echo(
                        f"  粉丝: {result.profile.follower_count:,}  |  "
                        f"关注: {result.profile.following_count:,}  |  "
                        f"获赞: {result.profile.total_likes:,}"
                    )
                else:
                    click.echo("  ⚠ 未获取到账号数据")
                click.echo(f"  笔记: {len(result.notes)} 篇")
                if result.errors:
                    for err in result.errors:
                        click.echo(f"  ⚠ {err}")
            except Exception as e:
                click.echo(f"  ✗ 采集失败: {e}")

        if hasattr(collector, "close"):
            await collector.close()

    asyncio.run(_test())
    click.echo("\n干跑完成。请检查日志确认数据。")


@cli.command()
@click.option("--date", "-d", default=None, help="仅同步指定日期的笔记 (YYYY-MM-DD)，不传则导入全部")
def run(date: str | None):
    """执行一次完整的数据采集→转换→同步流程。"""
    import asyncio
    import logging
    from datetime import date as date_type, datetime

    from src.core.config import load_accounts, load_config
    from src.core.logging import setup_logging

    config = load_config()
    setup_logging(config.logging)
    logger = logging.getLogger(__name__)

    target_date = None
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            click.echo(f"✗ 日期格式错误: {date}，请使用 YYYY-MM-DD 格式")
            sys.exit(1)

    logger.info("=" * 50)
    logger.info("开始执行数据同步: %s", (target_date or date_type.today()).isoformat())
    logger.info("=" * 50)

    accounts_cfg = load_accounts()
    all_accounts = accounts_cfg.all_accounts
    if not all_accounts:
        click.echo("⚠ 没有配置任何监控账号。请在 config/accounts.yaml 中添加账号。")
        return

    click.echo(f"将处理 {len(all_accounts)} 个账号\n")

    async def _run():
        from src.core.pipeline import run_pipeline
        from src.notifiers.feishu_bot import FeishuBotNotifier

        result = await run_pipeline(target_date)

        click.echo(f"\n{'=' * 50}")
        click.echo(
            f"同步完成: 总计={result['total']}, "
            f"成功={result['success']}, 失败={result['failed']}"
        )

        for d in result.get("details", []):
            icon = "✓" if d["status"] == "success" else "✗"
            click.echo(
                f"  [{icon}] {d['account_id']}: "
                f"notes={d.get('notes_synced', 0)}, "
                f"errors={len(d.get('errors', []))}"
            )

        # 发送日报
        if result.get("total", 0) > 0:
            notifier = FeishuBotNotifier()
            highlights = []
            notifier.send_daily_summary(
                run_date=target_date or date_type.today(),
                total_accounts=result["total"],
                success_count=result["success"],
                failed_count=result["failed"],
                highlights=highlights,
            )

    asyncio.run(_run())
    click.echo("\n✓ 完成")


@cli.command()
def start():
    """启动定时调度器（后台常驻进程）。"""
    import logging

    from src.core.config import load_config
    from src.core.logging import setup_logging

    config = load_config()
    setup_logging(config.logging)
    logger = logging.getLogger(__name__)

    click.echo("启动定时调度器...")
    click.echo(f"调度计划: {config.schedule.cron} ({config.schedule.timezone})")
    click.echo("按 Ctrl+C 停止\n")

    try:
        from src.scheduler.jobs import start_scheduler
        start_scheduler()
    except KeyboardInterrupt:
        click.echo("\n调度器已停止")
    except Exception as e:
        click.echo(f"\n✗ 调度器启动失败: {e}")
        sys.exit(1)


@cli.command()
def status():
    """查看数据同步状态（上次运行时间、各账号同步状态）。"""
    import logging

    from src.core.config import load_config
    from src.core.logging import setup_logging

    config = load_config()
    setup_logging(config.logging)

    click.echo("数据同步状态:\n")

    try:
        from src.storage.sqlite import Database, SyncStateRepo

        db = Database(config.storage.sqlite_path)
        db.init()
        with db.session() as session:
            repo = SyncStateRepo(session)
            from src.storage.models import SyncState
            states = session.query(SyncState).all()

            if not states:
                click.echo("  暂无同步记录。运行 'xhs-feishu run' 开始首次同步。")
                return

            for s in states:
                icon = "✓" if s.sync_status == "success" else "✗"
                click.echo(
                    f"  [{icon}] {s.account_id} | "
                    f"上次同步: {s.last_synced_at or 'N/A'} | "
                    f"快照日期: {s.last_snapshot_date or 'N/A'}"
                )
                if s.error_message:
                    click.echo(f"      错误: {s.error_message}")
    except Exception as e:
        click.echo(f"✗ 查询失败: {e}")
        sys.exit(1)


@cli.command()
@click.option("--account", "-a", "accounts", multiple=True, help="要清理的账号名（可多次指定），如 --account test_brand")
@click.option("--table", "-t", "table_filter", default=None, help="仅清理指定表: account_summary/note_metrics/daily_snapshot/competitor_comparison")
@click.option("--confirm", is_flag=True, default=False, help="必须显式传入才执行真正删除，否则仅预览")
@click.option("--keep-local", is_flag=True, default=False, help="保留本地 SQLite 数据，仅清理飞书")
def clear(accounts: tuple[str, ...], table_filter: str | None, confirm: bool, keep_local: bool):
    """清理飞书多维表格中的指定账号数据（同时清理本地 SQLite）。

    默认干跑模式：只展示会被删除的记录，不执行删除。
    必须传入 --confirm 才会真正执行。

    示例：
      xhs-feishu clear --account test_brand               # 预览
      xhs-feishu clear --account test_brand --confirm     # 执行删除
      xhs-feishu clear -a acc1 -a acc2 --table note_metrics --confirm
    """
    import logging
    import sys

    from src.core.config import load_config
    from src.core.logging import setup_logging
    from src.loaders.bitable_client import BitableClient
    from src.storage.models import AccountSnapshot, NoteInfo, NoteSnapshot, SyncState
    from src.storage.sqlite import Database

    config = load_config()
    setup_logging(config.logging)
    logger = logging.getLogger(__name__)

    if not accounts:
        click.echo("✗ 请用 --account 指定要清理的账号名（可多次传），如: --account test_brand")
        click.echo("  提示：用 xhs-feishu status 查看当前有哪些账号的同步记录")
        sys.exit(1)

    # ── 表名映射 ──
    table_zh_names = {
        "account_summary": "账号概览",
        "note_metrics": "笔记数据明细",
        "daily_snapshot": "每日快照",
        "competitor_comparison": "竞品对比",
    }
    # 各表用于匹配账号的字段
    table_account_field = {
        "account_summary": "账号名称",
        "note_metrics": "所属账号",
        "daily_snapshot": "账号名称",
        "competitor_comparison": "账号名称",
    }

    target_tables = [table_filter] if table_filter else list(table_zh_names.keys())
    # 校验表名
    for t in target_tables:
        if t not in table_zh_names:
            click.echo(f"✗ 无效表名: {t}，可选值: {', '.join(table_zh_names.keys())}")
            sys.exit(1)

    click.echo("=" * 60)
    click.echo("  清理飞书多维表格 + 本地 SQLite 数据")
    click.echo("=" * 60)
    click.echo(f"\n  目标账号: {', '.join(accounts)}")
    click.echo(f"  目标表:   {', '.join(table_zh_names[t] for t in target_tables)}")
    click.echo(f"  模式:     {'🔍 干跑预览 (加 --confirm 执行)' if not confirm else '⚠ 确认删除'}")

    # ── 连接飞书 ──
    click.echo("\n[1/3] 连接飞书多维表格...")
    try:
        client = BitableClient(config.feishu)
        client.ensure_token()
        tables = client.list_tables()
        name_to_id = {t["name"]: t["table_id"] for t in tables}
        click.echo(f"  ✓ 已连接，共 {len(tables)} 张表")
    except Exception as e:
        click.echo(f"\n✗ 连接飞书失败: {e}")
        sys.exit(1)

    # ── 扫描记录 ──
    click.echo("\n[2/3] 扫描待删除记录...")
    deletion_plan: dict[str, list[dict]] = {}  # {table_key: [{"record_id": ..., "fields": ...}, ...]}
    not_found_tables: list[str] = []

    for table_key in target_tables:
        zh_name = table_zh_names[table_key]
        if zh_name not in name_to_id:
            click.echo(f"  ⚠ 飞书中未找到表: {zh_name}，跳过")
            not_found_tables.append(table_key)
            continue

        table_id = name_to_id[zh_name]
        match_field = table_account_field[table_key]
        matched: list[dict] = []

        # 分页拉取全表记录
        page_token = None
        page_count = 0
        while True:
            result = client.list_records(table_id, page_token=page_token)
            for rec in result["records"]:
                field_value = str(rec["fields"].get(match_field, ""))
                if field_value in accounts:
                    matched.append(rec)
            page_count += 1
            if not result["has_more"]:
                break
            page_token = result["page_token"]

        deletion_plan[table_key] = matched
        click.echo(f"  {zh_name}: {len(matched)} 条记录")

    # ── 汇总 ──
    total_feishu = sum(len(v) for v in deletion_plan.values())
    click.echo(f"\n  ─────────────────────")
    click.echo(f"  飞书待删除合计: {total_feishu} 条")

    # 统计 SQLite 待删除数
    total_sqlite = 0
    if not keep_local:
        try:
            db = Database(config.storage.sqlite_path)
            db.init()
            with db.session() as session:
                for acc in accounts:
                    snapshots = session.query(AccountSnapshot).filter_by(account_id=acc).count()
                    notes = session.query(NoteInfo).filter_by(account_id=acc).count()
                    note_ss = session.query(NoteSnapshot).filter_by(account_id=acc).count()
                    sync = session.query(SyncState).filter_by(account_id=acc).count()
                    total_sqlite += snapshots + notes + note_ss + sync
            click.echo(f"  本地 SQLite 待删除合计: {total_sqlite} 条")
            click.echo(f"    (AccountSnapshot + NoteInfo + NoteSnapshot + SyncState)")
        except Exception as e:
            click.echo(f"  ⚠ 无法统计 SQLite 数据: {e}")
    else:
        click.echo(f"  本地 SQLite: 跳过 (--keep-local)")

    click.echo(f"\n  ─────────────────────")
    click.echo(f"  总计: {total_feishu + total_sqlite} 条记录将被删除")

    if total_feishu == 0 and total_sqlite == 0:
        click.echo("\n✓ 没有需要清理的数据。")
        return

    # ── 干跑模式 → 停止 ──
    if not confirm:
        click.echo(f"\n🔍 干跑完成。以上记录将会被删除。")
        click.echo(f"   如需执行删除，请加上 --confirm 参数。")
        return

    # ── 确认执行 ──
    click.echo(f"\n⚠ 即将删除以上全部数据，此操作不可恢复！")
    click.echo("=" * 60)

    # ── 删除飞书记录 ──
    if total_feishu > 0:
        click.echo("\n[3/3] 执行删除...")
        feishu_deleted = 0
        feishu_failed = 0

        for table_key in target_tables:
            records = deletion_plan.get(table_key, [])
            if not records:
                continue

            zh_name = table_zh_names[table_key]
            if zh_name not in name_to_id:
                continue
            table_id = name_to_id[zh_name]
            record_ids = [r["record_id"] for r in records]

            # 分批删除（每批最多 500 条）
            batch_size = 500
            for i in range(0, len(record_ids), batch_size):
                batch = record_ids[i : i + batch_size]
                try:
                    result = client.batch_delete_records(table_id, batch)
                    deleted_count = sum(1 for r in result if r.get("deleted"))
                    feishu_deleted += deleted_count
                    failed_in_batch = len(batch) - deleted_count
                    feishu_failed += failed_in_batch
                    click.echo(f"  ✓ {zh_name}: {deleted_count}/{len(batch)} 条已删除" +
                               (f", {failed_in_batch} 条失败" if failed_in_batch else ""))
                    # 大批次间加延迟避免限流
                    if len(batch) >= 400 and i + batch_size < len(record_ids):
                        import time
                        time.sleep(0.5)
                except Exception as e:
                    click.echo(f"  ✗ {zh_name} 批次删除失败: {e}")
                    feishu_failed += len(batch)

        click.echo(f"\n  飞书删除: {feishu_deleted} 条成功, {feishu_failed} 条失败")
    else:
        click.echo("\n[3/3] 飞书无数据需删除，跳过。")

    # ── 清理 SQLite ──
    if not keep_local and total_sqlite > 0:
        click.echo("\n  清理本地 SQLite...")
        try:
            db = Database(config.storage.sqlite_path)
            db.init()
            with db.session() as session:
                for acc in accounts:
                    # 按顺序删除：先删子表再删主表
                    deleted_ns = session.query(NoteSnapshot).filter_by(account_id=acc).delete()
                    deleted_ni = session.query(NoteInfo).filter_by(account_id=acc).delete()
                    deleted_as = session.query(AccountSnapshot).filter_by(account_id=acc).delete()
                    deleted_ss = session.query(SyncState).filter_by(account_id=acc).delete()
                    total = deleted_ns + deleted_ni + deleted_as + deleted_ss
                    if total > 0:
                        click.echo(f"  ✓ {acc}: {total} 条已删除 " +
                                   f"(快照{deleted_as}+笔记{deleted_ni}+笔记快照{deleted_ns}+同步{deleted_ss})")
                session.commit()
            click.echo("  ✓ SQLite 清理完成")
        except Exception as e:
            click.echo(f"  ✗ SQLite 清理失败: {e}")

    click.echo(f"\n{'=' * 60}")
    click.echo("✓ 清理完成")
    click.echo(f"{'=' * 60}")


if __name__ == "__main__":
    cli()
