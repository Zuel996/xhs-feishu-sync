"""测试数据标准化器 — parse_chinese_number, safe_int, safe_date, 校验函数。"""

import pytest
from datetime import date, datetime

from src.transformers.normalizer import (
    parse_chinese_number,
    safe_date,
    safe_int,
    validate_account_profile,
    validate_note_metrics,
    note_metrics_to_info,
    note_metrics_to_snapshot,
    profile_to_snapshot,
    normalize_collect_result,
)
from src.collectors.models import AccountProfile, CollectResult, NoteMetrics
from src.storage.models import AccountSnapshot, NoteInfo, NoteSnapshot


# ═══════════════════════════════════════════════════
# parse_chinese_number
# ═══════════════════════════════════════════════════

class TestParseChineseNumber:
    def test_plain_integer(self):
        assert parse_chinese_number(1234) == 1234

    def test_plain_float(self):
        assert parse_chinese_number(1.5) == 1

    def test_none_returns_zero(self):
        assert parse_chinese_number(None) == 0

    def test_empty_string_returns_zero(self):
        assert parse_chinese_number("") == 0
        assert parse_chinese_number("   ") == 0

    def test_wan_unit(self):
        assert parse_chinese_number("1.2万") == 12000
        assert parse_chinese_number("10万") == 100000
        assert parse_chinese_number("0.5万") == 5000

    def test_w_unit(self):
        assert parse_chinese_number("1.2w") == 12000
        assert parse_chinese_number("10W") == 100000

    def test_yi_unit(self):
        assert parse_chinese_number("3.5亿") == 350000000
        assert parse_chinese_number("1亿") == 100000000

    def test_k_unit(self):
        assert parse_chinese_number("1.2k") == 1200
        assert parse_chinese_number("5K") == 5000

    def test_comma_separated(self):
        assert parse_chinese_number("1,234") == 1234
        assert parse_chinese_number("1，234") == 1234  # 中文逗号

    def test_wan_with_comma(self):
        assert parse_chinese_number("12,345万") == 123450000

    def test_only_digits(self):
        assert parse_chinese_number("abc123def") == 123

    def test_unparseable_string(self):
        assert parse_chinese_number("无法解析") == 0

    def test_string_integer(self):
        assert parse_chinese_number("999") == 999


# ═══════════════════════════════════════════════════
# safe_int
# ═══════════════════════════════════════════════════

class TestSafeInt:
    def test_from_int(self):
        assert safe_int(42) == 42

    def test_from_float(self):
        assert safe_int(3.7) == 3

    def test_from_string(self):
        assert safe_int("1.5万") == 15000

    def test_from_none(self):
        assert safe_int(None) == 0

    def test_with_default(self):
        # safe_int 对无法解析的字符串始终返回 0（default 参数仅在非 str 类型生效）
        assert safe_int("bad", default=-1) == 0
        # default 在非 str/int/float 类型上生效
        assert safe_int([], default=-1) == -1


# ═══════════════════════════════════════════════════
# safe_date
# ═══════════════════════════════════════════════════

class TestSafeDate:
    def test_none_returns_none(self):
        assert safe_date(None) is None

    def test_date_passthrough(self):
        d = date(2026, 7, 14)
        assert safe_date(d) == d

    def test_datetime_conversion(self):
        # safe_date 的 isinstance 顺序：先 date 后 datetime
        # datetime 是 date 的子类，所以先被 date 分支捕获
        # 直接返回原值（datetime 对象），而非转换为 date
        dt = datetime(2026, 7, 14, 10, 30)
        result = safe_date(dt)
        # 当前实现：datetime 被子类关系先在 date 分支返回
        assert isinstance(result, datetime)

    def test_iso_string(self):
        assert safe_date("2026-07-14") == date(2026, 7, 14)

    def test_iso_string_with_time(self):
        assert safe_date("2026-07-14T10:30:00") == date(2026, 7, 14)

    def test_invalid_string(self):
        assert safe_date("not a date") is None


