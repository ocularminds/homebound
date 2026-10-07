"""Content screening complements audience policy; it never establishes identity."""

from __future__ import annotations

import asyncio
import re
import hashlib
from typing import Any, Callable

# Deliberately conservative local demo screening, not a replacement for Guardrails.
SENSITIVE = re.compile(
    r"[\w.+-]+@[\w.-]+\.[a-z]{2,}|\b(?:\d[ -]?){7,}\b|"
    r"\b(?:password|passcode|pin code|social security|credit card|bank account|"
    r"diagnos\w*|medication|prescription|medical|confidential|secret)\b",
    re.I,
)


class OverlaySafety:
    def __init__(
        self,
        client_factory: Callable[[], Any] | None = None,
        guardrail_id: str = "",
        version: str = "",
        required: bool = False,
    ) -> None:
        if bool(guardrail_id) != bool(version):
            raise ValueError("Configure both the canvas guardrail ID and version.")
        if guardrail_id and not re.fullmatch(r"[1-9][0-9]*", version):
            raise ValueError("Pin a published, numbered Bedrock Guardrails version.")
        self._factory, self._client = client_factory, None
        self.guardrail_id, self.version, self.required = guardrail_id, version, required

    @property
    def mode(self) -> str:
        if self.guardrail_id:
            return "bedrock_guardrails"
        return "guardrails_required" if self.required else "local_demo_screening"

    @property
    def policy_stamp(self) -> str:
        return hashlib.sha256(
            f"{self.mode}:{self.guardrail_id}:{self.version}".encode()
        ).hexdigest()

    def allows_saved(self, note: dict[str, Any]) -> bool:
        if note["screening"] == "demo_fixture":
            return True
        if self.guardrail_id:
            return (
                note["screening"] == "bedrock_guardrails"
                and note.get("policy_stamp") == self.policy_stamp
            )
        return not self.required and note["screening"] in {
            "local_demo_screening",
            "bedrock_guardrails",
        }

    async def screen(self, text: str, source: str = "OUTPUT") -> str:
        if SENSITIVE.search(text):
            return "held"
        if not self.guardrail_id:
            return "held" if self.required else "local_demo_screening"
        try:
            if self._client is None:
                if self._factory is None:
                    return "held"
                self._client = await asyncio.to_thread(self._factory)
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.apply_guardrail,
                    guardrailIdentifier=self.guardrail_id,
                    guardrailVersion=self.version,
                    source=source,
                    content=[{"text": {"text": text}}],
                    outputScope="INTERVENTIONS",
                ),
                timeout=12,
            )
            # Any intervention, masking, malformed result or outage holds the overlay.
            return "bedrock_guardrails" if result.get("action") == "NONE" else "held"
        except Exception:
            # Deliberately do not log assessments or original household content.
            return "held"
