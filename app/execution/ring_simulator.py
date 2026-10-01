"""Stateful, auditable Ring simulator behind the AgentSafe downstream boundary."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Iterator
from typing import Any, Literal, Protocol

RingActionName = Literal["unlockDoor", "disarmSystem", "viewStream"]


class RingExecutionPort(Protocol):
    """A physical execution port called only by the trusted AgentSafe process."""

    def execute(self, request: dict[str, Any]) -> dict[str, Any]: ...

    def find_event(self, idempotency_key: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class SimulatorAuth:
    """The local simulator's one executor-only bearer token."""

    token: str

    def verify(self, supplied: str | None) -> bool:
        return bool(supplied) and hmac.compare_digest(supplied, self.token)


class RingSimulatorAdapter:
    """Execute an exact, grant-bound action against persistent simulated devices."""

    initial_state = {
        "door_locked": {"side_gate": True},
        "security_system_armed": {"home_security": True},
        "camera_stream_available": {"front_door": True},
    }

    def __init__(
        self,
        database: str | Path,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._database = Path(database)
        self._database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._initialize()

    def execute(self, request: dict[str, Any]) -> dict[str, Any]:
        action = request.get("action")
        target = request.get("target")
        parameters = request.get("parameters")
        if action not in {"unlockDoor", "disarmSystem", "viewStream"}:
            raise SimulatorRefusal("ACTION_UNSUPPORTED")
        if not isinstance(target, str) or not isinstance(parameters, dict):
            raise SimulatorRefusal("REQUEST_INVALID")
        self._validate_binding(request)
        fingerprint = _digest(
            {
                "action": action,
                "target": target,
                "parameters": parameters,
                "intent_hash": request["intent_hash"],
                "decision_id": request["decision_id"],
                "dossier_id": request["dossier_id"],
                "grant_id": request["grant_id"],
                "authorization_expires_at": request["authorization_expires_at"],
            }
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            old = connection.execute(
                "SELECT fingerprint, event_json FROM execution_events WHERE idempotency_key = ?",
                (request["idempotency_key"],),
            ).fetchone()
            if old is not None:
                if not hmac.compare_digest(old[0], fingerprint):
                    raise SimulatorRefusal("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_ACTION")
                return json.loads(old[1])

            state_row = connection.execute(
                "SELECT state_json FROM simulator_state WHERE singleton = 1"
            ).fetchone()
            state = json.loads(state_row[0]) if state_row else json.loads(
                json.dumps(self.initial_state)
            )
            self._apply(action, target, parameters, state)
            event = {
                "action": action,
                "target": target,
                "result": "executed",
                "timestamp": self._now().astimezone(timezone.utc).isoformat(),
                "decision_id": request["decision_id"],
                "dossier_id": request["dossier_id"],
                "grant_id": request["grant_id"],
                "authorization_expires_at": request["authorization_expires_at"],
                "correlation_id": request["correlation_id"],
                "intent_id": request["intent_id"],
                "intent_hash": request["intent_hash"],
                "idempotency_key": request["idempotency_key"],
                "dossier_evidence": request["dossier_evidence"],
                "state": state,
            }
            encoded = json.dumps(event, separators=(",", ":"), allow_nan=False)
            connection.execute(
                "INSERT INTO simulator_state(singleton, state_json) VALUES (1, ?) "
                "ON CONFLICT(singleton) DO UPDATE SET state_json=excluded.state_json",
                (json.dumps(state, separators=(",", ":"), allow_nan=False),),
            )
            connection.execute(
                "INSERT INTO execution_events(idempotency_key, fingerprint, event_json) VALUES (?, ?, ?)",
                (request["idempotency_key"], fingerprint, encoded),
            )
            return event

    def find_event(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT event_json FROM execution_events WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def state(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state_json FROM simulator_state WHERE singleton = 1"
            ).fetchone()
        return json.loads(row[0]) if row else json.loads(json.dumps(self.initial_state))

    def reset_for_demo(self) -> dict[str, Any]:
        """Reset only simulated devices between isolated scripted scenarios."""

        baseline = json.dumps(self.initial_state, separators=(",", ":"), allow_nan=False)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO simulator_state(singleton, state_json) VALUES (1, ?) "
                "ON CONFLICT(singleton) DO UPDATE SET state_json=excluded.state_json",
                (baseline,),
            )
            connection.execute(
                "INSERT INTO simulator_demo_resets(reset_at, state_json) VALUES (?, ?)",
                (self._now().astimezone(timezone.utc).isoformat(), baseline),
            )
        return json.loads(baseline)

    def _validate_binding(self, request: dict[str, Any]) -> None:
        required = (
            "idempotency_key",
            "correlation_id",
            "intent_id",
            "intent_hash",
            "decision_id",
            "dossier_id",
            "grant_id",
            "authorization_expires_at",
        )
        if any(not isinstance(request.get(key), str) or not request[key] for key in required):
            raise SimulatorRefusal("AUTHORIZATION_BINDING_MISSING")
        try:
            expires_at = datetime.fromisoformat(
                request["authorization_expires_at"].replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            raise SimulatorRefusal("AUTHORIZATION_EXPIRY_INVALID") from None
        if expires_at.tzinfo is None:
            raise SimulatorRefusal("AUTHORIZATION_EXPIRY_INVALID")
        if expires_at.astimezone(timezone.utc) <= self._now().astimezone(timezone.utc):
            raise SimulatorRefusal("AUTHORIZATION_EXPIRED")
        evidence = request.get("dossier_evidence")
        if (
            not isinstance(evidence, dict)
            or evidence.get("verified") is not True
            or not isinstance(evidence.get("reference"), str)
            or evidence.get("trust_anchor") != "DECIONIS_OFFICIAL"
        ):
            raise SimulatorRefusal("DOSSIER_EVIDENCE_NOT_VERIFIED")

    @staticmethod
    def _apply(action: str, target: str, parameters: dict[str, Any], state: dict[str, Any]) -> None:
        device = parameters.get("device_parameters", {})
        if not isinstance(device, dict):
            raise SimulatorRefusal("DEVICE_PARAMETERS_INVALID")
        if action == "unlockDoor":
            if target not in state["door_locked"]:
                raise SimulatorRefusal("UNKNOWN_DOOR_TARGET")
            duration = device.get("unlock_duration_seconds", 30)
            if not isinstance(duration, int) or isinstance(duration, bool) or not 1 <= duration <= 900:
                raise SimulatorRefusal("UNLOCK_DURATION_INVALID")
            state["door_locked"][target] = False
            return
        if action == "disarmSystem":
            if target not in state["security_system_armed"]:
                raise SimulatorRefusal("UNKNOWN_SECURITY_TARGET")
            state["security_system_armed"][target] = False
            return
        if action == "viewStream":
            if target not in state["camera_stream_available"]:
                raise SimulatorRefusal("UNKNOWN_CAMERA_TARGET")
            if state["camera_stream_available"][target] is not True:
                raise SimulatorRefusal("CAMERA_STREAM_UNAVAILABLE")
            return
        raise SimulatorRefusal("ACTION_UNSUPPORTED")

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS simulator_state (singleton INTEGER PRIMARY KEY CHECK(singleton=1), state_json TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS execution_events (idempotency_key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, event_json TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS simulator_demo_resets (reset_id INTEGER PRIMARY KEY, reset_at TEXT NOT NULL, state_json TEXT NOT NULL)"
            )
        self._database.chmod(0o600)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database, timeout=5.0)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


class SimulatorRefusal(ValueError):
    """Deterministic refusal from the local simulated Ring provider."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _digest(value: dict[str, Any]) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
