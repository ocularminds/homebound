"""Small, closed event and command contracts. Models cannot supply executable UI."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from app.ambient.catalog import INGREDIENTS, PEOPLE, PRODUCTS, SCENES


class CanvasError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class AmbientEvent:
    id: str
    source: str
    kind: str
    sequence: int
    observed_at: float
    data: dict[str, Any]
    home_id: str = "local-home"
    version: int = 1

    def validate(self) -> None:
        try:
            UUID(self.id)
        except (ValueError, TypeError, AttributeError):
            raise CanvasError("INVALID_EVENT", "The event needs a valid identifier.") from None
        if type(self.version) is not int or self.version != 1 or self.home_id != "local-home":
            raise CanvasError("INVALID_EVENT", "This event belongs to a different home or version.")
        sources = {
            "presence": "ring-simulator",
            "media": "firetv-simulator",
            "inventory": "pantry-simulator",
        }
        if (
            not isinstance(self.kind, str)
            or self.kind not in sources
            or self.source != sources[self.kind]
        ):
            raise CanvasError("INVALID_EVENT", "This signal is not from a configured adapter.")
        if type(self.sequence) is not int or not 0 < self.sequence < 2**53:
            raise CanvasError("INVALID_EVENT", "The event needs a positive sequence.")
        if type(self.observed_at) not in {int, float} or not 0 < self.observed_at < 10**11:
            raise CanvasError("INVALID_EVENT", "The event time is invalid.")
        if not isinstance(self.data, dict):
            raise CanvasError("INVALID_EVENT", "The event data is invalid.")
        if self.kind == "presence":
            if set(self.data) != {"people", "guest"}:
                raise CanvasError("INVALID_EVENT", "The audience signal is invalid.")
            people = self.data["people"]
            if (
                not isinstance(people, list)
                or any(not isinstance(p, str) or p not in PEOPLE for p in people)
                or len(people) != len(set(people))
                or type(self.data["guest"]) is not bool
            ):
                raise CanvasError("INVALID_EVENT", "The audience signal is invalid.")
        elif self.kind == "media":
            if (
                set(self.data) != {"scene", "playback_id", "phase"}
                or not isinstance(self.data["scene"], str)
                or self.data["scene"] not in SCENES
                or not isinstance(self.data["phase"], str)
                or self.data["phase"] not in {"program", "break"}
            ):
                raise CanvasError("INVALID_EVENT", "The playback signal is invalid.")
            if not isinstance(self.data["playback_id"], str) or not re.fullmatch(
                r"[a-zA-Z0-9-]{1,64}", self.data["playback_id"]
            ):
                raise CanvasError("INVALID_EVENT", "The playback identifier is invalid.")
        else:
            if (
                set(self.data) != {"available"}
                or not isinstance(self.data["available"], list)
                or any(
                    not isinstance(i, str) or i not in INGREDIENTS for i in self.data["available"]
                )
                or len(self.data["available"]) != len(set(self.data["available"]))
            ):
                raise CanvasError("INVALID_EVENT", "The inventory signal is invalid.")

    def public_envelope(self) -> dict[str, Any]:
        return asdict(self)


COMMANDS = {
    "note",
    "recipes",
    "identify",
    "cart_add",
    "cart_clear",
    "checkout",
    "reading",
    "restore",
    "dashboard",
    "dismiss",
    "none",
}
COMMAND_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": sorted(COMMANDS),
            "description": "Latest requested intent only. Liking an item means identify, not cart_add. note sends a dictated note. reading previews the room while keeping the game on. Never buy anything.",
        },
        "recipient": {"type": "string", "enum": ["mom", "leo", "alex", "household", "unknown"]},
        "text": {
            "type": "string",
            "description": "For a note: exact dictated note body, without adding information. Otherwise empty.",
        },
        "product": {
            "type": "string",
            "enum": [*PRODUCTS, "scene", "missing", "unknown"],
            "description": "Only an item explicitly requested. scene = item from current content; missing = missing recipe ingredients.",
        },
        "reply": {
            "type": "string",
            "description": "Clarifying question only if intent is none. Never claim an action or purchase happened.",
        },
    },
    "required": ["intent", "recipient", "text", "product", "reply"],
}


def validate_command(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(COMMAND_SCHEMA["required"]):
        raise CanvasError(
            "INVALID_PLAN", "I couldn't safely interpret that request. Try saying it another way."
        )
    result = dict(value)
    for name, spec in COMMAND_SCHEMA["properties"].items():
        if not isinstance(result[name], str) or len(result[name]) > (
            500 if name in {"text", "reply"} else 40
        ):
            raise CanvasError("INVALID_PLAN", "The proposed canvas request was invalid.")
        # Normalize Nova's quoted labels, not note content or arbitrary HTML.
        if name not in {"text", "reply"}:
            result[name] = result[name].strip().strip('"')
        if "enum" in spec and result[name] not in spec["enum"]:
            raise CanvasError("INVALID_PLAN", "The proposed canvas request was unsupported.")
    if result["intent"] == "note" and (
        not result["text"].strip() or result["recipient"] == "unknown"
    ):
        raise CanvasError(
            "NOTE_INCOMPLETE", "Who is the note for: Mom, Leo, Alex, or the household?"
        )
    return result


def validate_note_request(command: dict[str, str], message: str) -> None:
    """Bind the extracted note and its audience to this utterance, never model inference."""

    def normalize(text: str) -> str:
        return " ".join(text.lower().split()).strip(" .!?")

    body, utterance = normalize(command["text"]), normalize(message)
    if not body or body not in utterance:
        raise CanvasError("NOTE_CHANGED", "Please dictate the exact note you'd like me to leave.")
    # Names within the note body do not authorize sending the note to those people.
    routing = utterance.replace(body, " ", 1)
    aliases = {
        "mom": "mom",
        "mum": "mom",
        "mother": "mom",
        "leo": "leo",
        "alex": "alex",
        "household": "household",
        "everyone": "household",
        "family": "household",
        "everybody": "household",
    }
    audience = {aliases[word] for word in re.findall(r"\b[a-z]+\b", routing) if word in aliases}
    if audience != {command["recipient"]}:
        raise CanvasError("AUDIENCE_UNCLEAR", "Who is this note for: Mom, Leo, Alex, or everyone?")
