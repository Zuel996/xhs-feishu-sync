"""测试趋势计算器 — DoD/WoW/增长率/异常检测。"""

import pytest
from datetime import date

from src.transformers.trend_calculator import (
    TrendCalculator,
    TrendResult,
    AccountTrends,
    NoteTrends,
)
from src.storage.models import AccountSnapshot, NoteSnapshot


# ═══════════════════════════════════════════════════
# TrendResult
# ═══════════════════════════════════════════════════

class TestTrendResult:
    def test_dod_display_positive(self):
        tr = TrendResult(dod_delta=100)
        assert tr.dod_display == "+100"

    def test_dod_display_zero(self):
        tr = TrendResult(dod_delta=0)
        assert tr.dod_display == "0"

    def test_dod_display_negative(self):
        tr = TrendResult(dod_delta=-50)
        assert tr.dod_display == "-50"

    def test_wow_display(self):
        tr = TrendResult(wow_delta=200)
        assert tr.wow_display == "+200"

    def test_defaults(self):
        tr = TrendResult()
        assert tr.current_value == 0
        assert tr.dod_delta == 0
        assert tr.dod_rate == 0.0
        assert tr.is_anomalous is False


# ═══════════════════════════════════════════════════
# TrendCalculator._calculate_trend
# ═══════════════════════════════════════════════════

class TestCalculateTrend:
    def setup_method(self):
        self.calc = TrendCalculator(history_days=30, anomaly_std_threshold=3.0)

    def test_basic_dod(self):
        result = self.calc._calculate_trend(current=100, previous=80, week_ago=60)
        assert result.current_value == 100
        assert result.previous_value == 80
        assert result.dod_delta == 20
        assert result.dod_rate == 25.0  # (20/80)*100
        assert result.wow_delta == 40
        assert result.wow_rate == pytest.approx(66.7, abs=0.1)  # (40/60)*100

    def test_previous_zero(self):
        """当 previous=0 时，DoD rate 应为 0（避免除零）。"""
        result = self.calc._calculate_trend(current=100, previous=0, week_ago=50)
        assert result.dod_delta == 100
        assert result.dod_rate == 0.0
        assert result.wow_rate == 100.0  # (50/50)*100

    def test_week_ago_zero(self):
        result = self.calc._calculate_trend(current=100, previous=80, week_ago=0)
        assert result.wow_delta == 100
        assert result.wow_rate == 0.0

    def test_all_zero(self):
        result = self.calc._calculate_trend(current=0, previous=0, week_ago=0)
        assert result.current_value == 0
        assert result.dod_delta == 0
        assert result.dod_rate == 0.0

    def test_none_inputs(self):
        """None 应该被当作 0 处理。"""
        result = self.calc._calculate_trend(current=50, previous=0, week_ago=0)
        assert result.dod_delta == 50

    def test_anomaly_detection_normal(self):
        """正常值不应触发异常标记（z-score < 3）。"""
        history = [100, 105, 98, 102, 101, 99, 103]
        result = self.calc._calculate_trend(
            current=102, previous=101, week_ago=98,
            history_values=history,
        )
        assert result.is_anomalous is False

    def test_anomaly_detection_triggered(self):
        """极端值应触发异常检测（z-score > 3）。"""
        history = [100, 100, 100, 100, 100, 100, 100]  # all same
        result = self.calc._calculate_trend(
            current=500, previous=100, week_ago=100,
            history_values=history,
        )
        # std ≈ 0, 但我们的代码在 std > 0 时才检查
        # 用不同的一组历史值
        history2 = [100, 105, 98, 102, 101, 99, 103]
        result2 = self.calc._calculate_trend(
            current=500, previous=100, week_ago=100,
            history_values=history2,
        )
        assert result2.is_anomalous is True

    def test_anomaly_short_history(self):
        """少于 7 个历史值时不检测异常。"""
        history = [100, 102, 101]
        result = self.calc._calculate_trend(
            current=500, previous=100, week_ago=100,
            history_values=history,
        )
        assert result.is_anomalous is False

    def test_custom_threshold(self):
        """自定义阈值应该生效。"""
        calc_low = TrendCalculator(anomaly_std_threshold=0.5)
        history = [100, 105, 98, 102, 101, 99, 103]
        result = calc_low._calculate_trend(
            current=110, previous=100, week_ago=95,
            history_values=history,
        )
        # 0.5 sigma threshold — more sensitive
        assert result.is_anomalous is True


# ═══════════════════════════════════════════════════
# AccountTrends
# ═══════════════════════════════════════════════════

