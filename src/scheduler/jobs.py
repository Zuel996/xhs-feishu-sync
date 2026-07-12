"""APScheduler 定时任务定义。

每日定时触发采集→同步流水线，并推送日报通知。
"""

import asyncio
import logging
from datetime import date

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from src.core.config import load_config
from src.core.logging import setup_logging
from src.core.pipeline import run_pipeline
from src.notifiers.feishu_bot import FeishuBotNotifier

logger = logging.getLogger(__name__)


def _run_sync_job():
    """定时任务执行函数 — 同步入口。"""
    config = load_config()
    setup_logging(config.logging)

    logger.info("=== 定时同步任务开始 ===")
    notifier = FeishuBotNotifier()

    try:
        # asyncio.run 在同步函数中运行异步 Pipeline
        result = asyncio.run(run_pipeline())

        # 提取高亮数据
        highlights = []
        if result.get("details"):
            # 找涨粉最多的账号
            best = None
            for d in result.get("details", []):
                if d["status"] == "success":
                    if best is None:
                        best = d
            if best:
                highlights.append({
                    "label": "同步成功",
                    "value": f"{best['account_id']} ({best['notes_synced']} 篇笔记)",
                })

        if result.get("total", 0) > 0:
            notifier.send_daily_summary(
                run_date=date.today(),
                total_accounts=result.get("total", 0),
                success_count=result.get("success", 0),
                failed_count=result.get("failed", 0),
                highlights=highlights,
            )
        else:
            notifier.send_text(
                "⚠️ 数据同步提示",
                "未配置监控账号或所有账号同步失败。\n"
                "请检查 config/accounts.yaml 配置。",
            )

    except Exception as e:
        logger.exception("定时同步任务异常")
        notifier.send_error_alert(
            step="定时同步任务",
            error_message=str(e),
        )

    logger.info("=== 定时同步任务结束 ===")


def _job_listener(event):
    """APScheduler 事件监听器。"""
    if event.exception:
        logger.error("定时任务执行异常: %s", event.exception)
        notifier = FeishuBotNotifier()
        notifier.send_error_alert(
            step="Scheduler",
            error_message=str(event.exception),
        )


def create_scheduler() -> BackgroundScheduler:
    """创建并配置后台调度器。

    Returns:
        已配置但未启动的 BackgroundScheduler 实例
    """
    config = load_config()
    sched_cfg = config.schedule

    scheduler = BackgroundScheduler(
        timezone=sched_cfg.timezone,
        job_defaults={
            "max_instances": 1,
            "coalesce": sched_cfg.coalesce,
            "misfire_grace_time": sched_cfg.misfire_grace_time,
        },
    )

    # 添加定时任务
    scheduler.add_job(
        _run_sync_job,
        trigger=CronTrigger.from_crontab(sched_cfg.cron, timezone=sched_cfg.timezone),
        id="daily_xhs_sync",
        name="小红书数据每日同步",
        replace_existing=True,
    )

    # 注册事件监听
    scheduler.add_listener(_job_listener, EVENT_JOB_ERROR)

    logger.info(
        "调度器已配置: cron='%s', tz=%s, coalesce=%s",
        sched_cfg.cron, sched_cfg.timezone, sched_cfg.coalesce,
    )
    logger.info("已注册任务: daily_xhs_sync (小红书数据每日同步)")

    return scheduler


def start_scheduler():
    """启动后台调度器（阻塞）。"""
    scheduler = create_scheduler()
    scheduler.start()

    logger.info("=" * 50)
    logger.info("  调度器已启动 — 等待定时触发...")
    logger.info("  按 Ctrl+C 停止")
    logger.info("=" * 50)

    # 打印下次运行时间
    job = scheduler.get_job("daily_xhs_sync")
    if job:
        logger.info("下次运行时间: %s", job.next_run_time)

    try:
        # 保持主线程
        import time
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("正在关闭调度器...")
        scheduler.shutdown()
        logger.info("调度器已关闭")
