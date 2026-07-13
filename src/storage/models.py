"""SQLAlchemy ORM 模型定义。

三张表：
- account_snapshots: 账号级别每日快照
- note_snapshots: 笔记级别每日快照
- note_info: 笔记基本信息（不变属性）
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AccountSnapshot(Base):
    """账号每日快照 — 趋势计算和差异同步的数据源。"""

    __tablename__ = "account_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32), default="xiaohongshu")
    account_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    follower_count: Mapped[int] = mapped_column(Integer, default=0)
    following_count: Mapped[int] = mapped_column(Integer, default=0)
    total_likes: Mapped[int] = mapped_column(Integer, default=0)
    total_collections: Mapped[int] = mapped_column(Integer, default=0)
    notes_published_today: Mapped[int] = mapped_column(Integer, default=0)
    total_interactions_today: Mapped[int] = mapped_column(Integer, default=0)
    total_views_today: Mapped[int] = mapped_column(Integer, default=0)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("account_id", "snapshot_date", name="uq_account_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<AccountSnapshot(account={self.account_id}, "
            f"date={self.snapshot_date}, followers={self.follower_count})>"
        )


class NoteInfo(Base):
    """笔记基本信息 — 发布后不变的属性。"""

    __tablename__ = "note_info"

    note_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), default="xiaohongshu")
    account_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(256), default="")
    note_type: Mapped[str] = mapped_column(String(16), default="image")  # "image" | "video"
    publish_date: Mapped[date] = mapped_column(Date, index=True, nullable=True)
    url: Mapped[str] = mapped_column(String(512), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def __repr__(self) -> str:
        return f"<NoteInfo(id={self.note_id}, title={self.title[:30]})>"


class NoteSnapshot(Base):
    """笔记每日快照 — 互动指标每日采集值。"""

    __tablename__ = "note_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32), default="xiaohongshu")
    note_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    favorites: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("note_id", "snapshot_date", name="uq_note_date"),
    )

    @property
    def total_interactions(self) -> int:
        """总互动量 = 点赞 + 收藏 + 评论 + 分享。"""
        return self.likes + self.favorites + self.comments + self.shares

    def __repr__(self) -> str:
        return (
            f"<NoteSnapshot(note={self.note_id}, date={self.snapshot_date}, "
            f"views={self.views}, likes={self.likes})>"
        )


class SyncState(Base):
    """同步状态记录 — 跟踪每个账号上次同步时间。"""

    __tablename__ = "sync_state"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), default="xiaohongshu")
    last_synced_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    last_snapshot_date: Mapped[date] = mapped_column(Date, nullable=True)
    sync_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|success|failed
    error_message: Mapped[str] = mapped_column(String(512), default="")

    def __repr__(self) -> str:
        return (
            f"<SyncState(account={self.account_id}, "
            f"status={self.sync_status}, last={self.last_synced_at})>"
        )