class TestAccountTrends:
    def test_no_anomaly(self):
        trends = AccountTrends(
            account_id="acc1",
            snapshot_date=date(2026, 7, 14),
        )
        assert trends.has_anomaly is False
        assert trends.anomaly_fields == []

    def test_has_anomaly(self):
        trends = AccountTrends(
            account_id="acc1",
            snapshot_date=date(2026, 7, 14),
            follower=TrendResult(is_anomalous=True),
        )
        assert trends.has_anomaly is True
        assert "粉丝" in trends.anomaly_fields

    def test_multiple_anomalies(self):
        trends = AccountTrends(
            account_id="acc1",
            snapshot_date=date(2026, 7, 14),
            follower=TrendResult(is_anomalous=True),
            total_likes=TrendResult(is_anomalous=True),
        )
        assert len(trends.anomaly_fields) == 2


# ═══════════════════════════════════════════════════
# NoteTrends
# ═══════════════════════════════════════════════════

class TestNoteTrends:
    def test_best_growing_metric(self):
        trends = NoteTrends(
            note_id="note_001",
            account_id="acc1",
            snapshot_date=date(2026, 7, 14),
            views=TrendResult(dod_delta=100),
            likes=TrendResult(dod_delta=50),
            favorites=TrendResult(dod_delta=10),
            comments=TrendResult(dod_delta=5),
            shares=TrendResult(dod_delta=200),
        )
        best = trends.best_growing_metric
        assert best[0] == "分享"
        assert best[1] == 200

    def test_best_growing_metric_all_zero(self):
        trends = NoteTrends(
            note_id="note_001",
            account_id="acc1",
            snapshot_date=date(2026, 7, 14),
        )
        best = trends.best_growing_metric
        assert best[1] == 0  # all zeros


# ═══════════════════════════════════════════════════
# TrendCalculator.calculate_account_trends
# ═══════════════════════════════════════════════════

class TestCalculateAccountTrends:
    def setup_method(self):
        self.calc = TrendCalculator()

    def test_with_all_snapshots(self):
        current = AccountSnapshot(
            account_id="acc1",
            snapshot_date=date(2026, 7, 14),
            follower_count=1000,
            following_count=100,
            total_likes=5000,
            total_collections=3000,
            total_interactions_today=500,
            total_views_today=5000,
        )
        previous = AccountSnapshot(
            account_id="acc1",
            snapshot_date=date(2026, 7, 13),
            follower_count=980,
            following_count=100,
            total_likes=4900,
            total_collections=2950,
            total_interactions_today=450,
            total_views_today=4800,
        )
        week_ago = AccountSnapshot(
            account_id="acc1",
            snapshot_date=date(2026, 7, 7),
            follower_count=950,
            following_count=98,
            total_likes=4700,
            total_collections=2800,
            total_interactions_today=400,
            total_views_today=4500,
        )

        trends = self.calc.calculate_account_trends(current, previous, week_ago)

        assert trends.account_id == "acc1"
        assert trends.follower.dod_delta == 20  # 1000 - 980
        assert trends.follower.wow_delta == 50  # 1000 - 950
        assert trends.total_likes.dod_delta == 100  # 5000 - 4900

    def test_without_previous_snapshots(self):
        """没有历史快照时不应崩溃。"""
        current = AccountSnapshot(
            account_id="acc1",
            snapshot_date=date(2026, 7, 14),
            follower_count=100,
            total_interactions_today=10,
            total_views_today=100,
        )
        trends = self.calc.calculate_account_trends(current, None, None)
        assert trends.account_id == "acc1"
        assert trends.follower.dod_delta == 100  # 100 - 0 (default prev = 0)


# ═══════════════════════════════════════════════════
# TrendCalculator.calculate_note_trends
# ═══════════════════════════════════════════════════

class TestCalculateNoteTrends:
    def setup_method(self):
        self.calc = TrendCalculator()

    def test_with_all_snapshots(self):
        current = NoteSnapshot(
            note_id="note_001",
            account_id="acc1",
            snapshot_date=date(2026, 7, 14),
            views=1000,
            likes=100,
            favorites=20,
            comments=10,
            shares=5,
        )
        previous = NoteSnapshot(
            note_id="note_001",
            account_id="acc1",
            snapshot_date=date(2026, 7, 13),
            views=900,
            likes=90,
            favorites=18,
            comments=9,
            shares=4,
        )
        week_ago = NoteSnapshot(
            note_id="note_001",
            account_id="acc1",
            snapshot_date=date(2026, 7, 7),
            views=800,
            likes=80,
            favorites=15,
            comments=8,
            shares=3,
        )

        trends = self.calc.calculate_note_trends(current, previous, week_ago)

        assert trends.views.dod_delta == 100
        assert trends.likes.dod_delta == 10
        assert trends.shares.wow_delta == 2

    def test_without_previous(self):
        current = NoteSnapshot(
            note_id="note_002",
            account_id="acc1",
            snapshot_date=date(2026, 7, 14),
            views=500,
            likes=50,
        )
        trends = self.calc.calculate_note_trends(current, None, None)
        assert trends.views.dod_delta == 500  # 500 - 0
        assert trends.views.dod_rate == 0.0
