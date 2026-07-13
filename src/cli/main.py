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
@click.option("--date", "-d", default=None, help="指定同步日期 (YYYY-MM-DD)")
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


if __name__ == "__main__":
    cli()
