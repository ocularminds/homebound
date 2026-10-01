"""Typed, orchestration-originated action proposals."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

RingAction = Literal["unlockDoor", "disarmSystem", "viewStream"]


@dataclass(frozen=True, slots=True)
class ActionProposal:
    """An agent's proposed action; it does not carry execution authority."""

    action: RingAction
    target: str
    purpose: str
    parameters: dict[str, Any] = field(default_factory=dict)
    context_signals: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    idempotency_key: str = field(default_factory=lambda: str(uuid4()))
    captured_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def as_dict(self) -> dict[str, Any]:
        """Return the local proposal record without claiming it is a Decionis EIE."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class ActionResult:
    """Structured result returned through MCP to the orchestration layer."""

    decision: Literal["ALLOW", "ESCALATE", "BLOCK", "AUTHORITY_UNAVAILABLE"]
    execution: Literal["PERFORMED", "NOT_PERFORMED"]
    message: str
    correlation_id: str
    decision_id: str | None = None
    dossier_id: str | None = None
    grant_id: str | None = None
    authorization_expires_at: str | None = None
    escalation_id: str | None = None
    intent_id: str | None = None
    intent_hash: str | None = None
    authority_outcome: str | None = None
    reason_codes: tuple[str, ...] = ()
    escalation_expires_at: str | None = None
    dossier_evidence: dict[str, Any] | None = None
    execution_event: dict[str, Any] | None = None
    audit_recorded: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
