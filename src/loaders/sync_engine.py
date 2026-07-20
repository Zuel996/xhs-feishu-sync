"""飞书多维表格同步引擎。

核心逻辑:
1. Diff 计算: 对比 SQLite 中新数据 vs 最后同步状态
2. 增量写入: 仅将变更记录同步到飞书 Bitable
3. 批量 Upsert: 匹配已有记录 → 更新，否则 → 创建
4. 幂等性: note_id + snapshot_date 复合键去重
5. 冲突解决: Last-write-wins（最新采集数据覆盖）
"""

import logging
from datetime import date, datetime
from typing import Optional


def _to_timestamp(d: date | datetime | None) -> int:
    """将日期/时间转为飞书 DateTime 字段所需的毫秒时间戳。"""
    if d is None:
        return 0
    if isinstance(d, datetime):
        return int(d.timestamp() * 1000)
    if isinstance(d, date):
        return int(datetime(d.year, d.month, d.day).timestamp() * 1000)
    return 0


def _to_timestamp_str(d: date | datetime | None) -> str:
    """将日期/时间转为飞书 DateTime 字段所需的毫秒时间戳字符串。

    因为部分飞书 API 场景下 DateTime 字段接受字符串形式的时间戳。
    """
    return str(_to_timestamp(d))

from src.core.config import load_accounts, load_config
from src.core.exceptions import SyncEngineError
from src.core.exceptions import FeishuAuthError, XHSFeishuSyncError
from src.loaders.bitable_client import BitableClient, get_bitable_client
from src.storage.models import AccountSnapshot, NoteInfo, NoteSnapshot, SyncState
from src.storage.sqlite import (
    AccountSnapshotRepo,
    NoteInfoRepo,
    NoteSnapshotRepo,
    SyncStateRepo,
    get_db,
)
from src.transformers.competitor import ComparisonTable, CompetitorAnalyzer
from src.transformers.trend_calculator import (
    AccountTrends,
    NoteTrends,
    TrendCalculator,
)

logger = logging.getLogger(__name__)


