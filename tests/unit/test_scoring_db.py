"""Unit tests for :mod:`validator.scoring_db`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import protocol
from scoring.engine import VerifiedResult
from validator.scoring_db import ScoringDB


def _make_verified(cvrmse: float = 0.1, nmbe: float = 0.01, r2: float = 0.9, sims: int = 100) -> VerifiedResult:
    """Build a passing VerifiedResult with the given metrics."""
    return VerifiedResult(
        cvrmse=cvrmse,
        nmbe=nmbe,
        r_squared=r2,
        simulations_used=sims,
        calibrated_params={"a": 1.0},
    )


def _iso(dt: datetime) -> str:
    """Format a datetime to the same ISO-8601 millisecond-precision UTC string the DB uses."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _insert_raw(db: ScoringDB, round_id: str, uid: int, received_at: str, composite: float = 0.5) -> None:
    """Insert a single row bypassing the default timestamp so tests can control age."""
    assert db._conn is not None
    db._conn.execute(
        """
        INSERT INTO round_scores (
            round_id, uid, test_case,
            train_period_start, train_period_end,
            test_period_start, test_period_end,
            cvrmse, nmbe, r_squared, sims_used, composite, reason, received_at
        ) VALUES (?, ?, 'tc', 0, 1, 1, 2, 0.1, 0.01, 0.9, 100, ?, '', ?)
        """,
        (round_id, uid, composite, received_at),
    )


