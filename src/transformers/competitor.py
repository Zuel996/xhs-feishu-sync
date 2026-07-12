"""竞品对比分析器。

计算：
- 按多维度排名（粉丝数、互动率、笔记发布量）
- 横向对比表数据
- 排名变化追踪
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from src.storage.models import AccountSnapshot, NoteSnapshot

logger = logging.getLogger(__name__)


@dataclass
class CompetitorRank:
    """单个竞品的排名信息。"""

    account_id: str
    display_name: str
    rank: int
    previous_rank: Optional[int] = None
    follower_count: int = 0
    follower_dod: int = 0
    follower_wow: int = 0
    total_interactions: int = 0
    engagement_rate: float = 0.0
    recent_notes_count: int = 0
    avg_interactions_per_note: float = 0.0

    @property
    def rank_change(self) -> str:
        """排名变化展示。"""
        if self.previous_rank is None:
            return "新"
        delta = self.previous_rank - self.rank  # 正数 = 上升
        if delta > 0:
            return f"+{delta}"
        elif delta < 0:
            return str(delta)
        return "不变"

    @property
    def rank_change_direction(self) -> str:
        """排名变化方向。"""
        if self.previous_rank is None:
            return "new"
        if self.rank < self.previous_rank:
            return "up"
        elif self.rank > self.previous_rank:
            return "down"
        return "same"


@dataclass
class ComparisonTable:
    """竞品对比表。"""

    comparison_date: date
    rankings: list[CompetitorRank] = field(default_factory=list)

    @property
    def sorted_by_rank(self) -> list[CompetitorRank]:
        return sorted(self.rankings, key=lambda r: r.rank)

    @property
    def top_by_followers(self) -> list[CompetitorRank]:
        return sorted(self.rankings, key=lambda r: -r.follower_count)

    @property
    def top_by_engagement(self) -> list[CompetitorRank]:
        return sorted(self.rankings, key=lambda r: -r.engagement_rate)


class CompetitorAnalyzer:
    """竞品分析器。

    用法:
        analyzer = CompetitorAnalyzer()
        table = analyzer.build_comparison(
            account_snapshots, note_snapshots, previous_rankings
        )
    """

    def rank_by_followers(
        self,
        snapshots: list[AccountSnapshot],
    ) -> list[CompetitorRank]:
        """按粉丝数排名（降序）。"""
        sorted_snap = sorted(snapshots, key=lambda s: -s.follower_count)
        rankings = []
        for i, snap in enumerate(sorted_snap, 1):
            rankings.append(CompetitorRank(
                account_id=snap.account_id,
                display_name=snap.account_id,
                rank=i,
                follower_count=snap.follower_count,
            ))
        return rankings

    def build_comparison(
        self,
        current_snapshots: list[AccountSnapshot],
        note_snapshots_by_account: dict[str, list[NoteSnapshot]],
        previous_rankings: Optional[dict[str, int]] = None,
    ) -> ComparisonTable:
        """构建完整竞品对比表。

        Args:
            current_snapshots: 各账号当日快照
            note_snapshots_by_account: 各账号的笔记快照
            previous_rankings: 昨日排名 {account_id: rank}

        Returns:
            ComparisonTable 包含所有排名和指标
        """
        # 按粉丝数排名
        sorted_accounts = sorted(
            current_snapshots, key=lambda s: -s.follower_count
        )

        rankings: list[CompetitorRank] = []
        for i, snap in enumerate(sorted_accounts, 1):
            notes = note_snapshots_by_account.get(snap.account_id, [])

            # 计算指标
            total_interactions = sum(
                n.total_interactions for n in notes
            )
            total_views = sum(n.views for n in notes)

            # 互动率 = 总互动 / 总浏览
            engagement = (
                (total_interactions / total_views * 100)
                if total_views > 0
                else 0.0
            )

            # 平均笔记互动量
            avg_interactions = (
                total_interactions / len(notes) if notes else 0.0
            )

            prev_rank = previous_rankings.get(snap.account_id) if previous_rankings else None

            rankings.append(CompetitorRank(
                account_id=snap.account_id,
                display_name=snap.account_id,
                rank=i,
                previous_rank=prev_rank,
                follower_count=snap.follower_count,
                follower_dod=0,  # 需要与昨日快照对比
                follower_wow=0,  # 需要与7日前快照对比
                total_interactions=total_interactions,
                engagement_rate=round(engagement, 2),
                recent_notes_count=len(notes),
                avg_interactions_per_note=round(avg_interactions, 1),
            ))

        return ComparisonTable(
            comparison_date=(
                current_snapshots[0].snapshot_date
                if current_snapshots
                else date.today()
            ),
            rankings=rankings,
        )

    def enrich_with_deltas(
        self,
        rankings: list[CompetitorRank],
        yesterday_snapshots: dict[str, AccountSnapshot],
        week_ago_snapshots: dict[str, AccountSnapshot],
    ) -> list[CompetitorRank]:
        """用昨日/上周数据补充增量和排名变化。

        Args:
            rankings: 当前排名列表
            yesterday_snapshots: {account_id: 昨日快照}
            week_ago_snapshots: {account_id: 7日前快照}

        Returns:
            补充了增量的排名列表
        """
        for rank in rankings:
            yest = yesterday_snapshots.get(rank.account_id)
            week = week_ago_snapshots.get(rank.account_id)

            if yest:
                rank.follower_dod = rank.follower_count - yest.follower_count
            if week:
                rank.follower_wow = rank.follower_count - week.follower_count

        return rankings

    def get_rank_changes_summary(
        self, current: list[CompetitorRank]
    ) -> list[dict]:
        """获取排名变化摘要，适合推送到飞书 Bot。

        Returns:
            [{"account": "竞品A", "rank": 1, "change": "up", "detail": "+2"}, ...]
        """
        summary = []
        for r in current:
            if r.rank_change_direction != "same":
                summary.append({
                    "account": r.display_name,
                    "rank": r.rank,
                    "change": r.rank_change_direction,
                    "detail": r.rank_change,
                })
        return sorted(summary, key=lambda x: x["rank"])
