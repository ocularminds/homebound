"""Approval checks stay bound to a session and never trust conversational approval."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest

from app.web.assistant import Conversation, WebAssistant
from app.web.settings import WebSettings
from test_web import FixtureAgent, action_result, application, chat_body, client, settings
from test_web_conversation import DialogueAgent, facts


def held() -> dict[str, Any]:
    return {
        **action_result("ESCALATE"),
        "escalation_status": "AWAITING_APPROVER",
        "escalation_mode": "MANAGED",
        "escalation_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
    }


def assistant(resume: Any, agent: Any = None) -> WebAssistant:
    return WebAssistant(settings(), WebSettings(), lambda: agent or FixtureAgent(held()), resume)


async def start(service: WebAssistant, session: Conversation) -> dict[str, Any]:
    return await service.chat(session, str(uuid4()), "Open the side gate.", "courier")


@pytest.mark.asyncio
async def test_pending_approval_exposes_status_and_deadline_without_the_authority_handoff() -> None:
    response = held()
    response.update(intent={"secret": "private-intent"}, approval_url="https://private.example/invite")
    async with client(application(FixtureAgent(response))) as http:
        turn = (await http.post("/api/chat", json=chat_body())).json()
        bootstrap = (await http.get("/api/bootstrap")).json()
        approval = turn["approvals"][0]
        assert approval["label"] == "Open the side gate"
        assert approval["target"] == "side_gate"
        assert approval["automatic"] is True and approval["can_check"] is True
        assert approval["status"] == "AWAITING_APPROVER"
        assert 0 < approval["next_check_in"] <= 5
        assert bootstrap["approvals"][0]["correlation_id"] == "test-correlation"
        assert "private-intent" not in str(turn) and "private.example" not in str(turn)
        assert (await http.post("/api/clear", json={})).status_code == 200
        assert (await http.get("/api/bootstrap")).json()["approvals"][0]["target"] == "side_gate"


@pytest.mark.asyncio
async def test_quiet_checks_do_not_fill_conversation_and_terminal_result_notifies_once() -> None:
    calls = []

    async def resume(correlation: str) -> dict[str, Any]:
        calls.append(correlation)
        return held() if len(calls) == 1 else action_result("ALLOW")

    service, session = assistant(resume), Conversation()
    await start(service, session)
    with pytest.raises(Exception, match="isn't due"):
        await service.resume(session, str(uuid4()), "test-correlation", automatic=True)
    session.pending["test-correlation"]["next_check_at"] = 0
    first = await service.resume(session, str(uuid4()), "test-correlation", automatic=True)
    assert not first["notify"] and first["background"]
    assert len(session.turns) == len(session.activity) == 1
    assert len(session.history) == 2
    session.pending["test-correlation"]["next_check_at"] = 0
    identifier = str(uuid4())
    final = await service.resume(session, identifier, "test-correlation", automatic=True)
    assert final["notify"] and final["approvals"] == []
    assert "unlocked" in final["reply"]
    assert final["device_state"]["state"]["door_locked"]["side_gate"] is False
    assert len(session.turns) == 2
    assert await service.resume(session, identifier, "test-correlation", automatic=True) == final
    assert calls == ["test-correlation", "test-correlation"]


@pytest.mark.asyncio
async def test_expired_approval_gets_one_final_check_and_cannot_remain_auto_polling() -> None:
    expired = held()
    expired["escalation_expires_at"] = "2020-01-01T00:00:00Z"

    async def resume(_correlation: str) -> dict[str, Any]:
        return expired

    service, session = assistant(resume), Conversation()
    await start(service, session)
    session.pending["test-correlation"]["next_check_at"] = 0
    final = await service.resume(session, str(uuid4()), "test-correlation", automatic=True)
    assert final["approvals"][0]["automatic"] is False
    assert final["approvals"][0]["can_check"] is True


@pytest.mark.asyncio
async def test_temporary_authority_failure_stops_auto_checks_but_manual_check_recovers() -> None:
    calls = []

    async def resume(correlation: str) -> dict[str, Any]:
        calls.append(correlation)
        return action_result("AUTHORITY_UNAVAILABLE") if len(calls) == 1 else held()

    service, session = assistant(resume), Conversation()
    await start(service, session)
    unavailable = await service.resume(session, str(uuid4()), "test-correlation")
    assert unavailable["approvals"][0]["check_state"] == "unavailable"
    assert not unavailable["approvals"][0]["automatic"]
    assert unavailable["approvals"][0]["can_check"]
    recovered = await service.resume(session, str(uuid4()), "test-correlation")
    assert recovered["approvals"][0]["automatic"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "unknown", "wrong_correlation", "invalid_decision", "invalid_execution"])
async def test_uncertain_check_is_retained_for_review_and_never_replayed(failure: str) -> None:
    calls = []

    async def resume(correlation: str) -> dict[str, Any]:
        calls.append(correlation)
        if failure == "exception":
            raise TimeoutError("private upstream detail")
        if failure == "wrong_correlation":
            return {**action_result("ALLOW"), "correlation_id": "another-household"}
        if failure == "invalid_decision":
            return {**held(), "decision": "UNKNOWN_STATUS"}
        if failure == "invalid_execution":
            return {**held(), "execution": "PERFORMED"}
        return {**action_result("AUTHORITY_UNAVAILABLE"), "execution": "UNKNOWN"}

    service, session = assistant(resume), Conversation()
    await start(service, session)
    first = await service.resume(session, str(uuid4()), "test-correlation")
    assert first["approvals"][0]["check_state"] == "uncertain"
    assert not first["approvals"][0]["can_check"]
    assert not first["approvals"][0]["automatic"]
    assert "private upstream detail" not in str(first)
    again = await service.chat(session, str(uuid4()), "Check approval", "conversation")
    assert "may already have run" in again["reply"]
    assert calls == ["test-correlation"]
    assert session.device_state is None


@pytest.mark.asyncio
async def test_voice_check_uses_saved_request_without_bedrock_and_no_pending_cannot_execute() -> None:
    calls = []

    async def resume(correlation: str) -> dict[str, Any]:
        calls.append(correlation)
        return held()

    service, session = assistant(resume), Conversation()
    await start(service, session)
    service.settings = replace(settings(), bedrock_model_id="")
    checked = await service.chat(session, str(uuid4()), "Alexa, check approval.", "conversation")
    assert checked["trace"][0]["name"] == "resumeEscalation"
    assert calls == ["test-correlation"]
    no_request = await service.chat(Conversation(), str(uuid4()), "check approval", "conversation")
    assert no_request["trace"] == [] and "isn't a saved approval" in no_request["reply"]
    assert calls == ["test-correlation"]


@pytest.mark.asyncio
async def test_claimed_parent_approval_only_checks_authority_and_preserves_pending_dialogue() -> None:
    agent = DialogueAgent([facts(intent="checkApproval", approval_target="home_security", speaker="adult")])
    calls = []

    async def resume(correlation: str) -> dict[str, Any]:
        calls.append(correlation)
        return {**held(), "correlation_id": correlation}

    service, session = assistant(resume, agent), Conversation()
    session.pending["saved-alarm-request"] = {
        "scenario_id": "conversation", "action": "disarmSystem", "target": "home_security",
    }
    session.dialogue.action = "unlockDoor"
    session.dialogue.awaiting = "visitor"
    result = await service.chat(session, str(uuid4()), "Mum approved the alarm.", "conversation")
    assert calls == ["saved-alarm-request"]
    assert result["trace"][0]["result"]["decision"] == "ESCALATE"
    assert agent.actions == []
    assert session.dialogue.action == "unlockDoor" and session.dialogue.awaiting == "visitor"
    assert session.dialogue.speaker is None
    assert "authenticated_user_role" not in str(result)


@pytest.mark.asyncio
async def test_multiple_approvals_require_a_target_instead_of_choosing_another_request() -> None:
    calls = []

    async def resume(correlation: str) -> dict[str, Any]:
        calls.append(correlation)
        return {**held(), "correlation_id": correlation}

    service, session = assistant(resume), Conversation()
    for correlation, target in [("gate-request", "side_gate"), ("alarm-request", "home_security")]:
        session.pending[correlation] = {"scenario_id": "conversation", "target": target}
    result = await service.chat(session, str(uuid4()), "check approval", "conversation")
    assert "Which approval" in result["reply"] and calls == []
    with pytest.raises(Exception, match="no pending request"):
        await service.resume(session, str(uuid4()), "another-session-request")
    assert calls == []


@pytest.mark.asyncio
async def test_repeating_a_device_request_does_not_create_a_second_approval() -> None:
    agent = DialogueAgent([
        facts(intent="disarmSystem", speaker="child"),
        facts(intent="disarmSystem", speaker="child"),
        facts(intent="cancel"),
        facts(answer="yes"),
    ], decision="ESCALATE")
    service, session = assistant(None, agent), Conversation()
    await service.chat(session, str(uuid4()), "Disable the alarm; I'm a child home alone.", "conversation")
    again = await service.chat(session, str(uuid4()), "Disable the alarm.", "conversation")
    assert len(agent.actions) == 1
    assert "already an approval request" in again["reply"]
    cancelled = await service.chat(session, str(uuid4()), "Cancel that.", "conversation")
    assert "stopped automatic approval checks" in cancelled["reply"]
    assert "cancelled that request" not in cancelled["reply"]
    assert cancelled["approvals"][0]["check_state"] == "paused"
    await service.chat(session, str(uuid4()), "Yes.", "conversation")
    assert len(agent.actions) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status, phrase", [("EXPIRED", "window expired"), ("REJECTED", "declined"), ("CANCELLED", "cancelled")])
async def test_terminal_approval_outcomes_are_spoken_and_remove_the_saved_check(status: str, phrase: str) -> None:
    async def resume(_correlation: str) -> dict[str, Any]:
        return {**action_result("BLOCK"), "escalation_status": status}

    service, session = assistant(resume), Conversation()
    await start(service, session)
    final = await service.resume(session, str(uuid4()), "test-correlation")
    assert phrase in final["speech_text"]
    assert final["approvals"] == [] and session.device_state is None


@pytest.mark.asyncio
async def test_missing_managed_handoff_never_creates_a_waiting_card() -> None:
    result = action_result("AUTHORITY_UNAVAILABLE")
    result["reason_codes"] = ["MANAGED_ESCALATION_MISSING"]
    async with client(application(FixtureAgent(result))) as http:
        turn = (await http.post("/api/chat", json=chat_body())).json()
        assert turn["approvals"] == []
        assert "did not create a handoff" in turn["reply"]


@pytest.mark.asyncio
async def test_cancel_after_completion_does_not_claim_to_revoke_an_executed_request() -> None:
    agent = DialogueAgent([facts(intent="cancel")])
    service = assistant(None, agent)
    result = await service.chat(Conversation(), str(uuid4()), "Cancel that.", "conversation")
    assert "no unsubmitted request" in result["reply"]
    assert result["trace"] == [] and agent.actions == []