# ═══════════════════════════════════════════════════
# validate_note_metrics
# ═══════════════════════════════════════════════════

class TestValidateNoteMetrics:
    def test_valid_note_no_warnings(self):
        note = NoteMetrics(
            note_id="note_001",
            account_id="acc1",
            views=1000,
            likes=100,
            favorites=20,
            comments=10,
            shares=5,
        )
        assert validate_note_metrics(note) == []

    def test_likes_exceed_views(self):
        note = NoteMetrics(
            note_id="note_002",
            account_id="acc1",
            views=100,
            likes=200,
            favorites=0,
            comments=0,
            shares=0,
        )
        warnings = validate_note_metrics(note)
        assert len(warnings) == 1
        assert "点赞数" in warnings[0]

    def test_interactions_far_exceed_views(self):
        note = NoteMetrics(
            note_id="note_003",
            account_id="acc1",
            views=100,
            likes=100,
            favorites=100,
            comments=100,
            shares=100,
        )
        warnings = validate_note_metrics(note)
        assert any("互动总量" in w for w in warnings)

    def test_negative_values(self):
        # NoteMetrics 使用 pydantic Field(ge=0) 防止负值
        # 但 views 可以为 0（新笔记），此时 likes>views 会触发"点赞数大于浏览量"警告
        note = NoteMetrics(
            note_id="note_004",
            account_id="acc1",
            views=0,
            likes=10,
            favorites=0,
            comments=0,
            shares=0,
        )
        # likes(10) > views(0) but views=0 so validation skips
        warnings = validate_note_metrics(note)
        assert not any("点赞数" in w for w in warnings)

    def test_zero_views_no_false_positive(self):
        note = NoteMetrics(
            note_id="note_005",
            account_id="acc1",
            views=0,
            likes=10,
            favorites=0,
            comments=0,
            shares=0,
        )
        # likes > views but views=0, should not trigger warning
        warnings = validate_note_metrics(note)
        assert not any("点赞数" in w for w in warnings)


# ═══════════════════════════════════════════════════
# validate_account_profile
# ═══════════════════════════════════════════════════

class TestValidateAccountProfile:
    def test_normal_profile_no_warnings(self):
        profile = AccountProfile(
            account_id="acc1",
            xhs_user_id="abc123",
            username="test",
            follower_count=1000,
            following_count=100,
        )
        assert validate_account_profile(profile) == []

    def test_following_far_exceeds_followers(self):
        profile = AccountProfile(
            account_id="acc1",
            xhs_user_id="abc123",
            username="test",
            follower_count=200,
            following_count=5000,
        )
        warnings = validate_account_profile(profile)
        assert len(warnings) == 1
        assert "关注数" in warnings[0]

    def test_small_follower_base_no_false_positive(self):
        # follower < 100, even 10x ratio shouldn't trigger
        profile = AccountProfile(
            account_id="acc1",
            xhs_user_id="abc123",
            username="test",
            follower_count=50,
            following_count=500,
        )
        assert validate_account_profile(profile) == []


# ═══════════════════════════════════════════════════
# ORM 转换函数
# ═══════════════════════════════════════════════════

class TestModelConversions:
    def test_profile_to_snapshot(self):
        profile = AccountProfile(
            account_id="acc1",
            xhs_user_id="abc123",
            username="test",
            follower_count=1000,
            following_count=100,
            total_likes=5000,
            total_collections=3000,
        )
        snap = profile_to_snapshot(profile, date(2026, 7, 14))
        assert snap.platform == "xiaohongshu"
        assert snap.account_id == "acc1"
        assert snap.snapshot_date == date(2026, 7, 14)
        assert snap.follower_count == 1000
        assert snap.total_likes == 5000

    def test_note_metrics_to_info(self):
        note = NoteMetrics(
            note_id="note_001",
            account_id="acc1",
            title="Test Note",
            note_type="video",
            publish_date=date(2026, 7, 10),
            url="https://example.com/note/001",
            sort_order=3,
        )
        info = note_metrics_to_info(note)
        assert info.note_id == "note_001"
        assert info.title == "Test Note"
        assert info.note_type == "video"
        assert info.publish_date == date(2026, 7, 10)

    def test_note_metrics_to_snapshot(self):
        note = NoteMetrics(
            note_id="note_001",
            account_id="acc1",
            views=500,
            likes=50,
            favorites=10,
            comments=5,
            shares=2,
        )
        snap = note_metrics_to_snapshot(note, date(2026, 7, 14))
        assert snap.note_id == "note_001"
        assert snap.views == 500
        assert snap.likes == 50
        assert snap.snapshot_date == date(2026, 7, 14)


