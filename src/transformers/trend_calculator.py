"""趋势计算器。

基于 SQLite 中的历史快照计算：
- 日环比 (DoD: Day-over-Day)
- 周环比 (WoW: Week-over-Week)
- 增长率
- 异常标记（3σ 阈值）
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from src.storage.models import AccountSnapshot, NoteSnapshot

logger = logging.getLogger(__name__)


@dataclass
class TrendResult:
    """单个指标的趋势计算结果。"""

    current_value: int = 0
    previous_value: int = 0
    week_ago_value: int = 0
    dod_delta: int = 0
    wow_delta: int = 0
    dod_rate: float = 0.0
    wow_rate: float = 0.0
    is_anomalous: bool = False

    @property
    def dod_display(self) -> str:
        """日增量展示文本。"""
        if self.dod_delta > 0:
            return f"+{self.dod_delta}"
        return str(self.dod_delta)

    @property
    def wow_display(self) -> str:
        """周增量展示文本。"""
        if self.wow_delta > 0:
            return f"+{self.wow_delta}"
        return str(self.wow_delta)


@dataclass
class AccountTrends:
    """账号级别的趋势数据。"""

    account_id: str
    snapshot_date: date
    follower: TrendResult = field(default_factory=TrendResult)
    following: TrendResult = field(default_factory=TrendResult)
    total_likes: TrendResult = field(default_factory=TrendResult)
    total_collections: TrendResult = field(default_factory=TrendResult)
    total_interactions: TrendResult = field(default_factory=TrendResult)
    total_views: TrendResult = field(default_factory=TrendResult)

    @property
    def has_anomaly(self) -> bool:
        return any([
            self.follower.is_anomalous,
            self.total_likes.is_anomalous,
            self.total_interactions.is_anomalous,
        ])

    @property
    def anomaly_fields(self) -> list[str]:
        fields = []
        if self.follower.is_anomalous:
            fields.append("粉丝")
        if self.total_likes.is_anomalous:
            fields.append("获赞")
        if self.total_interactions.is_anomalous:
            fields.append("互动")
        return fields


@dataclass
class NoteTrends:
    """笔记级别的趋势数据。"""

    note_id: str
    account_id: str
    snapshot_date: date
    views: TrendResult = field(default_factory=TrendResult)
    likes: TrendResult = field(default_factory=TrendResult)
    favorites: TrendResult = field(default_factory=TrendResult)
    comments: TrendResult = field(default_factory=TrendResult)
    shares: TrendResult = field(default_factory=TrendResult)

    @property
    def best_growing_metric(self) -> tuple[str, int]:
        """增长最快的指标 (名称, 增量)。"""
        metrics = [
            ("浏览", self.views.dod_delta),
            ("点赞", self.likes.dod_delta),
            ("收藏", self.favorites.dod_delta),
            ("评论", self.comments.dod_delta),
            ("分享", self.shares.dod_delta),
        ]
        return max(metrics, key=lambda x: x[1])


class TrendCalculator:
    """趋势计算器。

    用法:
        calc = TrendCalculator(session, history_days=30)
        trends = calc.calculate_account_trends(current, previous, week_ago)
    """

    def __init__(self, history_days: int = 30, anomaly_std_threshold: float = 3.0):
        self.history_days = history_days
        self.anomaly_std_threshold = anomaly_std_threshold

    def _calculate_trend(
        self,
        current: int,
        previous: int,
        week_ago: int,
        history_values: Optional[list[int]] = None,
    ) -> TrendResult:
        """计算单个指标的趋势。"""
        current = current or 0
        previous = previous or 0
        week_ago = week_ago or 0

        dod_delta = current - previous
        wow_delta = current - week_ago

        dod_rate = (dod_delta / previous * 100) if previous > 0 else 0.0
        wow_rate = (wow_delta / week_ago * 100) if week_ago > 0 else 0.0

        # 异常检测: 基于历史均值和标准差
        is_anomalous = False
        if history_values and len(history_values) >= 7:
            import statistics

            try:
                mean = statistics.mean(history_values)
                std = statistics.stdev(history_values)
                if std > 0:
                    z_score = abs(current - mean) / std
                    is_anomalous = z_score > self.anomaly_std_threshold
                    if is_anomalous:
                        logger.info(
                            "异常检测: 当前值=%d, 均值=%.1f, σ=%.1f, z=%.2f",
                            current, mean, std, z_score,
                        )
            except statistics.StatisticsError:
                pass

        return TrendResult(
            current_value=current,
            previous_value=previous,
            week_ago_value=week_ago,
            dod_delta=dod_delta,
            wow_delta=wow_delta,
            dod_rate=round(dod_rate, 1),
            wow_rate=round(wow_rate, 1),
            is_anomalous=is_anomalous,
        )

    def calculate_account_trends(
        self,
        current: AccountSnapshot,
        previous: Optional[AccountSnapshot],
        week_ago: Optional[AccountSnapshot],
        history: Optional[list[AccountSnapshot]] = None,
    ) -> AccountTrends:
        """计算账号级别趋势。"""
        prev = previous or AccountSnapshot()
        wk = week_ago or AccountSnapshot()

        # 提取历史粉丝数用于异常检测
        history_followers = None
        if history:
            history_followers = [h.follower_count for h in history]

        return AccountTrends(
            account_id=current.account_id,
            snapshot_date=current.snapshot_date,
            follower=self._calculate_trend(
                current.follower_count,
                prev.follower_count,
                wk.follower_count,
                history_followers,
            ),
            following=self._calculate_trend(
                current.following_count or 0,
                prev.following_count or 0,
                wk.following_count or 0,
            ),
            total_likes=self._calculate_trend(
                current.total_likes or 0,
                prev.total_likes or 0,
                wk.total_likes or 0,
            ),
            total_collections=self._calculate_trend(
                current.total_collections or 0,
                prev.total_collections or 0,
                wk.total_collections or 0,
            ),
            total_interactions=self._calculate_trend(
                current.total_interactions_today,
                prev.total_interactions_today if previous else 0,
                wk.total_interactions_today if week_ago else 0,
            ),
            total_views=self._calculate_trend(
                current.total_views_today,
                prev.total_views_today if previous else 0,
                wk.total_views_today if week_ago else 0,
            ),
        )

    def calculate_note_trends(
        self,
        current: NoteSnapshot,
        previous: Optional[NoteSnapshot],
        week_ago: Optional[NoteSnapshot],
    ) -> NoteTrends:
        """计算单篇笔记的趋势。"""
        prev = previous or NoteSnapshot()
        wk = week_ago or NoteSnapshot()

        return NoteTrends(
            note_id=current.note_id,
            account_id=current.account_id,
            snapshot_date=current.snapshot_date,
            views=self._calculate_trend(
                current.views, prev.views, wk.views,
            ),
            likes=self._calculate_trend(
                current.likes, prev.likes, wk.likes,
            ),
            favorites=self._calculate_trend(
                current.favorites, prev.favorites, wk.favorites,
            ),
            comments=self._calculate_trend(
                current.comments, prev.comments, wk.comments,
            ),
            shares=self._calculate_trend(
                current.shares, prev.shares, wk.shares,
            ),
        )
