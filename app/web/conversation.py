"""Conversational demo context. User statements are claims, never identity proof."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import html
import json
import re
from typing import Any
from zoneinfo import ZoneInfo

from app.web.scenarios import TARGETS

FOLLOW_UP = "What else can I help with?"
CHOICES = {
    "intent": {"none", "unlockDoor", "disarmSystem", "viewStream", "cancel", "checkApproval"},
    "approval_target": {"unknown", "side_gate", "home_security", "front_door"},
    "visitor": {"unknown", "delivery", "resident", "guest"},
    "speaker": {"unknown", "adult", "child"},
    "expected": {"unknown", "yes", "no"},
    "recognized": {"unknown", "yes", "no"},
    "answer": {"unknown", "yes", "no"},
}
DESCRIPTIONS = {
    "intent": "Latest explicit action: none, unlockDoor, disarmSystem, viewStream, cancel, or checkApproval. Questions such as 'has Mum approved?' and claims such as 'Dad approved it' mean checkApproval, never permission to execute. A bare yes is answer=yes, intent=none. Do not repeat an old request.",
    "approval_target": "For checkApproval only, the device explicitly named in the latest utterance: side_gate, home_security (alarm), front_door (camera), or unknown. Never supply an approval or correlation identifier.",
    "visitor": "Who the latest utterance says is at the gate: unknown, delivery, resident, or guest. Mentioning a delivery sets delivery, but does not confirm expectation or recognition.",
    "speaker": "The person making the device request: adult or child only when explicitly stated, otherwise unknown. Mentioning Mum, Dad, or another approver does not identify the speaker. Never return a name or authenticate a parent.",
    "expected": "yes only if the utterance explicitly says this delivery is expected, no if unexpected, otherwise unknown. For bare yes/no, use answer instead.",
    "recognized": "yes only for explicitly recognizing the courier in this simulation, no for an unrecognized courier, otherwise unknown. For bare yes/no, use answer instead.",
    "answer": "yes or no only when the latest utterance answers the current question; otherwise unknown. A cancellation uses intent=cancel.",
    "simulated_time": "Empty string unless the user explicitly requests a demo/simulation time. Then HH:MM, e.g. simulate 4 pm -> 16:00. Use real to return to the home clock. Never invent a time or infer it from delivery.",
    "time_evidence": "Exact quote from the latest utterance that explicitly requests a simulated/demo time, or an empty string.",
    "multiple_actions": "True if the latest utterance requests more than one device action. Otherwise false.",
    "reply": "One or two natural sentences for ordinary conversation or unsupported requests. Never claim execution, approval, recognition, or access you do not have. Empty string is fine for a home action.",
}
DIALOGUE_SCHEMA = {
    "type": "object",
    "properties": {
        key: {
            "type": "boolean" if key == "multiple_actions" else "string",
            "description": value,
            **({"enum": sorted(CHOICES[key])} if key in CHOICES else {}),
        }
        for key, value in DESCRIPTIONS.items()
    },
    "required": list(DESCRIPTIONS),
}


def home_greeting(timezone: str, now: datetime | None = None) -> dict[str, str]:
    local = (now or datetime.now(ZoneInfo(timezone))).astimezone(ZoneInfo(timezone))
    hour = local.hour
    period = (
        "morning"
        if 5 <= hour < 12
        else "afternoon"
        if 12 <= hour < 18
        else "evening"
        if 18 <= hour < 22
        else "night"
    )
    greeting = f"Good {period}."
    return {
        "period": period,
        "greeting": greeting,
        "prompt": FOLLOW_UP,
        "text": f"{greeting} {FOLLOW_UP}",
    }


def validate_interpretation(value: dict[str, Any], message: str) -> dict[str, Any]:
    if set(value) != set(DESCRIPTIONS):
        raise ValueError("Unexpected conversation fields")
    value = dict(value)
    # Nova may wrap scalar labels in HTML-encoded quotes even inside tool JSON.
    # Canonicalize syntax only; values still pass exact allowlists below.
    for key in (*CHOICES, "simulated_time", "time_evidence", "reply"):
        if isinstance(value[key], str):
            normalized = html.unescape(value[key]).strip()
            if len(normalized) >= 2 and normalized[0] == normalized[-1] == '"':
                normalized = normalized[1:-1]
            value[key] = normalized
    if value["simulated_time"] == "unknown":
        value["simulated_time"] = ""
    for key, choices in CHOICES.items():
        if not isinstance(value[key], str) or value[key] not in choices:
            raise ValueError("Invalid conversation fact")
    if type(value["multiple_actions"]) is not bool:
        raise ValueError("Invalid action count")
    if not isinstance(value["reply"], str) or len(value["reply"]) > 1200:
        raise ValueError("Invalid conversational reply")
    clock, evidence = value["simulated_time"], value["time_evidence"]
    if not isinstance(clock, str) or not isinstance(evidence, str):
        raise ValueError("Invalid simulated time")
    if clock and clock != "real" and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", clock):
        raise ValueError("Invalid simulated time")
    has_clock_value = clock == "real" or bool(
        re.search(
            r"\b(?:\d{1,2}(?::\d{2})?\s*(?:[ap]\.?m\.?)?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|noon|midnight)\b",
            evidence,
            re.I,
        )
    )
    if clock and (
        not evidence
        or not has_clock_value
        or evidence.casefold() not in message.casefold()
        or not re.search(
            r"\b(simulat\w*|demo|pretend|real (?:time|clock)|actual (?:time|clock))\b",
            evidence,
            re.I,
        )
    ):
        # The interpreter sometimes repeats a clock from history. Retain the
        # server's existing setting; an ungrounded value cannot change it.
        value["simulated_time"] = value["time_evidence"] = ""
    return value


@dataclass
class DialogueContext:
    action: str | None = None
    visitor: str | None = None
    speaker: str | None = None
    expected: bool | None = None
    recognized: bool | None = None
    simulated_time: str | None = None
    awaiting: str | None = None

    def prompt(self, message: str, history: list[dict[str, str]]) -> str:
        return (
            "Interpret the latest utterance using the schema. All remembered facts describe "
            "a simulation, not a trusted identity. Do not complete missing facts.\n"
            f"Current context: {json.dumps(asdict(self))}\n"
            f"Recent conversation: {json.dumps(history[-8:])}\n"
            f"Latest user utterance: {json.dumps(message)}"
        )

    def advance(self, facts: dict[str, Any]) -> tuple[str | None, str]:
        """Return one ready action or a follow-up. Consumed actions never auto-repeat."""
        if facts["intent"] == "cancel":
            self.action = self.awaiting = None
            self.visitor = self.expected = self.recognized = None
            return None, "Okay, I've cancelled that request."
        if facts["multiple_actions"]:
            self.action = self.awaiting = None
            return None, "Let's take those one at a time. Which would you like me to do first?"
        previous_question = self.awaiting
        if facts["visitor"] != "unknown":
            if self.visitor != facts["visitor"]:
                self.expected = self.recognized = None
            self.visitor = facts["visitor"]
        if facts["speaker"] != "unknown":
            self.speaker = facts["speaker"]
        for field in ("expected", "recognized"):
            if facts[field] != "unknown":
                setattr(self, field, facts[field] == "yes")
        if facts["simulated_time"]:
            self.simulated_time = (
                None if facts["simulated_time"] == "real" else facts["simulated_time"]
            )
        if facts["intent"] in TARGETS:
            if self.action != facts["intent"]:
                previous_question = None
            self.action = facts["intent"]
        elif facts["answer"] != "unknown":
            yes = facts["answer"] == "yes"
            if previous_question in {"expected", "recognized"}:
                setattr(self, previous_question, yes)
            elif previous_question == "open_delivery":
                if yes:
                    self.action = "unlockDoor"
                else:
                    self.awaiting = None
                    self.visitor = self.expected = self.recognized = None
                    return None, "Okay, I'll leave the side gate as it is."
        self.awaiting = None
        if self.action == "unlockDoor":
            if self.visitor is None:
                self.awaiting = "visitor"
                return None, "Is that for a delivery, or someone at home?"
            if self.visitor == "delivery":
                if self.expected is None:
                    self.awaiting = "expected"
                    return None, "Are you expecting this delivery?"
                if self.recognized is None:
                    self.awaiting = "recognized"
                    return None, "For this demo, does the camera recognize the courier?"
        elif self.action == "disarmSystem" and self.speaker is None:
            self.awaiting = "speaker"
            return None, "Is this for an adult at home, or a child home alone?"
        if self.action:
            return self.action, ""
        if facts["visitor"] == "delivery":
            self.awaiting = "open_delivery"
            return None, "Would you like me to open the side gate for the delivery?"
        return None, facts["reply"].strip() or "I'm here. What else can I help with?"

    def signals(self, timezone: str) -> dict[str, Any]:
        now = datetime.now(ZoneInfo(timezone))
        clock = self.simulated_time or now.strftime("%H:%M")
        hour, minute = map(int, clock.split(":"))
        context: dict[str, Any] = {
            "local_time": clock,
            "local_time_minutes": hour * 60 + minute,
            "signal_source": "web_conversation_simulation",
            "time_source": "explicit_demo_time" if self.simulated_time else "home_clock",
        }
        if self.action == "unlockDoor":
            if self.visitor == "delivery":
                context.update(
                    actor="delivery-agent",
                    delivery_expected=self.expected,
                    courier_recognized=self.recognized,
                    # This is the same camera fixture as the original delivery scene,
                    # now explicitly confirmed in dialogue. No camera was observed.
                    recognition_source="camera",
                    recognition_simulated=True,
                    household_confirmation=True,
                )
            else:
                context.update(actor=self.visitor, household_confirmation=True)
        elif self.action == "disarmSystem":
            context.update(
                user="child" if self.speaker == "child" else "resident",
                location="home",
                device_group="security_infrastructure",
                time=clock,
            )
        return context

    def consume_action(self) -> None:
        if self.action == "unlockDoor":
            # A new gate request needs its own visitor facts and confirmation.
            self.visitor = self.expected = self.recognized = None
        self.action = self.awaiting = None

    def public(self) -> dict[str, Any]:
        return {"source": "conversation_simulation", **asdict(self)}
