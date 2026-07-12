"""SQLite 数据库管理：引擎创建、表初始化、CRUD 操作。"""

from datetime import date, datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import load_config
from src.storage.models import (
    AccountSnapshot,
    Base,
    NoteInfo,
    NoteSnapshot,
    SyncState,
)


class Database:
    """SQLite 数据库管理器。

    用法:
        db = Database("data/local.db")
        db.init()
        with db.session() as session:
            ...
    """

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            config = load_config()
            db_path = config.storage.sqlite_path

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(bind=self.engine)

    def init(self) -> None:
        """创建所有表（幂等操作）。"""
        Base.metadata.create_all(self.engine)

    def session(self) -> Session:
        """获取一个新的数据库 session。"""
        return self.SessionLocal()

    def drop_all(self) -> None:
        """删除所有表（仅用于测试）。"""
        Base.metadata.drop_all(self.engine)


# ── Repository 函数 ──


class AccountSnapshotRepo:
    """账号快照数据访问。"""

    def __init__(self, session: Session):
        self.session = session

    def save(self, snapshot: AccountSnapshot) -> AccountSnapshot:
        """保存或更新账号快照（每天每账号只有一条）。"""
        existing = self.get_by_account_date(
            snapshot.account_id, snapshot.snapshot_date
        )
        if existing:
            existing.follower_count = snapshot.follower_count
            existing.following_count = snapshot.following_count
            existing.total_likes = snapshot.total_likes
            existing.total_collections = snapshot.total_collections
            existing.notes_published_today = snapshot.notes_published_today
            existing.total_interactions_today = snapshot.total_interactions_today
            existing.total_views_today = snapshot.total_views_today
            existing.collected_at = datetime.now()
            self.session.flush()
            return existing
        else:
            self.session.add(snapshot)
            self.session.flush()
            return snapshot

    def get_by_account_date(
        self, account_id: str, snapshot_date: date
    ) -> Optional[AccountSnapshot]:
        return (
            self.session.query(AccountSnapshot)
            .filter_by(account_id=account_id, snapshot_date=snapshot_date)
            .first()
        )

    def get_latest(self, account_id: str) -> Optional[AccountSnapshot]:
        """获取某账号最新的快照。"""
        return (
            self.session.query(AccountSnapshot)
            .filter_by(account_id=account_id)
            .order_by(AccountSnapshot.snapshot_date.desc())
            .first()
        )

    def get_history(
        self, account_id: str, days: int = 30
    ) -> list[AccountSnapshot]:
        """获取某账号最近N天的历史快照。"""
        from datetime import timedelta

        since = date.today() - timedelta(days=days)
        return (
            self.session.query(AccountSnapshot)
            .filter(
                AccountSnapshot.account_id == account_id,
                AccountSnapshot.snapshot_date >= since,
            )
            .order_by(AccountSnapshot.snapshot_date.desc())
            .all()
        )

    def get_previous(
        self, account_id: str, snapshot_date: date, offset_days: int = 1
    ) -> Optional[AccountSnapshot]:
        """获取指定日期前N天的快照（用于计算环比）。"""
        from datetime import timedelta

        target = snapshot_date - timedelta(days=offset_days)
        return self.get_by_account_date(account_id, target)


class NoteInfoRepo:
    """笔记基本信息数据访问。"""

    def __init__(self, session: Session):
        self.session = session

    def save(self, note_info: NoteInfo) -> NoteInfo:
        existing = self.session.get(NoteInfo, note_info.note_id)
        if existing:
            existing.title = note_info.title
            existing.note_type = note_info.note_type
            existing.publish_date = note_info.publish_date
            existing.url = note_info.url
            self.session.flush()
            return existing
        else:
            self.session.add(note_info)
            self.session.flush()
            return note_info

    def get(self, note_id: str) -> Optional[NoteInfo]:
        return self.session.get(NoteInfo, note_id)

    def get_by_account(
        self, account_id: str, limit: int = 100
    ) -> list[NoteInfo]:
        return (
            self.session.query(NoteInfo)
            .filter_by(account_id=account_id)
            .order_by(NoteInfo.publish_date.desc())
            .limit(limit)
            .all()
        )


class NoteSnapshotRepo:
    """笔记快照数据访问。"""

    def __init__(self, session: Session):
        self.session = session

    def save(self, snapshot: NoteSnapshot) -> NoteSnapshot:
        existing = (
            self.session.query(NoteSnapshot)
            .filter_by(note_id=snapshot.note_id, snapshot_date=snapshot.snapshot_date)
            .first()
        )
        if existing:
            existing.views = snapshot.views
            existing.likes = snapshot.likes
            existing.favorites = snapshot.favorites
            existing.comments = snapshot.comments
            existing.shares = snapshot.shares
            existing.collected_at = datetime.now()
            self.session.flush()
            return existing
        else:
            self.session.add(snapshot)
            self.session.flush()
            return snapshot

    def get_by_note_date(
        self, note_id: str, snapshot_date: date
    ) -> Optional[NoteSnapshot]:
        return (
            self.session.query(NoteSnapshot)
            .filter_by(note_id=note_id, snapshot_date=snapshot_date)
            .first()
        )

    def get_previous(
        self, note_id: str, snapshot_date: date, offset_days: int = 1
    ) -> Optional[NoteSnapshot]:
        """获取指定日期前N天的笔记快照。"""
        from datetime import timedelta

        target = snapshot_date - timedelta(days=offset_days)
        return self.get_by_note_date(note_id, target)

    def get_all_for_date(
        self, snapshot_date: date
    ) -> list[NoteSnapshot]:
        return (
            self.session.query(NoteSnapshot)
            .filter_by(snapshot_date=snapshot_date)
            .all()
        )


class SyncStateRepo:
    """同步状态记录数据访问。"""

    def __init__(self, session: Session):
        self.session = session

    def update(
        self,
        account_id: str,
        status: str,
        snapshot_date: date | None = None,
        error_message: str = "",
    ) -> SyncState:
        state = self.session.get(SyncState, account_id)
        if not state:
            state = SyncState(account_id=account_id)
            self.session.add(state)
        state.last_synced_at = datetime.now()
        state.last_snapshot_date = snapshot_date
        state.sync_status = status
        state.error_message = error_message
        self.session.flush()
        return state

    def get(self, account_id: str) -> Optional[SyncState]:
        return self.session.get(SyncState, account_id)


# ── 全局单例 ──

_db: Optional[Database] = None


def get_db() -> Database:
    """获取全局数据库实例。"""
    global _db
    if _db is None:
        _db = Database()
        _db.init()
    return _db