class SyncEngine:
    """数据同步引擎。

    用法:
        engine = SyncEngine(client, db)
        result = engine.sync_account(account_id, account_snapshot, note_infos, note_snapshots)
    """

    # 表名映射
    TABLE_MAP = {
        "account_summary": "tbl_account_summary",
        "note_metrics": "tbl_note_metrics",
        "daily_snapshot": "tbl_daily_snapshot",
        "competitor_comparison": "tbl_competitor_comparison",
    }

    def __init__(
        self,
        client: Optional[BitableClient] = None,
        table_ids: Optional[dict[str, str]] = None,
    ):
        self._enabled: Optional[bool] = None
        self._client: Optional[BitableClient] = None
        self._table_ids: dict[str, str] = {}

        if client is not None:
            self._client = client
            self._enabled = True
        else:
            try:
                self._client = get_bitable_client()
                self._enabled = True
            except XHSFeishuSyncError:
                self._enabled = False
                logger.info(
                    "飞书凭证未配置，SyncEngine 以离线模式运行。"
                    "设置 .env 中的 FEISHU_APP_ID/FEISHU_APP_SECRET 后自动启用。"
                )

        # 表ID映射: 如未提供则通过 list_tables 自动查找
        if self._enabled:
            self._table_ids = table_ids or self._resolve_table_ids()
        else:
            self._table_ids = table_ids or {}

    @property
    def enabled(self) -> bool:
        """飞书同步是否可用。"""
        return self._enabled

    @property
    def client(self) -> Optional[BitableClient]:
        return self._client

    @property
    def table_ids(self) -> dict[str, str]:
        return self._table_ids

    def _resolve_table_ids(self) -> dict[str, str]:
        """通过飞书 API 查找已存在的表ID。"""
        if not self._client:
            return {}
        tables = self._client.list_tables()
        name_to_id = {t["name"]: t["table_id"] for t in tables}

        result = {}
        schema_map = {
            "account_summary": "账号概览",
            "note_metrics": "笔记数据明细",
            "daily_snapshot": "每日快照",
            "competitor_comparison": "竞品对比",
        }

        for key, table_name in schema_map.items():
            if table_name in name_to_id:
                result[key] = name_to_id[table_name]
                logger.debug("表映射: %s -> %s", key, name_to_id[table_name])
            else:
                logger.warning("未找到表: %s，将在同步时跳过", table_name)

        return result

    # ── 同步逻辑 ──

    def sync_account_summary(
        self, trends: AccountTrends, competitor_rank: Optional[int] = None,
        rank_change: str = "不变",
    ) -> int:
        """同步账号概览表（单行 upsert）。

        Returns: 同步的记录数
        """
        if not self.enabled:
            return 0
        table_id = self.table_ids.get("account_summary")
        if not table_id:
            raise SyncEngineError("找不到 account_summary 表")

        fields = {
            "平台": "xiaohongshu",
            "账号名称": trends.account_id,
            "粉丝数": trends.follower.current_value,
            "关注数": trends.following.current_value,
            "获赞与收藏": trends.total_likes.current_value + trends.total_collections.current_value,
            "粉丝日增量": trends.follower.dod_delta,
            "粉丝周增量": trends.follower.wow_delta,
            "粉丝增长率(%)": trends.follower.dod_rate,
            "数据更新时间": _to_timestamp(datetime.now()),
            "异常标记": trends.has_anomaly,
        }

        if competitor_rank is not None:
            fields["竞品排名"] = competitor_rank
            fields["排名变化"] = rank_change

        records = [{"fields": fields}]
        result = self.client.upsert_records(table_id, records, match_field="账号名称")
        logger.info(
            "账号概览同步: %s (created=%d, updated=%d)",
            trends.account_id, result.get("created", 0), result.get("updated", 0),
        )
        return result.get("created", 0) + result.get("updated", 0)

    def sync_note_metrics(
        self,
        notes: list[tuple[NoteInfo, NoteSnapshot, Optional[NoteTrends]]],
    ) -> int:
        """同步笔记数据明细表（批量 upsert）。

        按 note_id 匹配已有记录，有则更新最新数据。

        Returns: 同步的记录数
        """
        if not self.enabled:
            return 0
        table_id = self.table_ids.get("note_metrics")
        if not table_id:
            raise SyncEngineError("找不到 note_metrics 表")

        records = []
        for note_info, note_snapshot, note_trends in notes:
            fields = {
                "平台": "xiaohongshu",
                "笔记ID": note_snapshot.note_id,
                "所属账号": note_snapshot.account_id,
                "笔记标题": note_info.title,
                "排序序号": note_info.sort_order,
                "发布日期": _to_timestamp(note_info.publish_date),
                "笔记类型": "图文" if note_info.note_type == "image" else "视频",
                "浏览量": note_snapshot.views,
                "点赞数": note_snapshot.likes,
                "收藏数": note_snapshot.favorites,
                "评论数": note_snapshot.comments,
                "分享数": note_snapshot.shares,
                "总互动量": note_snapshot.total_interactions,
                "互动率(%)": (
                    round(note_snapshot.total_interactions / note_snapshot.views * 100, 2)
                    if note_snapshot.views > 0 else 0.0
                ),
                "数据抓取日期": _to_timestamp(note_snapshot.snapshot_date),
            }

            if note_info.url:
                fields["笔记链接"] = note_info.url

            if note_trends:
                fields["浏览量日增量"] = note_trends.views.dod_delta
                fields["点赞日增量"] = note_trends.likes.dod_delta

            records.append({"fields": fields})

        if not records:
            return 0

        result = self.client.upsert_records(
            table_id, records, match_field="笔记ID"
        )
        logger.info(
            "笔记明细同步: %d 篇 (created=%d, updated=%d)",
            len(records), result.get("created", 0), result.get("updated", 0),
        )
        return result.get("created", 0) + result.get("updated", 0)

    def sync_daily_snapshot(self, snapshot: AccountSnapshot) -> int:
        """同步每日快照表（upsert：按 快照日期+账号名称 匹配，有则更新，无则创建）。"""
        if not self.enabled:
            return 0
        table_id = self.table_ids.get("daily_snapshot")
        if not table_id:
            raise SyncEngineError("找不到 daily_snapshot 表")

        fields = {
            "平台": "xiaohongshu",
            "快照日期": _to_timestamp(snapshot.snapshot_date),
            "账号名称": snapshot.account_id,
            "粉丝数": snapshot.follower_count,
            "关注数": snapshot.following_count,
            "获赞与收藏总数": snapshot.total_likes + snapshot.total_collections,
            "当日新增笔记数": snapshot.notes_published_today,
            "当日笔记总互动": snapshot.total_interactions_today,
            "当日笔记总浏览": snapshot.total_views_today,
        }

        # 使用复合唯一键 "快照键" 作为 upsert 匹配字段
        match_key = f"{snapshot.account_id}@{snapshot.snapshot_date}"
        fields["快照键"] = match_key

        records = [{"fields": fields}]
        result = self.client.upsert_records(table_id, records, match_field="快照键")
        logger.info(
            "每日快照同步: %s @ %s (created=%d, updated=%d)",
            snapshot.account_id,
            snapshot.snapshot_date,
            result.get("created", 0),
            result.get("updated", 0),
        )
        return result.get("created", 0) + result.get("updated", 0)

    def sync_competitor_comparison(
        self, comparison: ComparisonTable
    ) -> int:
        """同步竞品对比表（全量替换）。"""
        if not self.enabled:
            return 0
        table_id = self.table_ids.get("competitor_comparison")
        if not table_id:
            raise SyncEngineError("找不到 competitor_comparison 表")

        records = []
        for rank in comparison.sorted_by_rank:
            records.append({
                "fields": {
                    "平台": "xiaohongshu",
                    "排名": rank.rank,
                    "账号名称": rank.display_name,
                    "粉丝数": rank.follower_count,
                    "粉丝日增量": rank.follower_dod,
                    "粉丝周增量": rank.follower_wow,
                    "总互动量": rank.total_interactions,
                    "互动率(%)": rank.engagement_rate,
                    "近7天发布笔记数": rank.recent_notes_count,
                    "平均笔记互动量": rank.avg_interactions_per_note,
                    "对比日期": _to_timestamp(comparison.comparison_date),
                }
            })

        if not records:
            return 0

        result = self.client.upsert_records(
            table_id, records, match_field="账号名称"
        )
        logger.info(
            "竞品对比同步: %d 个账号 (created=%d, updated=%d)",
            len(records), result.get("created", 0), result.get("updated", 0),
        )
        return result.get("created", 0) + result.get("updated", 0)

    def sync_full_pipeline(
        self,
        account_snapshot: AccountSnapshot,
        note_infos: list[NoteInfo],
        note_snapshots: list[NoteSnapshot],
        trends: AccountTrends,
        note_trends_map: dict[str, NoteTrends],
        competitor_rank: Optional[int] = None,
        rank_change: str = "不变",
    ) -> dict:
        """执行完整同步：账号概览 + 笔记明细。

        每日快照由调用方单独调用 sync_daily_snapshot() 控制，
        以支持按日期分组的批量快照同步。

        Returns:
            {"account_summary": N, "note_metrics": N, "errors": [...]}
        """
        if not self.enabled:
            logger.debug("SyncEngine 离线模式，跳过飞书同步")
            return {"account_summary": 0, "note_metrics": 0, "errors": ["SyncEngine 离线模式"]}
        results: dict = {"account_summary": 0, "note_metrics": 0, "errors": []}

        # 检查所需表是否存在
        missing_tables = []
        for table_key in ["account_summary", "note_metrics"]:
            if not self.table_ids.get(table_key):
                missing_tables.append(table_key)
        if missing_tables:
            msg = f"飞书多维表格缺少以下表: {missing_tables}。请在飞书后台手动创建对应表格（账号概览/笔记数据明细/每日快照/竞品对比），或使用 BitableSchemaManager 初始化。"
            logger.error(msg)
            results["errors"].append(msg)
            return results

        try:
            results["account_summary"] = self.sync_account_summary(
                trends, competitor_rank, rank_change
            )
        except Exception as e:
            err_msg = f"账号概览同步失败: {e}"
            logger.error(err_msg)
            results["errors"].append(err_msg)

        try:
            notes_tuples = []
            for info in note_infos:
                snap = next(
                    (ns for ns in note_snapshots if ns.note_id == info.note_id),
                    None,
                )
                if snap:
                    trend = note_trends_map.get(info.note_id)
                    notes_tuples.append((info, snap, trend))
            results["note_metrics"] = self.sync_note_metrics(notes_tuples)
        except Exception as e:
            err_msg = f"笔记明细同步失败: {e}"
            logger.error(err_msg)
            results["errors"].append(err_msg)

        return results


def run_full_sync(
    account_snapshot: AccountSnapshot,
    note_infos: list[NoteInfo],
    note_snapshots: list[NoteSnapshot],
    trends: AccountTrends,
    note_trends_map: dict[str, NoteTrends],
) -> dict:
    """便捷函数: 一键执行完整同步 Pipeline。"""
    engine = SyncEngine()
    return engine.sync_full_pipeline(
        account_snapshot=account_snapshot,
        note_infos=note_infos,
        note_snapshots=note_snapshots,
        trends=trends,
        note_trends_map=note_trends_map,
    )
