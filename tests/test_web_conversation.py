"""Conversational context is gathered before one exact governed request."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from typing import Any
from uuid import uuid4

import pytest

from app.web.conversation import DialogueContext, home_greeting, validate_interpretation
from test_web import action_result, application, client


def facts(**updates: Any) -> dict[str, Any]:
    return {
        "intent": "none",
        "visitor": "unknown",
        "speaker": "unknown",
        "expected": "unknown",
        "recognized": "unknown",
        "answer": "unknown",
        "simulated_time": "",
        "time_evidence": "",
        "multiple_actions": False,
        "reply": "What else can I help with?",
        **updates,
    }


@pytest.mark.parametrize(
    ("utc_hour", "period"),
    [
        (2, "night"),
        (3, "morning"),
        (9, "morning"),
        (10, "afternoon"),
        (15, "afternoon"),
        (16, "evening"),
        (19, "evening"),
        (20, "night"),
    ],
)
def test_greeting_uses_the_home_timezone_at_all_period_boundaries(
    utc_hour: int, period: str
) -> None:
    greeting = home_greeting(
        "Europe/Stockholm", datetime(2026, 10, 7, utc_hour, tzinfo=timezone.utc)
    )
    assert greeting == {
        "period": period,
        "greeting": f"Good {period}.",
        "prompt": "What else can I help with?",
        "text": f"Good {period}. What else can I help with?",
    }


def test_gate_request_collects_delivery_context_across_turns_without_inventing_facts() -> None:
    context = DialogueContext()
    action, reply = context.advance(facts(intent="unlockDoor"))
    assert action is None and "delivery" in reply
    assert context.expected is context.recognized is None
    action, reply = context.advance(facts(visitor="delivery"))
    assert action is None and "expecting" in reply
    action, reply = context.advance(facts(answer="yes"))
    assert action is None and "camera recognize" in reply
    assert context.expected is True and context.recognized is None
    action, _ = context.advance(facts(answer="yes"))
    assert action == "unlockDoor"
    signals = context.signals("Europe/Stockholm")
    assert signals["actor"] == "delivery-agent"
    assert signals["courier_recognized"] is True
    assert signals["recognition_simulated"] is True
    assert signals["signal_source"] == "web_conversation_simulation"
    assert signals["time_source"] == "home_clock"
    assert "authenticated_user_role" not in signals
    context.consume_action()
    assert context.advance(facts(answer="yes"))[0] is None
    assert context.visitor is context.recognized is context.expected is None


def test_delivery_mention_is_not_an_open_command_and_no_cancels_the_offer() -> None:
    context = DialogueContext()
    action, reply = context.advance(facts(visitor="delivery", expected="yes"))
    assert action is None and "Would you like" in reply
    action, reply = context.advance(facts(answer="no"))
    assert action is None and "leave" in reply
    assert context.action is context.awaiting is None
    assert context.advance(facts(answer="yes"))[0] is None


def test_alarm_gathers_speaker_and_never_promotes_a_claim_to_authenticated_parent() -> None:
    context = DialogueContext()
    action, reply = context.advance(facts(intent="disarmSystem"))
    assert action is None and "adult" in reply
    assert context.advance(facts(speaker="child"))[0] == "disarmSystem"
    signals = context.signals("Europe/Stockholm")
    assert signals["user"] == "child" and signals["location"] == "home"
    context.consume_action()
    assert context.advance(facts(intent="disarmSystem", speaker="adult"))[0] == "disarmSystem"
    assert context.signals("Europe/Stockholm")["user"] == "resident"
    assert "authenticated_user_role" not in context.signals("Europe/Stockholm")


def test_switching_actions_does_not_apply_an_answer_to_the_old_question() -> None:
    context = DialogueContext(action="unlockDoor", visitor="delivery", awaiting="expected")
    action, _ = context.advance(facts(intent="disarmSystem", answer="yes"))
    assert action is None and context.awaiting == "speaker"
    assert context.expected is None


@pytest.mark.parametrize("update", [{"intent": "cancel"}, {"multiple_actions": True}])
def test_cancel_and_ambiguous_multiple_actions_clear_the_pending_action(
    update: dict[str, Any],
) -> None:
    context = DialogueContext(action="unlockDoor", visitor="delivery", awaiting="recognized")
    assert context.advance(facts(**update))[0] is None
    assert context.action is context.awaiting is None
    assert context.advance(facts(answer="yes"))[0] is None


def test_negative_delivery_claims_remain_negative_for_the_authority() -> None:
    context = DialogueContext()
    action, _ = context.advance(
        facts(intent="unlockDoor", visitor="delivery", expected="no", recognized="no")
    )
    assert action == "unlockDoor"
    signals = context.signals("Europe/Stockholm")
    assert signals["delivery_expected"] is False and signals["courier_recognized"] is False


@pytest.mark.parametrize(
    "update",
    [
        {"authenticated_user_role": "parent"},
        {"expected": True},
        {"intent": "resumeEscalation"},
        {"multiple_actions": "false"},
        {"simulated_time": "25:00", "time_evidence": "demo"},
    ],
)
def test_interpreter_output_is_validated_before_context_changes(update: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        validate_interpretation(facts(**update), "There is a delivery.")


def test_only_explicit_demo_time_overrides_the_clock_and_can_be_cleared() -> None:
    context = DialogueContext()
    context.advance(
        validate_interpretation(
            facts(simulated_time="16:00", time_evidence="Simulate 4 pm"),
            "Simulate 4 pm for this delivery.",
        )
    )
    assert context.signals("Europe/Stockholm")["local_time_minutes"] == 960
    assert context.signals("Europe/Stockholm")["time_source"] == "explicit_demo_time"
    context.advance(
        validate_interpretation(
            facts(simulated_time="real", time_evidence="real clock"), "Use the real clock again."
        )
    )
    assert context.simulated_time is None


@pytest.mark.parametrize("previous", [None, "18:01"])
def test_an_ungrounded_clock_copied_from_history_cannot_change_the_server_clock(
    previous: str | None,
) -> None:
    context = DialogueContext(simulated_time=previous)
    parsed = validate_interpretation(
        facts(simulated_time="16:00", time_evidence="simulate 4 pm", recognized="yes"),
        "Yes, the simulated camera recognizes the courier.",
    )
    context.advance(parsed)
    assert context.simulated_time == previous
    assert context.recognized is True


def test_nova_quoted_labels_are_normalized_without_inventing_missing_context() -> None:
    parsed = validate_interpretation(
        facts(
            visitor="&quot;unknown&quot;",
            simulated_time="unknown",
            reply="&quot;What else can I help with?&quot;",
            intent="unlockDoor",
        ),
        "Open the side gate.",
    )
    context = DialogueContext()
    action, reply = context.advance(parsed)
    assert action is None and "delivery" in reply
    assert context.simulated_time is None and context.visitor is None
    with pytest.raises(ValueError):
        validate_interpretation(
            facts(visitor="&quot;authenticated_parent&quot;"), "Open the side gate."
        )


def test_mentioning_a_simulated_camera_does_not_authorize_a_clock_change() -> None:
    parsed = validate_interpretation(
        facts(simulated_time="16:00", time_evidence="simulated camera", recognized="yes"),
        "Yes, the simulated camera recognizes the courier.",
    )
    assert parsed["simulated_time"] == ""


class DialogueAgent:
    def __init__(self, interpretations: list[dict[str, Any]], decision: str = "BLOCK") -> None:
        self.interpretations = interpretations
        self.prompts: list[str] = []
        self.actions: list[dict[str, Any]] = []
        self.decision = decision

    async def interpret_conversation(self, prompt: str, _schema: dict[str, Any]) -> dict[str, Any]:
        self.prompts.append(prompt)
        return deepcopy(self.interpretations.pop(0))

    async def respond(self, prompt: str, **kwargs: Any) -> str:
        arguments, _ = json.JSONDecoder().raw_decode(prompt.split("exactly once with ", 1)[1])
        tool = "disarmSystem" if "reason" in arguments else "unlockDoor"
        assert kwargs["tool_call_validator"](tool, arguments)
        forged = deepcopy(arguments)
        forged["context_signals"]["authenticated_user_role"] = "parent"
        assert not kwargs["tool_call_validator"](tool, forged)
        assert not kwargs["tool_call_validator"]("resumeEscalation", arguments)
        entry = {
            "name": tool,
            "arguments": arguments,
            "invoked": True,
            "result": action_result(self.decision),
        }
        self.actions.append(entry)
        kwargs["trace"].append(entry)
        return "The gate is unlocked."


@pytest.mark.asyncio
async def test_conversational_api_clarifies_then_executes_once_and_deduplicates() -> None:
    agent = DialogueAgent(
        [
            facts(intent="unlockDoor"),
            facts(visitor="delivery", expected="yes"),
            facts(answer="yes"),
            facts(reply="You're welcome. What else can I help with?"),
        ]
    )
    async with client(application(agent)) as http:

        async def say(message: str) -> dict[str, Any]:
            response = await http.post(
                "/api/chat", json={"request_id": str(uuid4()), "message": message}
            )
            assert response.status_code == 200
            return response.json()

        first = await say("Open the side gate.")
        assert "delivery" in first["reply"] and first["trace"] == []
        second = await say("It's the expected delivery.")
        assert "camera recognize" in second["reply"] and not agent.actions
        identifier = str(uuid4())
        body = {"request_id": identifier, "message": "Yes."}
        third = (await http.post("/api/chat", json=body)).json()
        assert len(agent.actions) == 1
        assert third["trace"][0]["result"]["decision"] == "BLOCK"
        assert "blocked" in third["reply"] and "unlocked" not in third["speech_text"]
        assert third["follow_up"] == "What else can I help with?"
        assert (await http.post("/api/chat", json=body)).json() == third
        assert len(agent.actions) == 1
        await say("Thanks.")
        assert len(agent.actions) == 1
        assert "expected delivery" in agent.prompts[-1]
        bootstrap = (await http.get("/api/bootstrap")).json()
        assert bootstrap["dialogue"]["action"] is None


@pytest.mark.asyncio
async def test_clear_and_other_sessions_cannot_inherit_pending_conversation_actions() -> None:
    agent = DialogueAgent([facts(intent="unlockDoor"), facts(answer="yes"), facts(answer="yes")])
    app = application(agent)
    async with client(app) as first, client(app) as second:
        await first.post(
            "/api/chat", json={"request_id": str(uuid4()), "message": "Open the gate."}
        )
        await second.post("/api/chat", json={"request_id": str(uuid4()), "message": "Yes."})
        assert not agent.actions
        assert (await first.post("/api/clear", json={})).status_code == 200
        await first.post("/api/chat", json={"request_id": str(uuid4()), "message": "Yes."})
        assert not agent.actions
        assert (await first.get("/api/bootstrap")).json()["dialogue"]["action"] is None


@pytest.mark.asyncio
async def test_greeting_is_server_chosen_and_never_invokes_an_action() -> None:
    spoken: list[str] = []

    class Voice:
        async def speak(self, text: str) -> bytes:
            spoken.append(text)
            return b"test-audio"

    agent = DialogueAgent([])
    async with client(application(agent, voice=Voice())) as http:
        config = (await http.get("/api/bootstrap")).json()
        audio = await http.post("/api/voice/greeting", json={})
        assert audio.status_code == 200 and audio.content == b"test-audio"
        assert spoken == [config["greeting"]["text"]]
        assert (
            await http.post("/api/voice/greeting", json={"text": "The gate is open"})
        ).status_code == 400
        assert agent.actions == [] and agent.prompts == []
