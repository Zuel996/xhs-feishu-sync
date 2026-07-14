"""测试竞品分析器 — 排名计算、对比表、增量补充。"""

import pytest
from datetime import date

from src.transformers.competitor import (
    CompetitorAnalyzer,
    CompetitorRank,
    ComparisonTable,
)
from src.storage.models import AccountSnapshot, NoteSnapshot


# ═══════════════════════════════════════════════════
# CompetitorRank
# ═══════════════════════════════════════════════════

class TestCompetitorRank:
    def test_rank_change_unchanged(self):
        rank = CompetitorRank(
            account_id="acc1",
            display_name="Brand A",
            rank=2,
            previous_rank=2,
        )
        assert rank.rank_change == "不变"
        assert rank.rank_change_direction == "same"

    def test_rank_change_up(self):
        rank = CompetitorRank(
            account_id="acc1",
            display_name="Brand A",
            rank=1,
            previous_rank=3,
        )
        assert rank.rank_change == "+2"
        assert rank.rank_change_direction == "up"

    def test_rank_change_down(self):
        rank = CompetitorRank(
            account_id="acc1",
            display_name="Brand A",
            rank=3,
            previous_rank=1,
        )
        assert rank.rank_change == "-2"
        assert rank.rank_change_direction == "down"

    def test_rank_change_new(self):
        rank = CompetitorRank(
            account_id="acc1",
            display_name="Brand A",
            rank=1,
            previous_rank=None,
        )
        assert rank.rank_change == "新"
        assert rank.rank_change_direction == "new"


# ═══════════════════════════════════════════════════
# ComparisonTable
# ═══════════════════════════════════════════════════

class TestComparisonTable:
    def test_sorted_by_rank(self):
        r1 = CompetitorRank(account_id="a", display_name="A", rank=3)
        r2 = CompetitorRank(account_id="b", display_name="B", rank=1)
        r3 = CompetitorRank(account_id="c", display_name="C", rank=2)
        table = ComparisonTable(
            comparison_date=date(2026, 7, 14),
            rankings=[r1, r2, r3],
        )
        sorted_ranks = table.sorted_by_rank
        assert sorted_ranks[0].rank == 1
        assert sorted_ranks[1].rank == 2
        assert sorted_ranks[2].rank == 3

    def test_top_by_followers(self):
        r1 = CompetitorRank(account_id="a", display_name="A", rank=1, follower_count=100)
        r2 = CompetitorRank(account_id="b", display_name="B", rank=2, follower_count=500)
        r3 = CompetitorRank(account_id="c", display_name="C", rank=3, follower_count=300)
        table = ComparisonTable(
            comparison_date=date(2026, 7, 14),
            rankings=[r1, r2, r3],
        )
        top = table.top_by_followers
        assert top[0].account_id == "b"  # 500 followers
        assert top[2].account_id == "a"  # 100 followers

    def test_top_by_engagement(self):
        r1 = CompetitorRank(account_id="a", display_name="A", rank=1, engagement_rate=3.5)
        r2 = CompetitorRank(account_id="b", display_name="B", rank=2, engagement_rate=5.2)
        table = ComparisonTable(
            comparison_date=date(2026, 7, 14),
            rankings=[r1, r2],
        )
        top = table.top_by_engagement
        assert top[0].account_id == "b"


# ═══════════════════════════════════════════════════
# CompetitorAnalyzer
# ═══════════════════════════════════════════════════

