"""Private local persistence for AgentSafe escalation handoffs."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterator
from typing import Any


@dataclass(frozen=True, slots=True)
class PendingEscalation:
    """The saved AgentSafe handoff and the request identity that owns it."""

    correlation_id: str
    proposal: dict[str, Any]
    handoff: dict[str, Any]


class PendingEscalationStore:
    """Persist a managed handoff without changing the authority's intent."""

    def __init__(self, database: str | Path) -> None:
        self._path = Path(database)
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._initialize()

    def save(
        self,
        correlation_id: str,
        proposal: dict[str, Any],
        handoff: dict[str, Any],
    ) -> None:
        """Insert or replace only this correlation's still-open handoff."""

        with self._connect() as connection:
            connection.execute(
                """INSERT INTO pending_escalations
                   (correlation_id, proposal_json, handoff_json, status)
                   VALUES (?, ?, ?, 'PENDING')
                   ON CONFLICT(correlation_id) DO UPDATE SET
                     proposal_json = excluded.proposal_json,
                     handoff_json = excluded.handoff_json,
                     status = 'PENDING'""",
                (
                    correlation_id,
                    json.dumps(proposal, separators=(",", ":"), allow_nan=False),
                    json.dumps(handoff, separators=(",", ":"), allow_nan=False),
                ),
            )

    def get(self, correlation_id: str) -> PendingEscalation | None:
        """Return only an open escalation owned by this request identifier."""

        with self._connect() as connection:
            row = connection.execute(
                """SELECT proposal_json, handoff_json
                   FROM pending_escalations
                   WHERE correlation_id = ? AND status = 'PENDING'""",
                (correlation_id,),
            ).fetchone()
        if row is None:
            return None
        return PendingEscalation(
            correlation_id=correlation_id,
            proposal=json.loads(row[0]),
            handoff=json.loads(row[1]),
        )

    def update_handoff(self, correlation_id: str, handoff: dict[str, Any]) -> None:
        """Save AgentSafe's latest pending state exactly as returned."""

        with self._connect() as connection:
            connection.execute(
                """UPDATE pending_escalations SET handoff_json = ?
                   WHERE correlation_id = ? AND status = 'PENDING'""",
                (json.dumps(handoff, separators=(",", ":"), allow_nan=False), correlation_id),
            )

    def close(self, correlation_id: str, status: str) -> None:
        """Mark a terminal resume result so that it cannot be replayed locally."""

        if status not in {"RESOLVED", "DENIED", "EXPIRED", "UNAVAILABLE"}:
            raise ValueError("invalid terminal escalation status")
        with self._connect() as connection:
            connection.execute(
                """UPDATE pending_escalations SET status = ?
                   WHERE correlation_id = ? AND status = 'PENDING'""",
                (status, correlation_id),
            )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS pending_escalations (
                       correlation_id TEXT PRIMARY KEY,
                       proposal_json TEXT NOT NULL,
                       handoff_json TEXT NOT NULL,
                       status TEXT NOT NULL
                   )"""
            )
        try:
            self._path.chmod(0o600)
        except OSError:
            # The caller will get an I/O error on the next use; no action may
            # proceed on a handoff the runtime cannot durably retain.
            raise

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
