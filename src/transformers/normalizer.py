"""数据标准化器。

将采集层输出的原始数据转换为统一的内部格式：
- 中文数字解析: "1.2万" → 12000
- 类型强制转换
- 异常值检测与清洗
- 数据完整性校验
"""

import logging
import re
from datetime import date, datetime
from typing import Any, Optional, Union

from src.collectors.models import AccountProfile, CollectResult, NoteMetrics
from src.storage.models import AccountSnapshot, NoteInfo, NoteSnapshot

logger = logging.getLogger(__name__)


def parse_chinese_number(value: Union[str, int, float, None]) -> int:
    """解析中文数字表示。

    Examples:
        "1.2万"   -> 12000
        "1.2w"    -> 12000
        "3.5亿"   -> 350000000
        "1,234"   -> 1234
        "1.2k"    -> 1200
        1234      -> 1234
        None      -> 0
        ""        -> 0
    """
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)

    if not isinstance(value, str) or not value.strip():
        return 0

    value = value.strip().replace(",", "").replace("，", "").replace(" ", "")

    # 尝试直接解析
    try:
        return int(float(value))
    except ValueError:
        pass

    # 中文/英文单位
    multipliers = {
        "亿": 100_000_000,
        "千万": 10_000_000,
        "百万": 1_000_000,
        "万": 10_000,
        "w": 10_000,
        "W": 10_000,
        "k": 1_000,
        "K": 1_000,
        "千": 1_000,
    }

    # 按长度降序排序，优先匹配长单位（如"千万"要先于"万"）
    for unit, multiplier in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if unit in value:
            try:
                num_str = value.replace(unit, "")
                num = float(num_str)
                return int(num * multiplier)
            except ValueError:
                pass

    # 最后尝试提取纯数字部分
    digits = re.sub(r"[^\d.]", "", value)
    try:
        return int(float(digits))
    except ValueError:
        pass

    logger.debug("无法解析的数字: %s", value)
    return 0


def safe_int(value: Any, default: int = 0) -> int:
    """安全转换整数。"""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        return parse_chinese_number(value)
    return default


def safe_date(value: Any) -> Optional[date]:
    """安全转换日期。"""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except (ValueError, TypeError):
            pass
    return None


def validate_note_metrics(note: NoteMetrics) -> list[str]:
    """校验笔记数据合理性，返回警告列表。

    规则:
    - 点赞不应超过浏览量
    - 互动总量不应超过浏览量的200%（允许因缓存延迟略高）
    - 各项指标不应为负数
    """
    warnings = []

    if note.likes > note.views and note.views > 0:
        warnings.append(
            f"笔记 {note.note_id}: 点赞数({note.likes})大于浏览量({note.views})"
        )

    if note.total_interactions > note.views * 2 and note.views > 0:
        warnings.append(
            f"笔记 {note.note_id}: 互动总量({note.total_interactions})远大于浏览量({note.views})"
        )

    if note.views < 0 or note.likes < 0 or note.favorites < 0:
        warnings.append(f"笔记 {note.note_id}: 指标为负数")

    return warnings


def validate_account_profile(profile: AccountProfile) -> list[str]:
    """校验账号数据合理性。"""
    warnings = []

    if profile.following_count > profile.follower_count * 10 and profile.follower_count > 100:
        warnings.append(
            f"账号 {profile.account_id}: 关注数({profile.following_count})"
            f"远大于粉丝数({profile.follower_count})"
        )

    return warnings


# ── 数据模型转换 ──

def profile_to_snapshot(
    profile: AccountProfile, snapshot_date: Optional[date] = None
) -> AccountSnapshot:
    """将 AccountProfile 转为 AccountSnapshot ORM 对象。"""
    return AccountSnapshot(
        account_id=profile.account_id,
        snapshot_date=snapshot_date or date.today(),
        follower_count=profile.follower_count,
        following_count=profile.following_count,
        total_likes=profile.total_likes,
        total_collections=profile.total_collections,
        notes_published_today=0,
        total_interactions_today=0,
        total_views_today=0,
    )


def note_metrics_to_info(note: NoteMetrics) -> NoteInfo:
    """从 NoteMetrics 提取不变信息到 NoteInfo。"""
    return NoteInfo(
        note_id=note.note_id,
        account_id=note.account_id,
        title=note.title,
        note_type=note.note_type,
        publish_date=note.publish_date,
        url=note.url,
    )


def note_metrics_to_snapshot(
    note: NoteMetrics, snapshot_date: Optional[date] = None
) -> NoteSnapshot:
    """将 NoteMetrics 转为 NoteSnapshot ORM 对象。"""
    return NoteSnapshot(
        note_id=note.note_id,
        account_id=note.account_id,
        snapshot_date=snapshot_date or date.today(),
        views=note.views,
        likes=note.likes,
        favorites=note.favorites,
        comments=note.comments,
        shares=note.shares,
    )


def normalize_collect_result(
    result: CollectResult, snapshot_date: Optional[date] = None
) -> tuple[Optional[AccountSnapshot], list[NoteInfo], list[NoteSnapshot]]:
    """将一个采集结果标准化为数据库模型。

    Returns:
        (account_snapshot, note_info_list, note_snapshot_list)
    """
    sd = snapshot_date or date.today()

    account_snapshot = None
    if result.profile:
        account_snapshot = profile_to_snapshot(result.profile, sd)

    note_infos: list[NoteInfo] = []
    note_snapshots: list[NoteSnapshot] = []

    for note in result.notes:
        # 跳过无效笔记
        if not note.note_id or len(note.note_id) < 5:
            continue

        warnings = validate_note_metrics(note)
        for w in warnings:
            logger.warning("数据校验: %s", w)

        note_infos.append(note_metrics_to_info(note))
        note_snapshots.append(note_metrics_to_snapshot(note, sd))

    # 补充当日汇总数据
    if account_snapshot:
        account_snapshot.notes_published_today = len(note_infos)
        account_snapshot.total_interactions_today = sum(
            ns.total_interactions for ns in note_snapshots
        )
        account_snapshot.total_views_today = sum(
            ns.views for ns in note_snapshots
        )

    return account_snapshot, note_infos, note_snapshots