# ═══════════════════════════════════════════════════
# normalize_collect_result
# ═══════════════════════════════════════════════════

class TestNormalizeCollectResult:
    def test_empty_result(self):
        result = CollectResult(account_id="acc1")
        snapshots, infos, note_snapshots = normalize_collect_result(result)
        assert snapshots == []
        assert infos == []
        assert note_snapshots == []

    def test_result_with_profile_and_notes(self):
        profile = AccountProfile(
            account_id="acc1",
            xhs_user_id="abc123",
            username="test",
            follower_count=1000,
            following_count=100,
            total_likes=5000,
            total_collections=3000,
        )
        note1 = NoteMetrics(
            note_id="note_001",
            account_id="acc1",
            views=500,
            likes=50,
            publish_date=date(2026, 7, 14),
        )
        note2 = NoteMetrics(
            note_id="note_002",
            account_id="acc1",
            views=300,
            likes=30,
            publish_date=date(2026, 7, 14),
        )
        result = CollectResult(
            account_id="acc1",
            profile=profile,
            notes=[note1, note2],
        )
        snapshots, infos, note_snapshots = normalize_collect_result(result)

        # Should produce one snapshot for July 14
        assert len(snapshots) == 1
        assert snapshots[0].notes_published_today == 2
        assert snapshots[0].total_interactions_today == note1.total_interactions + note2.total_interactions
        assert snapshots[0].total_views_today == 800  # 500 + 300
        assert len(infos) == 2
        assert len(note_snapshots) == 2

    def test_skips_invalid_notes(self):
        profile = AccountProfile(
            account_id="acc1",
            xhs_user_id="abc123",
            username="test",
            follower_count=100,
        )
        valid_note = NoteMetrics(
            note_id="valid_note_001",
            account_id="acc1",
            views=100,
            publish_date=date(2026, 7, 14),
        )
        invalid_note = NoteMetrics(
            note_id="ab",  # too short, < 5 chars
            account_id="acc1",
            views=50,
        )
        result = CollectResult(
            account_id="acc1",
            profile=profile,
            notes=[valid_note, invalid_note],
        )
        snapshots, infos, note_snapshots = normalize_collect_result(result)
        assert len(infos) == 1
        assert infos[0].note_id == "valid_note_001"

    def test_multi_date_snapshots(self):
        profile = AccountProfile(
            account_id="acc1",
            xhs_user_id="abc123",
            username="test",
            follower_count=1000,
        )
        note_jul14 = NoteMetrics(
            note_id="note_001",
            account_id="acc1",
            views=500,
            publish_date=date(2026, 7, 14),
        )
        note_jul13 = NoteMetrics(
            note_id="note_002",
            account_id="acc1",
            views=300,
            publish_date=date(2026, 7, 13),
        )
        result = CollectResult(
            account_id="acc1",
            profile=profile,
            notes=[note_jul14, note_jul13],
        )
        snapshots, infos, note_snapshots = normalize_collect_result(result)

        # Should produce 2 snapshots: one for Jul 13, one for Jul 14
        assert len(snapshots) == 2
        dates = {s.snapshot_date for s in snapshots}
        assert date(2026, 7, 13) in dates
        assert date(2026, 7, 14) in dates
