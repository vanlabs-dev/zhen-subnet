"""SQLite-backed rolling score store for calibration rounds.

Persists every miner's verified result per round; provides windowed reads
for EMA-based weight computation. Single long-lived connection with WAL
mode. Schema versioned via ``PRAGMA user_version`` and spec-version checked
against ``protocol.__spec_version__`` on open: mismatched databases are
archived and recreated fresh.

Threading: the connection is opened with ``check_same_thread=False`` because
methods are called from both the asyncio main task (inline) and from
``asyncio.to_thread()`` workers. The single long-lived connection is safe
for serialized access from one coroutine context; we do NOT have concurrent
writers. If that ever changes, revisit.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import protocol
from scoring.engine import VerifiedResult

logger = logging.getLogger(__name__)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS round_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round_id TEXT NOT NULL,
    uid INTEGER NOT NULL,
    test_case TEXT NOT NULL,
    train_period_start INTEGER NOT NULL,
    train_period_end INTEGER NOT NULL,
    test_period_start INTEGER NOT NULL,
    test_period_end INTEGER NOT NULL,
    cvrmse REAL NOT NULL,
    nmbe REAL NOT NULL,
    r_squared REAL NOT NULL,
    sims_used INTEGER NOT NULL,
    composite REAL NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_round_scores_received_at
    ON round_scores(received_at);

CREATE INDEX IF NOT EXISTS idx_round_scores_uid_received
    ON round_scores(uid, received_at);

CREATE TABLE IF NOT EXISTS validator_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class RoundScoreRow:
    """Immutable view of one row from the ``round_scores`` table."""

    id: int
    round_id: str
    uid: int
    test_case: str
    train_period_start: int
    train_period_end: int
    test_period_start: int
    test_period_end: int
    cvrmse: float
    nmbe: float
    r_squared: float
    sims_used: int
    composite: float
    reason: str
    received_at: str


class ScoringDB:
    """Rolling score store for validator calibration rounds."""

    SCHEMA_VERSION = 1

    def __init__(self, db_path: Path | None = None) -> None:
        """Open (or create) the scoring DB at ``db_path``.

        Creates the parent directory if missing, opens a single long-lived
        connection, applies PRAGMAs, runs migrations, checks the stored
        spec version against ``protocol.__spec_version__`` and archives the
        DB if they disagree. Also archives any legacy JSON state file in
        the same directory on first open.

        Args:
            db_path: Override DB path. Defaults to ``~/.zhen/scoring.db``.
        """
        if db_path is None:
            db_path = Path.home() / ".zhen" / "scoring.db"
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

        self._open()
        self._archive_legacy_json_state()

    def _open(self) -> None:
        """Open the connection and bring schema + spec version current.

        May call :meth:`_archive_and_reinit` if a spec version mismatch is
        detected, which closes and reopens on a fresh file.
        """
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            isolation_level=None,
        )
        self._apply_pragmas()
        self._migrate()
        self._check_spec_version()
        self._verify_pragmas()

    def _apply_pragmas(self) -> None:
        """Apply the documented PRAGMA settings in the required order."""
        assert self._conn is not None
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA temp_store = MEMORY")

    def _verify_pragmas(self) -> None:
        """Assert the PRAGMAs we require are actually set on this connection.

        Guards against regressions where PRAGMAs silently fail to apply due
        to transaction-state or driver-version interactions. If any expected
        setting is wrong, refuse to start so the validator never runs with
        weaker durability or disabled constraints than intended.
        """
        assert self._conn is not None
        expected: dict[str, str | int] = {
            "journal_mode": "wal",
            "synchronous": 1,
            "busy_timeout": 5000,
            "foreign_keys": 1,
        }
        for pragma, want in expected.items():
            got = self._conn.execute(f"PRAGMA {pragma}").fetchone()[0]
            if isinstance(want, str):
                got = str(got).lower()
            if got != want:
                raise RuntimeError(
                    f"PRAGMA {pragma} expected {want!r}, got {got!r}. ScoringDB will not start with incorrect settings."
                )

    def _migrate(self) -> None:
        """Create schema and bump ``PRAGMA user_version`` to SCHEMA_VERSION.

        ``executescript`` manages its own transactions so we cannot wrap it in
        an outer BEGIN/COMMIT; the ``IF NOT EXISTS`` clauses plus the
        idempotent ``user_version`` bump make the sequence safe to retry if
        interrupted between statements.
        """
        assert self._conn is not None
        current = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        if current >= self.SCHEMA_VERSION:
            return

        self._conn.executescript(_SCHEMA_SQL)
        self._conn.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")

    def _check_spec_version(self) -> None:
        """Record spec version on fresh DB, or archive if it disagrees."""
        assert self._conn is not None
        row = self._conn.execute("SELECT value FROM validator_meta WHERE key = 'spec_version'").fetchone()

        current = protocol.__spec_version__

        if row is None:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    "INSERT INTO validator_meta (key, value) VALUES (?, ?)",
                    ("spec_version", str(current)),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            return

        stored = int(row[0])
        if stored != current:
            self._archive_and_reinit(f"spec_version mismatch: stored={stored}, current={current}")

    def _archive_and_reinit(self, reason: str) -> None:
        """Close connection, rename DB file with ``.archived.<ts>`` and reopen."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

        ts = int(time.time())
        archived = self.db_path.with_name(f"{self.db_path.name}.archived.{ts}")
        self.db_path.rename(archived)
        logger.warning(
            "Archived scoring DB to %s (%s). A fresh DB will be created; windowed EMA history starts from zero.",
            archived,
            reason,
        )

        for sidecar in (
            self.db_path.with_name(f"{self.db_path.name}-wal"),
            self.db_path.with_name(f"{self.db_path.name}-shm"),
        ):
            if sidecar.exists():
                sidecar.unlink()

        self._open()

    def _archive_legacy_json_state(self) -> None:
        """Rename any legacy ``validator_state.json`` next to the DB file.

        The old file recorded a point-in-time EMA snapshot, which has no
        meaning under the rolling 72h window model. We archive rather than
        replay it so the two scoring regimes stay cleanly separated.
        """
        legacy = self.db_path.parent / "validator_state.json"
        if not legacy.exists():
            return

        ts = int(time.time())
        archived = legacy.with_name(f"{legacy.name}.archived.{ts}")
        legacy.rename(archived)
        logger.warning(
            "Archived legacy state file %s to %s. The new scoring DB uses "
            "a rolling 72h window; old point-in-time EMA values are not "
            "meaningful in that model and will not be replayed.",
            legacy,
            archived,
        )

    async def insert_round_scores(
        self,
        round_id: str,
        test_case: str,
        train_period: tuple[int, int],
        test_period: tuple[int, int],
        verified: dict[int, VerifiedResult],
        composites: dict[int, float],
    ) -> None:
        """Persist one row per UID in ``verified`` as a single transaction.

        Rows for UIDs without an entry in ``composites`` receive a composite
        of ``0.0`` (matching ``ScoringEngine.compute()`` semantics for
        zeroed or floored miners).

        Args:
            round_id: Round identifier string.
            test_case: Test case id for this round.
            train_period: ``(start_hour, end_hour)`` training window.
            test_period: ``(start_hour, end_hour)`` held-out window.
            verified: Per-UID verification outcomes.
            composites: Per-UID normalized composite scores.
        """
        rows = [
            (
                round_id,
                uid,
                test_case,
                train_period[0],
                train_period[1],
                test_period[0],
                test_period[1],
                float(v.cvrmse),
                float(v.nmbe),
                float(v.r_squared),
                int(v.simulations_used),
                float(composites.get(uid, 0.0)),
                v.reason,
            )
            for uid, v in verified.items()
        ]

        if not rows:
            return

        await asyncio.to_thread(self._insert_rows_sync, rows)

    def _insert_rows_sync(self, rows: Sequence[tuple[object, ...]]) -> None:
        """Synchronous batched insert used by :meth:`insert_round_scores`."""
        assert self._conn is not None
        self._conn.execute("BEGIN")
        try:
            self._conn.executemany(
                """
                INSERT INTO round_scores (
                    round_id, uid, test_case,
                    train_period_start, train_period_end,
                    test_period_start, test_period_end,
                    cvrmse, nmbe, r_squared, sims_used, composite, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    async def get_scores_in_window(self, hours: int = 72) -> list[RoundScoreRow]:
        """Return rows received within the last ``hours``, oldest first."""
        return await asyncio.to_thread(self._get_scores_in_window_sync, hours)

    def _get_scores_in_window_sync(self, hours: int) -> list[RoundScoreRow]:
        """Synchronous body of :meth:`get_scores_in_window`."""
        assert self._conn is not None
        cutoff_expr = f"-{int(hours)} hours"
        cur = self._conn.execute(
            """
            SELECT id, round_id, uid, test_case,
                   train_period_start, train_period_end,
                   test_period_start, test_period_end,
                   cvrmse, nmbe, r_squared, sims_used, composite, reason,
                   received_at
            FROM round_scores
            WHERE received_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?)
            ORDER BY received_at ASC, id ASC
            """,
            (cutoff_expr,),
        )
        return [RoundScoreRow(*row) for row in cur.fetchall()]

    async def cleanup_older_than(self, hours: int = 168) -> int:
        """Delete rows older than ``hours`` (default 7 days). Returns count."""
        return await asyncio.to_thread(self._cleanup_older_than_sync, hours)

    def _cleanup_older_than_sync(self, hours: int) -> int:
        """Synchronous body of :meth:`cleanup_older_than`."""
        assert self._conn is not None
        cutoff_expr = f"-{int(hours)} hours"
        self._conn.execute("BEGIN")
        try:
            cur = self._conn.execute(
                """
                DELETE FROM round_scores
                WHERE received_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?)
                """,
                (cutoff_expr,),
            )
            deleted = int(cur.rowcount)
            self._conn.execute("COMMIT")
            return deleted
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def close(self) -> None:
        """Close the connection. Safe to call multiple times."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
