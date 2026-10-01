"""Contract tests for Python's authenticated AgentSafe HTTP client."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest

from app.audit.action_log import ActionAuditLog
from app.audit.pending_escalations import PendingEscalationStore
from app.interception.agentsafe_http import AgentSafeActionPort
from app.models.actions import ActionProposal


def response(
    verdict: str,
    *,
    outcome: str,
    executed: bool | None,
    escalation: dict[str, Any] | None = None,
    reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "mode": "ENFORCEMENT",
        "intent_id": "intent-001",
        "intent_hash": "sha256:" + "a" * 64,
        "verdict": verdict,
        "decision_id": "decision-001",
        "dossier_id": "dossier-001",
        "authorization": {
            "decision_id": "decision-001",
            "dossier_id": "dossier-001",
            "grant_id": "grant-001",
            "expires_at": "2030-01-01T00:00:00Z",
        },
        "reason_codes": reason_codes or [],
        "fail_closed": False,
        "outcome": outcome,
        "executed": executed,
        "escalation": escalation,
    }


def proposal() -> ActionProposal:
    return ActionProposal(
        action="unlockDoor",
        target="side_gate",
        purpose="expected high-value delivery",
        parameters={"unlock_duration_seconds": 30},
        context_signals={"delivery_expected": True, "local_time": "14:30"},
        correlation_id="corr-courier-1",
        idempotency_key="idem-courier-1",
    )


def port(
    tmp_path: Path,
    sender: Callable[[str, dict[str, Any]], Awaitable[tuple[int, dict[str, Any]]]],
) -> AgentSafeActionPort:
    return AgentSafeActionPort(
        "http://127.0.0.1:8100",
        "local-caller-token-not-a-production-secret",
        PendingEscalationStore(tmp_path / "audit" / "pending.sqlite3"),
        sender=sender,
    )


@pytest.mark.asyncio
async def test_posts_exact_proposal_to_agentsafe_and_never_adds_trusted_fields(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def sender(path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        calls.append((path, payload))
        return 200, response("ALLOW", outcome="FAILED_BEFORE_DISPATCH", executed=False)

    result = await port(tmp_path, sender).request(proposal())

    assert result.decision == "ALLOW"
    assert result.execution == "NOT_PERFORMED"
    assert result.dossier_id == "dossier-001"
    assert result.grant_id == "grant-001"
    assert result.authorization_expires_at == "2030-01-01T00:00:00Z"
    assert calls == [
        (
            "/v1/actions",
            {
                "proposal": {
                    "action": "unlockDoor",
                    "target": "side_gate",
                    "parameters": {
                        "homebound_purpose": "expected high-value delivery",
                        "context_signals": {"delivery_expected": True, "local_time": "14:30"},
                        "device_parameters": {"unlock_duration_seconds": 30},
                    },
                },
                "idempotency_key": "idem-courier-1",
                "correlation_id": "corr-courier-1",
            },
        )
    ]
    assert "tenant_id" not in calls[0][1]["proposal"]
    assert "actor" not in calls[0][1]["proposal"]


@pytest.mark.asyncio
async def test_managed_escalation_is_saved_and_resumed_unchanged(tmp_path: Path) -> None:
    initial_handoff = {
        "mode": "MANAGED",
        "intent": {"intentId": "intent-001", "expiresAt": "2030-01-01T00:00:00Z"},
        "escalation": {
            "escalationId": "presence-escalation-1",
            "intentId": "intent-001",
            "status": "AWAITING_APPROVER",
            "outcome": "ESCALATE_PENDING",
            "expiresAt": "2030-01-01T00:00:00Z",
            "reasonCodes": ["HUMAN_APPROVAL_REQUIRED"],
        },
    }
    updated_handoff = {
        **initial_handoff,
        "escalation": {**initial_handoff["escalation"], "status": "PRESENCE_REQUESTED"},
    }
    calls: list[tuple[str, dict[str, Any]]] = []
    next_responses = [
        response(
            "ESCALATE",
            outcome="ESCALATE_PENDING",
            executed=False,
            escalation=initial_handoff,
            reason_codes=["HUMAN_APPROVAL_REQUIRED"],
        ),
        response(
            "ESCALATE",
            outcome="ESCALATE_PENDING",
            executed=False,
            escalation=updated_handoff,
            reason_codes=["HUMAN_APPROVAL_REQUIRED"],
        ),
        response("ALLOW", outcome="FAILED_BEFORE_DISPATCH", executed=False),
    ]

    async def sender(path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        calls.append((path, payload))
        return 200, next_responses.pop(0)

    action_port = port(tmp_path, sender)
    first = await action_port.request(proposal())
    assert first.decision == "ESCALATE"
    assert first.execution == "NOT_PERFORMED"
    assert first.escalation_id == "presence-escalation-1"
    stored = action_port._pending.get("corr-courier-1")
    assert stored is not None
    assert stored.handoff == initial_handoff

    second = await action_port.resume("corr-courier-1")
    assert second.decision == "ESCALATE"
    assert calls[1] == ("/v1/escalations", initial_handoff)
    assert action_port._pending.get("corr-courier-1").handoff == updated_handoff

    final = await action_port.resume("corr-courier-1")
    assert final.decision == "ALLOW"
    assert final.execution == "NOT_PERFORMED"
    assert calls[2] == ("/v1/escalations", updated_handoff)
    assert action_port._pending.get("corr-courier-1") is None


@pytest.mark.asyncio
async def test_block_is_reported_without_execution(tmp_path: Path) -> None:
    async def sender(_path: str, _payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return 200, response(
            "BLOCK", outcome="BLOCKED", executed=False, reason_codes=["OUTSIDE_WINDOW"]
        )

    result = await port(tmp_path, sender).request(proposal())
    assert result.decision == "BLOCK"
    assert result.execution == "NOT_PERFORMED"
    assert result.reason_codes == ("OUTSIDE_WINDOW",)
    assert "OUTSIDE_WINDOW" in result.message


@pytest.mark.asyncio
async def test_non_enforcement_and_http_errors_are_not_mapped_to_allow(
    tmp_path: Path,
) -> None:
    async def unavailable(_path: str, _payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return 503, {"code": "AUTHORITY_UNAVAILABLE"}

    result = await port(tmp_path, unavailable).request(proposal())
    assert result.decision == "AUTHORITY_UNAVAILABLE"
    assert result.execution == "NOT_PERFORMED"

    shadow = response("ALLOW", outcome="OBSERVED", executed=False)
    shadow["mode"] = "SHADOW"

    async def observe_only(_path: str, _payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return 200, shadow

    result = await port(tmp_path, observe_only).request(proposal())
    assert result.decision == "AUTHORITY_UNAVAILABLE"
    assert result.execution == "NOT_PERFORMED"


@pytest.mark.asyncio
async def test_expired_presence_handoff_is_closed_as_block_without_execution(tmp_path: Path) -> None:
    handoff = {
        "mode": "MANAGED",
        "intent": {"intentId": "intent-001", "expiresAt": "2026-10-01T00:00:00Z"},
        "escalation": {"escalationId": "presence-1", "status": "AWAITING_APPROVER"},
    }
    calls: list[tuple[str, dict[str, Any]]] = []

    async def sender(path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        calls.append((path, payload))
        if path == "/v1/actions":
            return 200, response(
                "ESCALATE", outcome="ESCALATE_PENDING", executed=False, escalation=handoff
            )
        return 409, {"code": "INTENT_EXPIRED"}

    action_port = port(tmp_path, sender)
    initial = await action_port.request(proposal())
    expired = await action_port.resume(initial.correlation_id)

    assert initial.decision == "ESCALATE"
    assert expired.decision == "BLOCK"
    assert expired.execution == "NOT_PERFORMED"
    assert expired.authority_outcome == "INTENT_EXPIRED"
    assert calls[1] == ("/v1/escalations", handoff)
    assert action_port._pending.get(initial.correlation_id) is None


@pytest.mark.asyncio
async def test_dossier_evidence_and_local_action_record_are_retained(tmp_path: Path) -> None:
    class ArchiveFixture:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def archive(self, dossier_id: str, correlation_id: str) -> dict[str, Any]:
            self.calls.append((dossier_id, correlation_id))
            return {
                "dossier_id": dossier_id,
                "correlation_id": correlation_id,
                "reference": "dossier-archive-ref",
                "verified": True,
                "signature_verified": True,
                "trust_anchor": "DECIONIS_OFFICIAL",
            }

    async def sender(_path: str, _payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return 200, response("BLOCK", outcome="BLOCKED", executed=False)

    archive = ArchiveFixture()
    action_log = ActionAuditLog(tmp_path / "audit" / "actions.jsonl")
    action_port = AgentSafeActionPort(
        "http://127.0.0.1:8100",
        "local-caller-token-not-a-production-secret",
        PendingEscalationStore(tmp_path / "audit" / "pending.sqlite3"),
        dossier_archiver=archive,  # type: ignore[arg-type]
        audit_log=action_log,
        sender=sender,
    )

    result = await action_port.request(proposal())

    assert result.decision == "BLOCK"
    assert result.execution == "NOT_PERFORMED"
    assert result.dossier_evidence["verified"] is True
    assert result.audit_recorded is True
    assert archive.calls == [("dossier-001", "corr-courier-1")]
    saved = json.loads((tmp_path / "audit" / "actions.jsonl").read_text())
    assert saved["proposal"]["target"] == "side_gate"
    assert saved["result"]["authority_outcome"] == "BLOCKED"
    assert saved["dossier_evidence"]["signature_verified"] is True


@pytest.mark.asyncio
async def test_dossier_archive_failure_still_records_fail_closed_governance_audit(
    tmp_path: Path,
) -> None:
    class FailingArchive:
        def archive(self, _dossier_id: str, _correlation_id: str) -> dict[str, Any]:
            raise RuntimeError("connection refused")

    async def sender(_path: str, _payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return 200, response("BLOCK", outcome="BLOCKED", executed=False)

    log = ActionAuditLog(tmp_path / "audit" / "actions.jsonl")
    action_port = AgentSafeActionPort(
        "http://127.0.0.1:8100",
        "local-caller-token-not-a-production-secret",
        PendingEscalationStore(tmp_path / "audit" / "pending.sqlite3"),
        dossier_archiver=FailingArchive(),  # type: ignore[arg-type]
        audit_log=log,
        sender=sender,
    )

    result = await action_port.request(proposal())

    assert result.decision == "BLOCK"
    assert result.execution == "NOT_PERFORMED"
    assert result.dossier_evidence == {
        "dossier_id": "dossier-001",
        "correlation_id": "corr-courier-1",
        "verified": False,
        "error_code": "DOSSIER_ARCHIVE_UNAVAILABLE",
    }
    assert result.audit_recorded is True
    saved = json.loads((tmp_path / "audit" / "actions.jsonl").read_text())
    assert saved["result"]["decision"] == "BLOCK"
    assert saved["dossier_evidence"]["verified"] is False


@pytest.mark.asyncio
async def test_real_http_transport_sets_bearer_and_uses_executor_path(tmp_path: Path) -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            200,
            json=response("BLOCK", outcome="BLOCKED", executed=False),
        )

    action_port = AgentSafeActionPort(
        "http://127.0.0.1:8100",
        "local-caller-token-not-a-production-secret",
        PendingEscalationStore(tmp_path / "audit" / "pending.sqlite3"),
        transport_factory=lambda: httpx2.MockTransport(handler),
    )
    result = await action_port.request(proposal())

    assert result.decision == "BLOCK"
    assert seen[0].url.path == "/v1/actions"
    assert seen[0].headers["authorization"] == "Bearer local-caller-token-not-a-production-secret"
    body = json.loads(seen[0].content)
    assert body["proposal"]["target"] == "side_gate"