class TestCompetitorAnalyzer:
    def setup_method(self):
        self.analyzer = CompetitorAnalyzer()

    def test_rank_by_followers(self):
        snapshots = [
            AccountSnapshot(
                account_id="a",
                snapshot_date=date(2026, 7, 14),
                follower_count=500,
            ),
            AccountSnapshot(
                account_id="b",
                snapshot_date=date(2026, 7, 14),
                follower_count=1000,
            ),
            AccountSnapshot(
                account_id="c",
                snapshot_date=date(2026, 7, 14),
                follower_count=300,
            ),
        ]
        rankings = self.analyzer.rank_by_followers(snapshots)
        assert len(rankings) == 3
        assert rankings[0].account_id == "b"  # 1000 followers → rank 1
        assert rankings[0].rank == 1
        assert rankings[1].account_id == "a"  # 500 followers → rank 2
        assert rankings[2].account_id == "c"  # 300 followers → rank 3

    def test_build_comparison_basic(self):
        snapshots = [
            AccountSnapshot(
                account_id="comp_a",
                snapshot_date=date(2026, 7, 14),
                follower_count=1000,
            ),
            AccountSnapshot(
                account_id="comp_b",
                snapshot_date=date(2026, 7, 14),
                follower_count=800,
            ),
        ]
        notes_by_account = {
            "comp_a": [
                NoteSnapshot(
                    note_id="n1", account_id="comp_a",
                    snapshot_date=date(2026, 7, 14),
                    views=500, likes=50, favorites=10, comments=5, shares=2,
                ),
                NoteSnapshot(
                    note_id="n2", account_id="comp_a",
                    snapshot_date=date(2026, 7, 14),
                    views=300, likes=30, favorites=5, comments=3, shares=1,
                ),
            ],
            "comp_b": [
                NoteSnapshot(
                    note_id="n3", account_id="comp_b",
                    snapshot_date=date(2026, 7, 14),
                    views=200, likes=40, favorites=8, comments=4, shares=3,
                ),
            ],
        }

        table = self.analyzer.build_comparison(snapshots, notes_by_account)

        assert len(table.rankings) == 2
        assert table.rankings[0].account_id == "comp_a"  # rank 1 (1000 > 800)
        assert table.rankings[0].rank == 1
        assert table.rankings[0].recent_notes_count == 2
        assert table.rankings[1].rank == 2
        assert table.rankings[1].recent_notes_count == 1

        # Verification: engagement_rate = total_interactions / total_views * 100
        # comp_a: (67+39) / (500+300) * 100 = 106/800*100 = 13.25
        assert table.rankings[0].engagement_rate == pytest.approx(13.25, abs=0.01)

    def test_build_comparison_with_previous_rankings(self):
        snapshots = [
            AccountSnapshot(
                account_id="comp_a",
                snapshot_date=date(2026, 7, 14),
                follower_count=1000,
            ),
            AccountSnapshot(
                account_id="comp_b",
                snapshot_date=date(2026, 7, 14),
                follower_count=1200,
            ),
        ]
        prev_rankings = {"comp_a": 1, "comp_b": 2}

        table = self.analyzer.build_comparison(snapshots, {}, prev_rankings)

        # comp_b now has more followers → rank 1
        assert table.rankings[0].account_id == "comp_b"
        assert table.rankings[0].previous_rank == 2  # was 2, now 1
        assert table.rankings[0].rank_change_direction == "up"

        assert table.rankings[1].account_id == "comp_a"
        assert table.rankings[1].previous_rank == 1  # was 1, now 2
        assert table.rankings[1].rank_change_direction == "down"

    def test_build_comparison_empty(self):
        table = self.analyzer.build_comparison([], {})
        assert table.rankings == []

    def test_enrich_with_deltas(self):
        rankings = [
            CompetitorRank(
                account_id="comp_a", display_name="A",
                rank=1, follower_count=1000,
            ),
        ]
        yesterday = {
            "comp_a": AccountSnapshot(
                account_id="comp_a",
                snapshot_date=date(2026, 7, 13),
                follower_count=980,
            ),
        }
        week_ago = {
            "comp_a": AccountSnapshot(
                account_id="comp_a",
                snapshot_date=date(2026, 7, 7),
                follower_count=950,
            ),
        }
        enriched = self.analyzer.enrich_with_deltas(rankings, yesterday, week_ago)
        assert enriched[0].follower_dod == 20  # 1000 - 980
        assert enriched[0].follower_wow == 50  # 1000 - 950

    def test_get_rank_changes_summary(self):
        rankings = [
            CompetitorRank(
                account_id="a", display_name="A",
                rank=1, previous_rank=3,
            ),
            CompetitorRank(
                account_id="b", display_name="B",
                rank=2, previous_rank=2,
            ),
        ]
        changes = self.analyzer.get_rank_changes_summary(rankings)
        assert len(changes) == 1  # only A had a change
        assert changes[0]["account"] == "A"
        assert changes[0]["change"] == "up"
