"""Unit tests for :mod:`validator.scoring_db`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import protocol
from scoring.engine import VerifiedResult
from scoring.report import CalibrationReport
from validator.scoring_db import ScoringDB


def _make_report(round_id: str = "round-0", uid: int = 1, hotkey: str = "5Abc") -> CalibrationReport:
    """Build a minimal valid CalibrationReport for persistence tests."""
    return CalibrationReport(
        round_id=round_id,
        miner_uid=uid,
        miner_hotkey=hotkey,
        test_case_id="bestest_air",
        manifest_version="v2.0.0",
        spec_version=protocol.__spec_version__,
        training_period_start_hour=0,
        training_period_end_hour=336,
        test_period_start_hour=336,
        test_period_end_hour=504,
        calibrated_parameters={"wall_r_value": 3.5},
        hourly_cvrmse=0.12,
        hourly_nmbe=-0.02,
        hourly_r_squared=0.88,
        monthly_cvrmse=0.06,
        monthly_nmbe=0.01,
        per_output_metrics={
            "zone_air_temperature_C": {
                "hourly_cvrmse": 0.05,
                "hourly_nmbe": -0.01,
                "hourly_r_squared": 0.92,
            }
        },
        ashrae_hourly_cvrmse_pass=True,
        ashrae_hourly_nmbe_pass=True,
        ashrae_monthly_cvrmse_pass=True,
        ashrae_monthly_nmbe_pass=True,
        ashrae_overall_pass=True,
        simulations_used=150,
        verification_reason=None,
        generated_at="2026-04-21T12:00:00.000000Z",
    )


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


def test_calibration_reports_table_exists_on_fresh_db(tmp_path: Path) -> None:
    """Fresh DB creates the calibration_reports table and its indexes."""
    db = ScoringDB(db_path=tmp_path / "scoring.db")
    try:
        assert db._conn is not None
        tables = {row[0] for row in db._conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "calibration_reports" in tables

        indexes = {
            row[0]
            for row in db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='calibration_reports'"
            ).fetchall()
        }
        assert "idx_calibration_reports_miner_hotkey" in indexes
        assert "idx_calibration_reports_created_at" in indexes
    finally:
        db.close()


async def test_persist_and_retrieve_report(tmp_path: Path) -> None:
    """Persisting and retrieving a report round-trips through JSON."""
    db = ScoringDB(db_path=tmp_path / "scoring.db")
    try:
        report = _make_report(round_id="round-5", uid=7, hotkey="5AbcXyz")
        await db.persist_report(report)

        restored = await db.get_report("round-5", 7)
        assert restored is not None
        assert restored.round_id == "round-5"
        assert restored.miner_uid == 7
        assert restored.miner_hotkey == "5AbcXyz"
        assert restored.test_case_id == "bestest_air"
        assert restored.calibrated_parameters == {"wall_r_value": 3.5}
        assert restored.hourly_cvrmse == pytest.approx(0.12)
        assert restored.ashrae_overall_pass is True
    finally:
        db.close()


async def test_persist_report_idempotent(tmp_path: Path) -> None:
    """Persisting the same (round_id, uid) twice is idempotent (last-write-wins)."""
    db = ScoringDB(db_path=tmp_path / "scoring.db")
    try:
        first = _make_report(round_id="round-0", uid=1)
        await db.persist_report(first)

        # Replace with a different report under the same primary key.
        second = _make_report(round_id="round-0", uid=1, hotkey="5ReplacedKey")
        await db.persist_report(second)

        restored = await db.get_report("round-0", 1)
        assert restored is not None
        assert restored.miner_hotkey == "5ReplacedKey"

        assert db._conn is not None
        count = db._conn.execute(
            "SELECT COUNT(*) FROM calibration_reports WHERE round_id = 'round-0' AND miner_uid = 1"
        ).fetchone()[0]
        assert count == 1
    finally:
        db.close()


async def test_get_report_not_found(tmp_path: Path) -> None:
    """Missing (round_id, uid) returns None."""
    db = ScoringDB(db_path=tmp_path / "scoring.db")
    try:
        assert await db.get_report("nonexistent", 999) is None
    finally:
        db.close()


async def test_get_reports_by_miner(tmp_path: Path) -> None:
    """Multiple reports for one miner across rounds are returned newest-first."""
    db = ScoringDB(db_path=tmp_path / "scoring.db")
    try:
        for round_idx in range(3):
            await db.persist_report(_make_report(round_id=f"round-{round_idx}", uid=1, hotkey="5MyHotkey"))
        # A different miner in between; must not leak across hotkeys
        await db.persist_report(_make_report(round_id="round-1", uid=2, hotkey="5Other"))

        reports = await db.get_reports_by_miner("5MyHotkey", limit=10)
        assert len(reports) == 3
        assert {r.round_id for r in reports} == {"round-0", "round-1", "round-2"}
        assert all(r.miner_hotkey == "5MyHotkey" for r in reports)

        other = await db.get_reports_by_miner("5Other", limit=10)
        assert len(other) == 1
        assert other[0].round_id == "round-1"
    finally:
        db.close()


async def test_get_reports_by_miner_respects_limit(tmp_path: Path) -> None:
    """Limit caps the returned list length."""
    db = ScoringDB(db_path=tmp_path / "scoring.db")
    try:
        for round_idx in range(5):
            await db.persist_report(_make_report(round_id=f"round-{round_idx}", uid=1, hotkey="5Hk"))

        reports = await db.get_reports_by_miner("5Hk", limit=2)
        assert len(reports) == 2
    finally:
        db.close()


async def test_cleanup_older_than_prunes_reports(tmp_path: Path) -> None:
    """cleanup_older_than deletes aged rows from calibration_reports too."""
    db = ScoringDB(db_path=tmp_path / "scoring.db")
    try:
        # Persist a fresh report
        await db.persist_report(_make_report(round_id="round-new", uid=1, hotkey="5Hk"))

        # Insert an aged report directly to backdate its created_at.
        old_iso = (datetime.now(tz=timezone.utc) - timedelta(hours=500)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        assert db._conn is not None
        db._conn.execute(
            """
            INSERT INTO calibration_reports (
                round_id, miner_uid, miner_hotkey, test_case_id,
                spec_version, report_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "round-old",
                1,
                "5Hk",
                "bestest_air",
                protocol.__spec_version__,
                _make_report(round_id="round-old", uid=1, hotkey="5Hk").to_json(),
                old_iso,
            ),
        )

        pre = db._conn.execute("SELECT COUNT(*) FROM calibration_reports").fetchone()[0]
        assert pre == 2

        await db.cleanup_older_than(hours=168)

        post = db._conn.execute("SELECT COUNT(*) FROM calibration_reports").fetchone()[0]
        assert post == 1
        surviving = await db.get_reports_by_miner("5Hk", limit=10)
        assert len(surviving) == 1
        assert surviving[0].round_id == "round-new"
    finally:
        db.close()


async def test_persist_report_with_rejected_submission(tmp_path: Path) -> None:
    """Rejected submissions (NaN metrics, reason set) round-trip correctly."""
    import math

    db = ScoringDB(db_path=tmp_path / "scoring.db")
    try:
        report = _make_report()
        report.hourly_cvrmse = float("nan")
        report.hourly_nmbe = float("nan")
        report.monthly_cvrmse = float("nan")
        report.monthly_nmbe = float("nan")
        report.ashrae_hourly_cvrmse_pass = False
        report.ashrae_overall_pass = False
        report.verification_reason = "DEFAULT_PARAMS"
        report.per_output_metrics = {}

        await db.persist_report(report)

        restored = await db.get_report(report.round_id, report.miner_uid)
        assert restored is not None
        assert restored.verification_reason == "DEFAULT_PARAMS"
        assert math.isnan(restored.hourly_cvrmse)
        assert math.isnan(restored.monthly_nmbe)
        assert restored.ashrae_overall_pass is False
    finally:
        db.close()