def test_fresh_db_initializes_with_correct_schema(tmp_path: Path) -> None:
    """Fresh DB has user_version = SCHEMA_VERSION and required tables."""
    db = ScoringDB(db_path=tmp_path / "scoring.db")
    try:
        assert db._conn is not None
        user_version = db._conn.execute("PRAGMA user_version").fetchone()[0]
        assert user_version == ScoringDB.SCHEMA_VERSION

        tables = {row[0] for row in db._conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "round_scores" in tables
        assert "validator_meta" in tables
    finally:
        db.close()


async def test_insert_round_scores_round_trip(tmp_path: Path) -> None:
    """Inserting three miners for one round persists three readable rows."""
    db = ScoringDB(db_path=tmp_path / "scoring.db")
    try:
        verified = {
            1: _make_verified(),
            2: _make_verified(cvrmse=0.2),
            3: _make_verified(cvrmse=0.05, r2=0.95),
        }
        composites = {1: 0.4, 2: 0.3, 3: 0.6}

        await db.insert_round_scores(
            round_id="round-0",
            test_case="tc_a",
            train_period=(0, 48),
            test_period=(48, 72),
            verified=verified,
            composites=composites,
        )

        rows = await db.get_scores_in_window(hours=72)
        assert len(rows) == 3
        assert {r.uid for r in rows} == {1, 2, 3}
        by_uid = {r.uid: r for r in rows}
        assert by_uid[1].composite == pytest.approx(0.4)
        assert by_uid[3].cvrmse == pytest.approx(0.05)
        assert by_uid[3].test_case == "tc_a"
        assert by_uid[3].train_period_end == 48
        assert by_uid[3].test_period_start == 48
    finally:
        db.close()


async def test_window_query_respects_cutoff(tmp_path: Path) -> None:
    """Rows older than the window are excluded; newer rows included."""
    db = ScoringDB(db_path=tmp_path / "scoring.db")
    try:
        now = datetime.now(tz=timezone.utc)
        _insert_raw(db, "round-old", 1, _iso(now - timedelta(hours=100)))
        _insert_raw(db, "round-mid", 2, _iso(now - timedelta(hours=50)))
        _insert_raw(db, "round-new", 3, _iso(now - timedelta(hours=1)))

        rows = await db.get_scores_in_window(hours=72)
        uids = {r.uid for r in rows}
        assert uids == {2, 3}
    finally:
        db.close()


async def test_cleanup_older_than_deletes_correctly(tmp_path: Path) -> None:
    """Rows older than the cutoff are deleted; newer rows survive."""
    db = ScoringDB(db_path=tmp_path / "scoring.db")
    try:
        now = datetime.now(tz=timezone.utc)
        _insert_raw(db, "r-old", 1, _iso(now - timedelta(hours=200)))
        _insert_raw(db, "r-old2", 2, _iso(now - timedelta(hours=180)))
        _insert_raw(db, "r-new", 3, _iso(now - timedelta(hours=10)))

        deleted = await db.cleanup_older_than(hours=168)
        assert deleted == 2

        rows = await db.get_scores_in_window(hours=720)
        assert len(rows) == 1
        assert rows[0].uid == 3
    finally:
        db.close()


def test_spec_version_mismatch_archives_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reopening with a different spec_version archives the old DB."""
    db_path = tmp_path / "scoring.db"

    db = ScoringDB(db_path=db_path)
    assert db._conn is not None
    db._conn.execute(
        """
        INSERT INTO round_scores (
            round_id, uid, test_case,
            train_period_start, train_period_end,
            test_period_start, test_period_end,
            cvrmse, nmbe, r_squared, sims_used, composite, reason
        ) VALUES ('r', 1, 'tc', 0, 1, 1, 2, 0.1, 0.0, 0.9, 100, 0.5, '')
        """
    )
    db.close()

    monkeypatch.setattr(protocol, "__spec_version__", protocol.__spec_version__ + 777)

    db2 = ScoringDB(db_path=db_path)
    try:
        archived = list(tmp_path.glob("scoring.db.archived.*"))
        assert len(archived) == 1, f"Expected one archived DB, got {archived}"

        assert db2._conn is not None
        count = db2._conn.execute("SELECT COUNT(*) FROM round_scores").fetchone()[0]
        assert count == 0
    finally:
        db2.close()


def test_legacy_json_state_archived_on_init(tmp_path: Path) -> None:
    """A legacy validator_state.json next to the DB is renamed on first open."""
    legacy = tmp_path / "validator_state.json"
    legacy.write_text('{"round_count": 1}', encoding="utf-8")

    db = ScoringDB(db_path=tmp_path / "scoring.db")
    try:
        assert not legacy.exists()
        archived = list(tmp_path.glob("validator_state.json.archived.*"))
        assert len(archived) == 1
    finally:
        db.close()


def test_pragma_settings_applied(tmp_path: Path) -> None:
    """journal_mode=WAL, synchronous=NORMAL, busy_timeout=5000, foreign_keys=ON."""
    db = ScoringDB(db_path=tmp_path / "scoring.db")
    try:
        assert db._conn is not None
        assert db._conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert db._conn.execute("PRAGMA synchronous").fetchone()[0] == 1
        assert db._conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert db._conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        db.close()


def test_verify_pragmas_raises_on_regression(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_verify_pragmas must refuse to open with a wrong setting."""
    db = ScoringDB(db_path=tmp_path / "scoring.db")
    db.close()

    def silent_apply(self: ScoringDB) -> None:
        assert self._conn is not None
        self._conn.execute("PRAGMA synchronous = FULL")

    monkeypatch.setattr(ScoringDB, "_apply_pragmas", silent_apply)

    with pytest.raises(RuntimeError, match="PRAGMA"):
        ScoringDB(db_path=tmp_path / "scoring.db")


async def test_connection_reuse_no_leak(tmp_path: Path) -> None:
    """Inserting many rows keeps using the same single connection object."""
    db = ScoringDB(db_path=tmp_path / "scoring.db")
    try:
        original_conn = db._conn
        assert original_conn is not None

        for round_idx in range(50):
            verified = {uid: _make_verified() for uid in range(20)}
            composites = {uid: 0.5 for uid in range(20)}
            await db.insert_round_scores(
                round_id=f"round-{round_idx}",
                test_case="tc",
                train_period=(0, 48),
                test_period=(48, 72),
                verified=verified,
                composites=composites,
            )

        assert db._conn is original_conn
        count = original_conn.execute("SELECT COUNT(*) FROM round_scores").fetchone()[0]
        assert count == 1000
    finally:
        db.close()


async def test_insert_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failure mid-insert rolls back the whole round; no partial rows persist."""
    db = ScoringDB(db_path=tmp_path / "scoring.db")
    try:
        await db.insert_round_scores(
            round_id="round-ok",
            test_case="tc",
            train_period=(0, 48),
            test_period=(48, 72),
            verified={1: _make_verified()},
            composites={1: 0.5},
        )

        pre = len(await db.get_scores_in_window(hours=72))
        assert pre == 1

        def partial_then_raise(rows: object) -> None:
            assert db._conn is not None
            assert isinstance(rows, list) and rows
            first = rows[0]
            db._conn.execute("BEGIN")
            try:
                db._conn.execute(
                    """
                    INSERT INTO round_scores (
                        round_id, uid, test_case,
                        train_period_start, train_period_end,
                        test_period_start, test_period_end,
                        cvrmse, nmbe, r_squared, sims_used, composite, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    first,
                )
                raise RuntimeError("simulated mid-batch failure")
            except Exception:
                db._conn.execute("ROLLBACK")
                raise

        monkeypatch.setattr(db, "_insert_rows_sync", partial_then_raise)

        with pytest.raises(RuntimeError):
            await db.insert_round_scores(
                round_id="round-bad",
                test_case="tc",
                train_period=(0, 48),
                test_period=(48, 72),
                verified={2: _make_verified(), 3: _make_verified(), 4: _make_verified()},
                composites={2: 0.5, 3: 0.5, 4: 0.5},
            )

        post = len(await db.get_scores_in_window(hours=72))
        assert post == 1
    finally:
        db.close()


def test_round_count_default_is_zero(tmp_path: Path) -> None:
    """A fresh DB has no round_count row; getter returns 0."""
    db = ScoringDB(db_path=tmp_path / "scoring.db")
    try:
        assert db.get_round_count() == 0
    finally:
        db.close()


def test_round_count_persists_across_instances(tmp_path: Path) -> None:
    """set_round_count survives close + reopen."""
    db_path = tmp_path / "scoring.db"
    db1 = ScoringDB(db_path=db_path)
    db1.set_round_count(42)
    db1.close()

    db2 = ScoringDB(db_path=db_path)
    try:
        assert db2.get_round_count() == 42
    finally:
        db2.close()


def test_round_count_overwrites_not_appends(tmp_path: Path) -> None:
    """Repeated set_round_count stores the latest value only."""
    db = ScoringDB(db_path=tmp_path / "scoring.db")
    try:
        db.set_round_count(1)
        db.set_round_count(5)
        db.set_round_count(3)
        assert db.get_round_count() == 3
    finally:
        db.close()
