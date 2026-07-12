"""CSV 导入采集器。

从小红书创作者中心或第三方工具（新红/千瓜）导出的 CSV 文件中解析数据。
这是当浏览器采集和 API 都不可用时的降级方案。

支持的 CSV 格式（可配置列映射）:
- 创作者中心: 笔记导出 CSV
- 新红/千瓜等第三方工具的标准导出
"""

import csv
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from src.collectors.base import BaseCollector
from src.collectors.models import AccountProfile, CollectResult, NoteMetrics
from src.core.config import AccountInfo
from src.core.exceptions import CollectorError
from src.transformers.normalizer import parse_chinese_number

logger = logging.getLogger(__name__)

# 默认列名映射（创作者中心 -> 内部字段）
DEFAULT_COLUMN_MAP = {
    # 笔记数据列
    "note_id": ["笔记ID", "note_id", "id"],
    "title": ["笔记标题", "标题", "title"],
    "note_type": ["笔记类型", "类型", "type"],
    "publish_date": ["发布时间", "发布日期", "publish_date", "date"],
    "url": ["笔记链接", "链接", "url", "link"],
    "views": ["阅读量", "浏览量", "浏览", "views", "阅读"],
    "likes": ["点赞数", "点赞", "likes", "like_count"],
    "favorites": ["收藏数", "收藏", "favorites", "fav_count"],
    "comments": ["评论数", "评论", "comments", "comment_count"],
    "shares": ["分享数", "分享", "shares", "share_count"],
    # 账号数据列
    "followers": ["粉丝数", "粉丝", "followers", "follower_count"],
    "following": ["关注数", "关注", "following"],
    "total_likes": ["获赞数", "总获赞", "total_likes"],
    "total_collections": ["总收藏", "total_collections"],
}

# 笔记类型映射
NOTE_TYPE_MAP = {
    "图文": "image",
    "图片": "image",
    "image": "image",
    "视频": "video",
    "video": "video",
    "短视频": "video",
}


