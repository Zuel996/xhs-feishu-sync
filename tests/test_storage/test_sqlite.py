"""测试 SQLite 存储层 — CRUD 操作、幂等性、查询。"""

import pytest
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.storage.models import (
    AccountSnapshot,
    Base,
    NoteInfo,
    NoteSnapshot,
    SyncState,
)
from src.storage.sqlite import (
    AccountSnapshotRepo,
    NoteInfoRepo,
    NoteSnapshotRepo,
    SyncStateRepo,
)


# ═══════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════

@pytest.fixture
def engine():
    """In-memory SQLite engine with all tables created."""
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture
def session(engine):
    """New session for each test, rolled back after."""
    SessionLocal = sessionmaker(bind=engine)
    sess = SessionLocal()
    yield sess
    sess.rollback()
    sess.close()


# ═══════════════════════════════════════════════════
# AccountSnapshotRepo
# ═══════════════════════════════════════════════════

class TestAccountSnapshotRepo:
    def test_save_new(self, session):
        repo = AccountSnapshotRepo(session)
        snap = AccountSnapshot(
            account_id="acc1",
            snapshot_date=date(2026, 7, 14),
            follower_count=1000,
        )
        saved = repo.save(snap)
        assert saved.id is not None
        assert saved.account_id == "acc1"

    def test_save_update_existing(self, session):
        repo = AccountSnapshotRepo(session)
        snap1 = AccountSnapshot(
            account_id="acc1",
            snapshot_date=date(2026, 7, 14),
            follower_count=1000,
            following_count=100,
            total_likes=5000,
            total_collections=3000,
            notes_published_today=0,
            total_interactions_today=0,
            total_views_today=0,
        )
        repo.save(snap1)

        snap2 = AccountSnapshot(
            account_id="acc1",
            snapshot_date=date(2026, 7, 14),
            follower_count=1200,
            following_count=100,
            total_likes=5000,
            total_collections=3000,
            notes_published_today=0,
            total_interactions_today=0,
            total_views_today=0,
        )
        saved = repo.save(snap2)
        assert saved.follower_count == 1200

        # Should be only one row for (acc1, 2026-07-14)
        result = repo.get_by_account_date("acc1", date(2026, 7, 14))
        assert result.follower_count == 1200

    def test_get_by_account_date_not_found(self, session):
        repo = AccountSnapshotRepo(session)
        result = repo.get_by_account_date("nonexistent", date(2026, 7, 14))
        assert result is None

    def test_get_latest(self, session):
        repo = AccountSnapshotRepo(session)
        repo.save(AccountSnapshot(
            account_id="acc1", snapshot_date=date(2026, 7, 13), follower_count=900,
        ))
        repo.save(AccountSnapshot(
            account_id="acc1", snapshot_date=date(2026, 7, 14), follower_count=1000,
        ))
        latest = repo.get_latest("acc1")
        assert latest.snapshot_date == date(2026, 7, 14)
        assert latest.follower_count == 1000

    def test_get_history(self, session):
        repo = AccountSnapshotRepo(session)
        today = date.today()
        for i in range(10):
            repo.save(AccountSnapshot(
                account_id="acc1",
                snapshot_date=today - date.resolution * i,
                follower_count=1000 + i,
                following_count=100,
                total_likes=5000,
                total_collections=3000,
            ))
        history = repo.get_history("acc1", days=5)
        # All returned snapshots must be within the window
        since = today - date.resolution * 5
        assert len(history) >= 1  # at least today's snapshot
        for h in history:
            assert h.snapshot_date >= since
        # Snapshots older than 5 days should not be included
        old_snap = AccountSnapshot(
            account_id="acc1",
            snapshot_date=today - date.resolution * 10,
            follower_count=500,
            following_count=50,
            total_likes=1000,
            total_collections=500,
        )
        repo.save(old_snap)
        history2 = repo.get_history("acc1", days=5)
        old_ids = [h.snapshot_date for h in history2]
        assert (today - date.resolution * 10) not in old_ids

    def test_get_previous(self, session):
        repo = AccountSnapshotRepo(session)
        repo.save(AccountSnapshot(
            account_id="acc1", snapshot_date=date(2026, 7, 13), follower_count=900,
        ))
        repo.save(AccountSnapshot(
            account_id="acc1", snapshot_date=date(2026, 7, 14), follower_count=1000,
        ))
        prev = repo.get_previous("acc1", date(2026, 7, 14), offset_days=1)
        assert prev.snapshot_date == date(2026, 7, 13)
        assert prev.follower_count == 900

    def test_multiple_accounts(self, session):
        repo = AccountSnapshotRepo(session)
        repo.save(AccountSnapshot(
            account_id="acc1", snapshot_date=date(2026, 7, 14), follower_count=100,
        ))
        repo.save(AccountSnapshot(
            account_id="acc2", snapshot_date=date(2026, 7, 14), follower_count=200,
        ))
        assert repo.get_by_account_date("acc1", date(2026, 7, 14)).follower_count == 100
        assert repo.get_by_account_date("acc2", date(2026, 7, 14)).follower_count == 200


# ═══════════════════════════════════════════════════
# NoteInfoRepo
# ═══════════════════════════════════════════════════

