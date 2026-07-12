"""数据同步 Pipeline 编排器。

串联采集 → 转换 → 存储 → 同步的完整流程。
支持单账号独立运行和全部账号批量运行。
"""

import asyncio
import logging
from datetime import date
from typing import Optional

from src.collectors.factory import create_collector
from src.collectors.models import CollectResult
from src.core.config import AccountInfo, load_accounts, load_config
from src.core.exceptions import XHSFeishuSyncError
from src.loaders.sync_engine import SyncEngine
from src.storage.models import AccountSnapshot, NoteInfo, NoteSnapshot, SyncState
from src.storage.sqlite import (
    AccountSnapshotRepo,
    Database,
    NoteInfoRepo,
    NoteSnapshotRepo,
    SyncStateRepo,
    get_db,
)
from src.transformers.competitor import CompetitorAnalyzer, CompetitorRank, ComparisonTable
from src.transformers.normalizer import (
    normalize_collect_result,
    validate_account_profile,
)
from src.transformers.trend_calculator import (
    AccountTrends,
    NoteTrends,
    TrendCalculator,
)

logger = logging.getLogger(__name__)


class PipelineRunner:
    """同步流水线编排器。

    用法:
        runner = PipelineRunner()
        results = await runner.run_all_accounts()
        # 或
        result = await runner.run_single_account("main_brand")
    """

    def __init__(self, target_date: Optional[date] = None):
        self.target_date = target_date or date.today()
        self.config = load_config()
        self.db = get_db()
        self.collector = create_collector()
        self.sync_engine = SyncEngine()
        self.trend_calc = TrendCalculator(history_days=30)
        self.competitor_analyzer = CompetitorAnalyzer()

    async def run_single_account(
        self, account: AccountInfo
    ) -> dict:
        """运行单个账号的完整采集→同步流程。

        Returns:
            执行结果字典
        """
        result = {
            "account_id": account.account_id,
            "status": "pending",
            "profile_synced": False,
            "notes_synced": 0,
            "errors": [],
        }

        logger.info("=" * 50)
        logger.info("处理账号: %s (%s)", account.display_name, account.account_id)
        logger.info("=" * 50)

        try:
            # Step 1: 采集数据
            collect_result = await self.collector.collect_all(
                account, self.target_date
            )
            if not collect_result.success:
                for err in collect_result.errors:
                    logger.warning("采集警告: %s", err)
                    result["errors"].append(err)

            if collect_result.profile:
                profile_warnings = validate_account_profile(collect_result.profile)
                for w in profile_warnings:
                    logger.warning(w)

            # Step 2: 标准化并存入 SQLite
            account_snapshot, note_infos, note_snapshots = normalize_collect_result(
                collect_result, self.target_date
            )

            if not account_snapshot:
                result["status"] = "skipped"
                result["errors"].append("未采集到账号数据")
                return result

            with self.db.session() as session:
                # 存账号快照
                account_repo = AccountSnapshotRepo(session)
                account_repo.save(account_snapshot)

                # 存笔记信息
                note_info_repo = NoteInfoRepo(session)
                for info in note_infos:
                    note_info_repo.save(info)

                # 存笔记快照
                note_repo = NoteSnapshotRepo(session)
                for snap in note_snapshots:
                    note_repo.save(snap)

                # Step 3: 计算趋势
                prev_snapshot = account_repo.get_previous(
                    account.account_id, self.target_date, offset_days=1
                )
                week_ago_snapshot = account_repo.get_previous(
                    account.account_id, self.target_date, offset_days=7
                )
                history = account_repo.get_history(account.account_id, days=30)

                trends = self.trend_calc.calculate_account_trends(
                    account_snapshot, prev_snapshot, week_ago_snapshot, history
                )

                # 笔记趋势
                note_trends_map: dict[str, NoteTrends] = {}
                for snap in note_snapshots:
                    prev_note = note_repo.get_previous(
                        snap.note_id, self.target_date, offset_days=1
                    )
                    week_note = note_repo.get_previous(
                        snap.note_id, self.target_date, offset_days=7
                    )
                    note_trends_map[snap.note_id] = self.trend_calc.calculate_note_trends(
                        snap, prev_note, week_note
                    )

                # Step 4: 同步到飞书
                sync_results = self.sync_engine.sync_full_pipeline(
                    account_snapshot=account_snapshot,
                    note_infos=note_infos,
                    note_snapshots=note_snapshots,
                    trends=trends,
                    note_trends_map=note_trends_map,
                )

                # Step 5: 更新同步状态
                sync_repo = SyncStateRepo(session)
                sync_repo.update(
                    account.account_id,
                    status="success",
                    snapshot_date=self.target_date,
                )

                session.commit()

            result["status"] = "success"
            result["profile_synced"] = True
            result["notes_synced"] = sync_results.get("note_metrics", 0)

            logger.info(
                "✓ 账号 %s 处理完成: profile=%s, notes=%d",
                account.display_name,
                result["profile_synced"],
                result["notes_synced"],
            )

        except Exception as e:
            logger.exception("账号 %s 处理失败", account.display_name)
            result["status"] = "failed"
            result["errors"].append(str(e))

            # 记录失败状态
            try:
                with self.db.session() as session:
                    sync_repo = SyncStateRepo(session)
                    sync_repo.update(
                        account.account_id,
                        status="failed",
                        snapshot_date=self.target_date,
                        error_message=str(e)[:500],
                    )
                    session.commit()
            except Exception:
                pass

        return result

    async def run_all_accounts(self) -> dict:
        """运行所有配置账号的采集→同步流程。

        Returns:
            {"total": N, "success": N, "failed": N, "details": [...]}
        """
        accounts_cfg = load_accounts()
        all_accounts = accounts_cfg.all_accounts

        if not all_accounts:
            logger.warning("没有配置任何监控账号。请在 config/accounts.yaml 中添加账号。")
            return {"total": 0, "success": 0, "failed": 0, "details": []}

        logger.info("开始批量处理 %d 个账号", len(all_accounts))

        # 先处理自有账号，再处理竞品
        own = accounts_cfg.own_accounts
        competitors = accounts_cfg.competitor_accounts
        ordered_accounts = own + competitors

        details = []
        success_count = 0
        failed_count = 0

        for i, account in enumerate(ordered_accounts):
            tag = "自有" if not account.competitor else "竞品"
            logger.info("[%d/%d] %s账号: %s", i + 1, len(ordered_accounts), tag, account.display_name)

            detail = await self.run_single_account(account)
            details.append(detail)

            if detail["status"] == "success":
                success_count += 1
            elif detail["status"] == "failed":
                failed_count += 1

            # 账号间等待（反爬）
            if i < len(ordered_accounts) - 1:
                import random
                delay = random.uniform(3, 8)
                logger.debug("等待 %.1f 秒后处理下一个账号...", delay)
                await asyncio.sleep(delay)

        # Step 6: 竞品对比汇总
        if competitors:
            try:
                await self._run_competitor_sync(competitors)
            except Exception as e:
                logger.error("竞品对比同步失败: %s", e)

        summary = {
            "total": len(all_accounts),
            "success": success_count,
            "failed": failed_count,
            "details": details,
        }

        logger.info("=" * 50)
        logger.info(
            "批量处理完成: 总计=%d, 成功=%d, 失败=%d",
            summary["total"], summary["success"], summary["failed"],
        )

        return summary

    async def _run_competitor_sync(self, competitors: list[AccountInfo]) -> None:
        """执行竞品对比同步。"""
        with self.db.session() as session:
            account_repo = AccountSnapshotRepo(session)
            note_repo = NoteSnapshotRepo(session)

            current_snapshots = []
            notes_by_account: dict[str, list[NoteSnapshot]] = {}

            for acc in competitors:
                snap = account_repo.get_by_account_date(acc.account_id, self.target_date)
                if snap:
                    current_snapshots.append(snap)
                notes = note_repo.get_all_for_date(self.target_date)
                notes_by_account[acc.account_id] = [
                    n for n in notes if n.account_id == acc.account_id
                ]

            if not current_snapshots:
                logger.info("无竞品快照数据，跳过竞品对比")
                return

            # 昨日排名
            yesterday = date.today() if self.target_date > date.today() else (
                self.target_date
            )
            # 这里简化处理，获取之前排名
            comparison = self.competitor_analyzer.build_comparison(
                current_snapshots, notes_by_account,
            )

            self.sync_engine.sync_competitor_comparison(comparison)
            logger.info("竞品对比同步完成: %d 个竞品", len(comparison.rankings) if comparison else 0)

    async def close(self):
        """清理资源。"""
        if hasattr(self.collector, "close"):
            await self.collector.close()


async def run_pipeline(target_date: Optional[date] = None) -> dict:
    """快捷入口: 运行一次完整 Pipeline。"""
    runner = PipelineRunner(target_date)
    try:
        return await runner.run_all_accounts()
    finally:
        await runner.close()