class CSVImportCollector(BaseCollector):
    """从 CSV 文件导入小红书数据。

    用法:
        collector = CSVImportCollector(base_dir="data/csv_imports")
        result = await collector.collect_all(account, target_date)
    """

    def __init__(self, base_dir: str = "data/csv_imports"):
        super().__init__()
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _find_csv(self, account_id: str) -> Optional[Path]:
        """查找指定账号的最新 CSV 文件。

        按命名约定查找: {base_dir}/{account_id}/*.csv
        """
        account_dir = self.base_dir / account_id
        if not account_dir.exists():
            return None
        csv_files = sorted(
            account_dir.glob("*.csv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return csv_files[0] if csv_files else None

    def _map_header(self, header: list[str]) -> dict[str, int]:
        """将 CSV 表头映射到内部字段名。

        返回 {internal_field: column_index}。
        """
        mapping: dict[str, int] = {}
        for internal_name, candidate_names in DEFAULT_COLUMN_MAP.items():
            for i, col in enumerate(header):
                if col.strip() in candidate_names:
                    mapping[internal_name] = i
                    break
        return mapping

    # _parse_chinese_number 移除，直接复用 src.transformers.normalizer.parse_chinese_number

    def _parse_date(self, value: str) -> Optional[date]:
        """解析日期字符串。"""
        if not value:
            return None
        value = str(value).strip()
        formats = [
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y.%m.%d",
            "%Y-%m-%d %H:%M:%S",
            "%m/%d/%Y",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        try:
            # ISO 格式
            return date.fromisoformat(value)
        except (ValueError, TypeError):
            pass
        return None

    def _parse_row(
        self, row: list[str], mapping: dict[str, int], account: AccountInfo
    ) -> NoteMetrics:
        """将一行 CSV 数据解析为 NoteMetrics。"""

        def get_val(field: str, default: str = "") -> str:
            idx = mapping.get(field)
            if idx is not None and idx < len(row):
                return row[idx].strip()
            return default

        note_type = NOTE_TYPE_MAP.get(
            get_val("note_type", "图文").lower(), "image"
        )

        return NoteMetrics(
            note_id=get_val("note_id"),
            account_id=account.account_id,
            title=get_val("title"),
            note_type=note_type,
            publish_date=self._parse_date(get_val("publish_date")),
            url=get_val("url"),
            views=parse_chinese_number(get_val("views")),
            likes=parse_chinese_number(get_val("likes")),
            favorites=parse_chinese_number(get_val("favorites")),
            comments=parse_chinese_number(get_val("comments")),
            shares=parse_chinese_number(get_val("shares")),
        )

    # ── 抽象方法实现 ──

    async def collect_account_profile(
        self, account: AccountInfo
    ) -> AccountProfile:
        """从 CSV 文件提取账号概览数据。"""
        csv_path = self._find_csv(account.account_id)
        if not csv_path:
            raise CollectorError(
                f"找不到账号 {account.account_id} 的 CSV 文件。"
                f"请将 CSV 放入 {self.base_dir / account.account_id}/"
            )

        # 尝试从 CSV 中读取账号行（通常第一行或标记行）
        profile = AccountProfile(
            account_id=account.account_id,
            xhs_user_id=account.xhs_user_id,
            username=account.xhs_username,
            display_name=account.display_name,
            competitor=account.competitor,
        )

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header_row = next(reader, None)
            if not header_row:
                return profile
            header = [h.strip() for h in header_row]
            mapping = self._map_header(header)

            # 尝试找一个汇总行（account_id 匹配或 blank note_id）
            for row in reader:
                row_id = (
                    row[mapping["note_id"]].strip()
                    if "note_id" in mapping and mapping["note_id"] < len(row)
                    else ""
                )
                if not row_id or row_id.lower() in ("summary", "汇总", "合计"):
                    profile.follower_count = parse_chinese_number(
                        row[mapping["followers"]]
                        if "followers" in mapping and mapping["followers"] < len(row)
                        else "0"
                    )
                    profile.following_count = parse_chinese_number(
                        row[mapping["following"]]
                        if "following" in mapping and mapping["following"] < len(row)
                        else "0"
                    )
                    profile.total_likes = parse_chinese_number(
                        row[mapping["total_likes"]]
                        if "total_likes" in mapping and mapping["total_likes"] < len(row)
                        else "0"
                    )
                    profile.total_collections = parse_chinese_number(
                        row[mapping["total_collections"]]
                        if "total_collections" in mapping and mapping["total_collections"] < len(row)
                        else "0"
                    )
                    break

        logger.info("CSV 账号概览: %s (粉丝: %d)", account.display_name, profile.follower_count)
        return profile

    async def collect_notes_data(
        self, account: AccountInfo, target_date: Optional[date] = None
    ) -> list[NoteMetrics]:
        """从 CSV 文件解析笔记数据。"""
        csv_path = self._find_csv(account.account_id)
        if not csv_path:
            raise CollectorError(
                f"找不到账号 {account.account_id} 的 CSV 文件。"
            )

        notes: list[NoteMetrics] = []

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header_row = next(reader, None)
            if not header_row:
                return notes
            header = [h.strip() for h in header_row]
            mapping = self._map_header(header)

            required = ["note_id"]
            if not all(k in mapping for k in required):
                missing = [k for k in required if k not in mapping]
                raise CollectorError(
                    f"CSV 缺少必要列: {missing}。"
                    f"现有列: {header}"
                )

            for row in reader:
                if not row or all(c.strip() == "" for c in row):
                    continue  # 跳过空行

                try:
                    note = self._parse_row(row, mapping, account)

                    # 按 target_date 过滤
                    if target_date and note.publish_date:
                        if note.publish_date != target_date:
                            continue

                    # 跳过无效行（没有 note_id 或浏览量无意义）
                    if not note.note_id or len(note.note_id) < 5:
                        continue

                    notes.append(note)
                except Exception as e:
                    logger.warning("解析 CSV 行失败: %s (行内容: %s)", e, row[:3])
                    continue

        logger.info(
            "CSV 导入完成: %s — %d 篇笔记 (文件: %s)",
            account.display_name, len(notes), csv_path.name,
        )
        return notes

    async def validate_connection(self) -> bool:
        """检查 CSV 目录是否存在。"""
        return self.base_dir.exists()
