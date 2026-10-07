"""Managed handoffs survive outages and are serialized before the authority is checked."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from test_agentsafe_http import port, proposal, response


def handoff() -> dict[str, Any]:
    return {
        "mode": "MANAGED",
        "intent": {"intentId": "intent-001", "expiresAt": "2030-01-01T00:00:00Z"},
        "escalation": {
            "escalationId": "presence-1", "intentId": "intent-001",
            "status": "AWAITING_APPROVER", "outcome": "ESCALATE_PENDING",
            "expiresAt": "2030-01-01T00:01:00Z", "reasonCodes": ["HUMAN_APPROVAL_REQUIRED"],
        },
    }


def pending_response() -> dict[str, Any]:
    return response("ESCALATE", outcome="ESCALATE_PENDING", executed=False, escalation=handoff())


@pytest.mark.asyncio
async def test_temporary_managed_authority_failure_does_not_close_the_handoff(tmp_path: Path) -> None:
    calls = []
    unavailable = response("BLOCK", outcome="BLOCKED", executed=False, reason_codes=["MANAGED_ESCALATION_STATUS_FAILED"])
    unavailable["fail_closed"] = True
    answers = [pending_response(), unavailable, response("ALLOW", outcome="COMPLETED", executed=True)]

    async def sender(path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        calls.append((path, deepcopy(body)))
        return 200, answers.pop(0)

    service = port(tmp_path, sender)
    first = await service.request(proposal())
    assert first.escalation_status == "AWAITING_APPROVER"
    assert first.escalation_mode == "MANAGED"
    assert first.escalation_expires_at == "2030-01-01T00:00:00Z"
    failed = await service.resume(first.correlation_id)
    assert failed.decision == "AUTHORITY_UNAVAILABLE"
    assert service._pending.get(first.correlation_id).handoff == handoff()
    assert failed.escalation_id == first.escalation_id
    completed = await service.resume(first.correlation_id)
    assert completed.execution == "PERFORMED" and completed.escalation_status == "GRANT_READY"
    assert calls[1][1] == calls[2][1] == handoff()
    assert service._pending.get(first.correlation_id) is None


@pytest.mark.asyncio
async def test_parallel_resumes_make_only_one_authority_call_after_completion(tmp_path: Path) -> None:
    entered, release = asyncio.Event(), asyncio.Event()
    checks = []

    async def sender(path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if path == "/v1/actions":
            return 200, pending_response()
        checks.append(body)
        entered.set()
        await release.wait()
        return 200, response("ALLOW", outcome="COMPLETED", executed=True)

    service = port(tmp_path, sender)
    initial = await service.request(proposal())
    first = asyncio.create_task(service.resume(initial.correlation_id))
    await entered.wait()
    second = asyncio.create_task(service.resume(initial.correlation_id))
    release.set()
    results = await asyncio.gather(first, second)
    assert len(checks) == 1
    assert results[0].execution == "PERFORMED"
    assert results[1].reason_codes == ("ESCALATION_NOT_FOUND",)


@pytest.mark.asyncio
async def test_missing_updated_handoff_does_not_destroy_the_original(tmp_path: Path) -> None:
    calls = []

    async def sender(path: str, _body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        calls.append(path)
        return 200, pending_response() if len(calls) == 1 else response("ESCALATE", outcome="ESCALATE_PENDING", executed=False)

    service = port(tmp_path, sender)
    first = await service.request(proposal())
    failed = await service.resume(first.correlation_id)
    assert failed.decision == "AUTHORITY_UNAVAILABLE"
    assert failed.reason_codes == ("ESCALATION_HANDOFF_MISSING",)
    assert service._pending.get(first.correlation_id).handoff == handoff()


@pytest.mark.asyncio
async def test_lost_executor_response_is_unknown_and_keeps_handoff_for_reconciliation(tmp_path: Path) -> None:
    async def sender(path: str, _body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return (200, pending_response()) if path == "/v1/actions" else (503, {"code": "AGENTSAFE_UNREACHABLE"})

    service = port(tmp_path, sender)
    first = await service.request(proposal())
    failed = await service.resume(first.correlation_id)
    assert failed.decision == "AUTHORITY_UNAVAILABLE" and failed.execution == "UNKNOWN"
    assert service._pending.get(first.correlation_id).handoff == handoff()
    assert "No Ring action ran" not in failed.message


@pytest.mark.asyncio
async def test_unknown_after_dispatch_is_not_reported_as_not_performed_or_replayed(tmp_path: Path) -> None:
    calls = []

    async def sender(path: str, _body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        calls.append(path)
        return 200, pending_response() if len(calls) == 1 else response("ALLOW", outcome="UNKNOWN_AFTER_DISPATCH", executed=None)

    service = port(tmp_path, sender)
    first = await service.request(proposal())
    uncertain = await service.resume(first.correlation_id)
    assert uncertain.execution == "UNKNOWN"
    assert service._pending.get(first.correlation_id) is None
    await service.resume(first.correlation_id)
    assert calls == ["/v1/actions", "/v1/escalations"]