class TestNoteInfoRepo:
    def test_save_new(self, session):
        repo = NoteInfoRepo(session)
        info = NoteInfo(
            note_id="note_001",
            account_id="acc1",
            title="Test Note",
            note_type="image",
            publish_date=date(2026, 7, 14),
        )
        saved = repo.save(info)
        assert saved.note_id == "note_001"

    def test_save_update_existing(self, session):
        repo = NoteInfoRepo(session)
        info1 = NoteInfo(
            note_id="note_001",
            account_id="acc1",
            title="Old Title",
            note_type="image",
            url="https://example.com",
            sort_order=1,
        )
        repo.save(info1)

        info2 = NoteInfo(
            note_id="note_001",
            account_id="acc1",
            title="New Title",
            note_type="video",
            url="https://example.com",
            sort_order=1,
        )
        saved = repo.save(info2)
        assert saved.title == "New Title"
        assert saved.note_type == "video"

    def test_get(self, session):
        repo = NoteInfoRepo(session)
        repo.save(NoteInfo(
            note_id="note_001", account_id="acc1", title="Test",
        ))
        result = repo.get("note_001")
        assert result.title == "Test"

    def test_get_not_found(self, session):
        repo = NoteInfoRepo(session)
        assert repo.get("nonexistent") is None

    def test_get_by_account(self, session):
        repo = NoteInfoRepo(session)
        repo.save(NoteInfo(
            note_id="note_a1", account_id="acc1", title="A1",
            publish_date=date(2026, 7, 14),
        ))
        repo.save(NoteInfo(
            note_id="note_a2", account_id="acc1", title="A2",
            publish_date=date(2026, 7, 13),
        ))
        repo.save(NoteInfo(
            note_id="note_b1", account_id="acc2", title="B1",
            publish_date=date(2026, 7, 14),
        ))

        acc1_notes = repo.get_by_account("acc1")
        assert len(acc1_notes) == 2
        # Should be sorted by publish_date desc
        assert acc1_notes[0].publish_date == date(2026, 7, 14)


# ═══════════════════════════════════════════════════
# NoteSnapshotRepo
# ═══════════════════════════════════════════════════

class TestNoteSnapshotRepo:
    def test_save_new(self, session):
        repo = NoteSnapshotRepo(session)
        snap = NoteSnapshot(
            note_id="note_001",
            account_id="acc1",
            snapshot_date=date(2026, 7, 14),
            views=500,
            likes=50,
        )
        saved = repo.save(snap)
        assert saved.id is not None
        assert saved.views == 500

    def test_save_update_existing(self, session):
        repo = NoteSnapshotRepo(session)
        repo.save(NoteSnapshot(
            note_id="note_001", account_id="acc1",
            snapshot_date=date(2026, 7, 14),
            views=500, likes=50, favorites=10, comments=5, shares=2,
        ))
        repo.save(NoteSnapshot(
            note_id="note_001", account_id="acc1",
            snapshot_date=date(2026, 7, 14),
            views=600, likes=50, favorites=10, comments=5, shares=2,
        ))
        result = repo.get_by_note_date("note_001", date(2026, 7, 14))
        assert result.views == 600

    def test_get_all_for_date(self, session):
        repo = NoteSnapshotRepo(session)
        repo.save(NoteSnapshot(
            note_id="note_001", account_id="acc1",
            snapshot_date=date(2026, 7, 14), views=100,
        ))
        repo.save(NoteSnapshot(
            note_id="note_002", account_id="acc1",
            snapshot_date=date(2026, 7, 14), views=200,
        ))
        repo.save(NoteSnapshot(
            note_id="note_003", account_id="acc1",
            snapshot_date=date(2026, 7, 13), views=300,
        ))

        jul14 = repo.get_all_for_date(date(2026, 7, 14))
        assert len(jul14) == 2

    def test_get_previous(self, session):
        repo = NoteSnapshotRepo(session)
        repo.save(NoteSnapshot(
            note_id="note_001", account_id="acc1",
            snapshot_date=date(2026, 7, 13), views=400,
        ))
        repo.save(NoteSnapshot(
            note_id="note_001", account_id="acc1",
            snapshot_date=date(2026, 7, 14), views=500,
        ))
        prev = repo.get_previous("note_001", date(2026, 7, 14), offset_days=1)
        assert prev.snapshot_date == date(2026, 7, 13)
        assert prev.views == 400

    def test_total_interactions_property(self, session):
        repo = NoteSnapshotRepo(session)
        snap = NoteSnapshot(
            note_id="note_001", account_id="acc1",
            snapshot_date=date(2026, 7, 14),
            likes=100, favorites=20, comments=10, shares=5,
        )
        saved = repo.save(snap)
        assert saved.total_interactions == 135  # 100+20+10+5


# ═══════════════════════════════════════════════════
# SyncStateRepo
# ═══════════════════════════════════════════════════

class TestSyncStateRepo:
    def test_update_new(self, session):
        repo = SyncStateRepo(session)
        state = repo.update(
            account_id="acc1",
            status="success",
            snapshot_date=date(2026, 7, 14),
        )
        assert state.account_id == "acc1"
        assert state.sync_status == "success"
        assert state.last_snapshot_date == date(2026, 7, 14)
        assert state.last_synced_at is not None

    def test_update_existing(self, session):
        repo = SyncStateRepo(session)
        repo.update(account_id="acc1", status="success")
        state = repo.update(
            account_id="acc1",
            status="failed",
            error_message="Connection timeout",
        )
        assert state.sync_status == "failed"
        assert state.error_message == "Connection timeout"

    def test_get(self, session):
        repo = SyncStateRepo(session)
        repo.update(account_id="acc1", status="success")
        state = repo.get("acc1")
        assert state.sync_status == "success"

    def test_get_not_found(self, session):
        repo = SyncStateRepo(session)
        assert repo.get("nonexistent") is None
