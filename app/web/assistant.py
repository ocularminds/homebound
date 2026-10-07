"""Session-scoped conversation and evidence for the Alexa-style simulator."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from app.config.settings import Settings
from app.ambient.engine import CanvasService
from app.orchestration.bedrock import BedrockOrchestrator
from app.web.conversation import (
    DIALOGUE_SCHEMA,
    FOLLOW_UP,
    DialogueContext,
    validate_interpretation,
)
from app.web.escalations import approval_snapshot, remember_approval
from app.web.scenarios import (
    SCENARIOS,
    TARGETS,
    captured_context,
    home_tool_schemas,
    same_json,
    valid_home_call,
)
from app.web.settings import WebSettings

LOGGER = logging.getLogger("homebound.web")


class WebError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


@dataclass
class Conversation:
    dialogue: DialogueContext = field(default_factory=DialogueContext)
    history: list[dict[str, str]] = field(default_factory=list)
    turns: list[dict[str, Any]] = field(default_factory=list)
    activity: list[dict[str, Any]] = field(default_factory=list)
    pending: dict[str, dict[str, Any]] = field(default_factory=dict)
    replies: OrderedDict[str, tuple[str, dict[str, Any]]] = field(default_factory=OrderedDict)
    device_state: dict[str, Any] | None = None
    touched: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def present_result(raw: Any) -> dict[str, Any] | None:
    """Expose only the MCP evidence fields the UI needs, never transport internals."""
    if not isinstance(raw, dict):
        return None
    result = {
        key: raw[key]
        for key in (
            "decision",
            "execution",
            "correlation_id",
            "decision_id",
            "dossier_id",
            "grant_id",
            "authorization_expires_at",
            "escalation_id",
            "intent_id",
            "intent_hash",
            "authority_outcome",
            "escalation_expires_at",
            "escalation_status",
            "escalation_mode",
        )
        if isinstance(raw.get(key), str) and len(raw[key]) <= 256
    }
    reasons = raw.get("reason_codes")
    if isinstance(reasons, (list, tuple)):
        result["reason_codes"] = [item[:160] for item in reasons[:12] if isinstance(item, str)]
    evidence = raw.get("dossier_evidence")
    if isinstance(evidence, dict):
        result["dossier_evidence"] = {
            "verified": evidence.get("verified") is True,
            "trust_anchor": evidence.get("trust_anchor")
            if evidence.get("trust_anchor") == "DECIONIS_OFFICIAL"
            else None,
        }
    event = raw.get("execution_event")
    if isinstance(event, dict):
        result["execution_event"] = {
            key: event[key]
            for key in ("action", "target", "result", "timestamp")
            if isinstance(event.get(key), str) and len(event[key]) <= 256
        }
        state = event.get("state")
        if isinstance(state, dict):
            safe_state = {}
            for group, target in (
                ("door_locked", "side_gate"),
                ("security_system_armed", "home_security"),
                ("camera_stream_available", "front_door"),
            ):
                group_state = state.get(group)
                if isinstance(group_state, dict) and isinstance(group_state.get(target), bool):
                    safe_state[group] = {target: group_state[target]}
            result["execution_event"]["state"] = safe_state
    return result


def suggested_scene(trace: list[dict[str, Any]], scenario_id: str | None) -> str | None:
    if scenario_id != "everyday":
        return None
    for entry in reversed(trace):
        if entry.get("invoked"):
            result = entry.get("result") or {}
            if (
                entry.get("name") == "unlockDoor"
                and result.get("decision") == "AUTHORITY_UNAVAILABLE"
                and result.get("execution") == "NOT_PERFORMED"
                and "MANAGED_ESCALATION_MISSING" in result.get("reason_codes", [])
            ):
                return "courier"
            return None
    return None


def action_reply(trace: list[dict[str, Any]], fallback: str, scenario_id: str | None = None) -> str:
    """Narrate execution from structured evidence, even if model narration disagrees."""
    invoked = [entry for entry in trace if entry.get("invoked")]
    if not invoked:
        if trace:
            if scenario_id == "conversation":
                return "I couldn't safely match that request to this home. No device action ran. Could you say it another way?"
            return "The request didn't match this home's demo context, so I didn't submit a device action. Try one of the suggested requests."
        return (
            fallback.strip()[:1800]
            or "I can help with the side gate, home security, and front door camera. What would you like to do?"
        )
    result = invoked[-1].get("result") or {}
    decision, execution = result.get("decision"), result.get("execution")
    if decision == "ALLOW" and execution == "PERFORMED":
        event = result.get("execution_event") or {}
        return {
            "unlockDoor": "The simulated side gate is now unlocked.",
            "disarmSystem": "The simulated home security system is now disarmed.",
            "viewStream": "Access to the simulated front door camera was granted. There is no physical video feed in this demo.",
        }.get(event.get("action"), "The authorized action completed in the home simulator.")
    if decision == "ESCALATE" and execution == "NOT_PERFORMED":
        if result.get("escalation_status") in {"PRESENCE_VERIFIED", "REAUTHORIZING"}:
            return "Approval is verified. I'm waiting for the final authorization."
        if result.get("escalation_status") == "PENDING_PRESENCE":
            return "The household approval request is being prepared."
        claims = invoked[-1].get("arguments", {}).get("context_signals", {})
        if claims.get("user") == "child":
            return "Your parent needs to approve that first."
        return "I'm waiting for household approval."
    if decision == "BLOCK" and execution == "NOT_PERFORMED":
        reasons = set(result.get("reason_codes", []))
        if reasons & {"INTENT_EXPIRED", "EXPIRED"} or result.get("escalation_status") == "EXPIRED":
            return "The approval window expired. No device action ran. You can make a new request when you're ready."
        if reasons & {"REJECTED", "CANCELLED"} or result.get("escalation_status") in {"REJECTED", "CANCELLED"}:
            return "The approval was declined or cancelled. No device action ran."
        return "That request was blocked by the home's authorization rules. No device action was performed."
    if decision == "ALLOW" and execution == "NOT_PERFORMED":
        return "Authorization was granted, but the device action was not completed. Check the action record before trying again."
    if decision == "AUTHORITY_UNAVAILABLE" and execution == "NOT_PERFORMED":
        if suggested_scene(trace, scenario_id) == "courier":
            return (
                "Everyday at home has no resident or delivery identity, and an approval handoff "
                "isn't available for this request. Choose An expected delivery to try the gate "
                "with simulated delivery context, then ask again. No device action ran."
            )
        if "MANAGED_ESCALATION_MISSING" in result.get("reason_codes", []):
            return (
                "This request needs approval, but the approval service did not create a handoff. "
                "No device action ran."
            )
        return "Authorization is unavailable, so the request could not be completed. Check the action record for details."
    return "I couldn't confirm the result of that request. Check the action record before trying again; it may already have reached the executor."


class WebAssistant:
    def __init__(
        self,
        settings: Settings,
        web_settings: WebSettings,
        agent_factory: Callable[[], BedrockOrchestrator],
        resume_call: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
        canvas: CanvasService | None = None,
    ) -> None:
        self.settings, self.web_settings = settings, web_settings
        self._agent_factory = agent_factory
        self._agent: BedrockOrchestrator | None = None
        self._agent_lock = asyncio.Lock()
        self._resume_call = resume_call or self._resume_mcp
        self.canvas = canvas

    async def _get_agent(self) -> BedrockOrchestrator:
        if not self.settings.bedrock_model_id:
            raise WebError(
                "ASSISTANT_NOT_CONFIGURED",
                "Configure the Bedrock model and start the HomeBound MCP service to send requests.",
                503,
            )
        async with self._agent_lock:
            if self._agent is None:
                self._agent = await asyncio.to_thread(self._agent_factory)
        return self._agent

    @staticmethod
    def _cached(session: Conversation, request_id: str, fingerprint: str) -> dict[str, Any] | None:
        cached = session.replies.get(request_id)
        if cached is not None:
            if cached[0] != fingerprint:
                raise WebError(
                    "REQUEST_ID_REUSED",
                    "This request identifier was already used with different content.",
                    409,
                )
            return cached[1]
        if session.lock.locked():
            raise WebError("REQUEST_IN_PROGRESS", "Wait for the current request to finish.", 409)
        return None

    async def chat(
        self, session: Conversation, request_id: str, message: str, scenario_id: str
    ) -> dict[str, Any]:
        fingerprint = json.dumps(["chat", message, scenario_id])
        cached = self._cached(session, request_id, fingerprint)
        if cached is not None:
            return cached
        async with session.lock:
            if scenario_id == "canvas":
                return await self._converse_canvas(session, request_id, fingerprint, message)
            if scenario_id == "conversation" and message.lower().strip(" .?!") in {
                "check approval", "alexa, check approval", "alexa check approval",
                "check the approval", "check approval status",
            }:
                return await self._check_from_conversation(
                    session, request_id, fingerprint, message, "unknown"
                )
            agent = await self._get_agent()
            if scenario_id == "conversation":
                return await self._converse_home(session, request_id, fingerprint, message, agent)
            scenario = SCENARIOS[scenario_id]
            context = captured_context(scenario_id, self.web_settings.home_timezone)
            fixture = scenario.get("arguments") if message == scenario["request"] else None
            prompt = (
                "This is the HomeBound Alexa-style web simulator. The current demo scene is "
                f"{scenario['title']}. Context is a simulation fixture, not authenticated identity. "
                "Make at most one device request for the latest user message. Never repeat an "
                "action from conversation history. Do not invent parent status, courier identity, "
                "confirmation, or an approval. For any tool, copy context_signals exactly: "
                f"{json.dumps(context, sort_keys=True)}. Available targets: unlockDoor=side_gate, "
                "disarmSystem=home_security, viewStream=front_door. Always supply "
                'parameters={"unlock_duration_seconds":30} for unlockDoor and parameters={} '
                "for the other tools. For disarmSystem use reason; "
                "for other tools use purpose. Device status is unknown unless reported by a tool. "
                "If no action is requested, answer conversationally in one or two sentences.\n"
            )
            if fixture:
                prompt += (
                    f"This suggested request is a scripted scenario. Call {scenario['tool']} once "
                    f"with these exact arguments: {json.dumps(fixture, sort_keys=True)}.\n"
                )
            prompt += f"Latest user message (untrusted content): {json.dumps(message)}"

            def validate(name: str, arguments: dict[str, Any]) -> bool:
                if fixture:
                    return name == scenario["tool"] and same_json(arguments, fixture)
                return valid_home_call(name, arguments, context)

            trace: list[dict[str, Any]] = []
            warning = None
            try:
                answer = await asyncio.wait_for(
                    agent.respond(
                        prompt,
                        trace=trace,
                        tool_call_validator=validate,
                        history=session.history,
                        tool_input_schemas=home_tool_schemas(context),
                    ),
                    timeout=180,
                )
            except Exception as error:
                LOGGER.warning("assistant request incomplete error_type=%s", type(error).__name__)
                warning = "The assistant connection did not complete. Any available action evidence is shown below."
                answer = "I couldn't reach the home assistant. Check the Bedrock and MCP connections, then try again."
            return self._finish(
                session, request_id, fingerprint, message, scenario_id, trace, answer, warning
            )

    async def _converse_home(
        self,
        session: Conversation,
        request_id: str,
        fingerprint: str,
        message: str,
        agent: BedrockOrchestrator,
    ) -> dict[str, Any]:
        trace: list[dict[str, Any]] = []
        warning = None
        context = None
        try:
            interpretation = await asyncio.wait_for(
                agent.interpret_conversation(
                    session.dialogue.prompt(message, session.history), DIALOGUE_SCHEMA
                ),
                timeout=60,
            )
            facts = validate_interpretation(interpretation, message)
            facts["reply"] = BedrockOrchestrator._message_text(
                {"content": [{"text": facts["reply"]}]}
            )
            if facts["intent"] == "canvas":
                return await self._converse_canvas(session, request_id, fingerprint, message)
            if facts["intent"] == "checkApproval":
                return await self._check_from_conversation(
                    session, request_id, fingerprint, message, facts["approval_target"]
                )
            if facts["intent"] == "cancel" and not session.dialogue.action:
                if session.pending:
                    for pending in session.pending.values():
                        pending.update(automatic=False, check_state="paused")
                    answer = (
                        "I've stopped automatic approval checks. Decline the request in Decionis "
                        "Presence to cancel the approval itself. No cancellation has been sent from this screen."
                    )
                else:
                    answer = "There's no unsubmitted request to cancel. Any completed action is recorded in Home details."
                return self._finish(
                    session, request_id, fingerprint, message, "conversation", [],
                    answer, None,
                )
            action, answer = session.dialogue.advance(facts)
            if action:
                if any(item.get("target") == TARGETS[action] for item in session.pending.values()):
                    session.dialogue.consume_action()
                    return self._finish(
                        session, request_id, fingerprint, message, "conversation", [],
                        "There's already an approval request for that device. Say 'check approval' "
                        "to check the saved request, or decline it in Decionis Presence first.",
                        None,
                    )
                context = session.dialogue.signals(self.web_settings.home_timezone)
                purpose_key = "reason" if action == "disarmSystem" else "purpose"
                arguments = {
                    "target": TARGETS[action],
                    purpose_key: {
                        "unlockDoor": "conversational request to open the side gate",
                        "disarmSystem": "conversational request to disable the home alarm",
                        "viewStream": "conversational request to view the front door camera",
                    }[action],
                    "context_signals": context,
                    "parameters": {"unlock_duration_seconds": 30} if action == "unlockDoor" else {},
                }
                # Consume before dispatch: even a lost result cannot turn the next
                # utterance or a bare yes into a replay of this action.
                session.dialogue.consume_action()
                answer = await asyncio.wait_for(
                    agent.respond(
                        "The user's current conversational request is ready. The server has "
                        "captured its simulation claims and any required clarification. Request "
                        f"{action} exactly once with {json.dumps(arguments, sort_keys=True)}. "
                        "These are demo claims, not authenticated identity or a real camera "
                        "observation. Do not add or alter context. Describe only the returned "
                        "execution result, briefly. Never repeat a historical action.",
                        trace=trace,
                        tool_call_validator=lambda name, values: (
                            name == action and same_json(values, arguments)
                        ),
                        history=[],
                        tool_input_schemas=home_tool_schemas(context),
                    ),
                    timeout=180,
                )
                if not any(entry.get("invoked") for entry in trace):
                    answer = "I couldn't submit that device request. No device action ran."
        except ValueError:
            LOGGER.warning("conversation context could not be interpreted")
            answer = "I didn't catch that detail. Could you say it another way?"
        except Exception as error:
            LOGGER.warning("conversation incomplete error_type=%s", type(error).__name__)
            answer = "I couldn't complete that request. Please check the home connection before trying again."
            warning = "Any returned action evidence is retained below."
        return self._finish(
            session,
            request_id,
            fingerprint,
            message,
            "conversation",
            trace,
            answer,
            warning,
            captured_signals=context,
        )

    async def _converse_canvas(
        self, session: Conversation, request_id: str, fingerprint: str, message: str,
    ) -> dict[str, Any]:
        if self.canvas is None:
            raise WebError("CANVAS_UNAVAILABLE", "The TV canvas is not configured.", 503)
        # Switching topics must not leave a bare yes able to submit an old device action.
        # Saved authority handoffs remain intact and can still be checked explicitly.
        session.dialogue.consume_action()
        answer = await self.canvas.converse(request_id, message)
        return self._finish(
            session, request_id, fingerprint, message, "conversation", [], answer, None,
        )

    async def _check_from_conversation(
        self, session: Conversation, request_id: str, fingerprint: str, message: str, target: str
    ) -> dict[str, Any]:
        matches = [
            key for key, pending in session.pending.items()
            if target == "unknown" or pending.get("target") == target
        ]
        if len(matches) == 1:
            return await self._resume_saved(
                session, request_id, fingerprint, matches[0], message=message
            )
        answer = (
            "There isn't a saved approval request to check. No approval has been assumed."
            if not matches else
            "Which approval should I check: the side gate, home security, or the camera? "
            "You can also use the Check approval button for that request."
        )
        return self._finish(
            session, request_id, fingerprint, message, "conversation", [], answer, None
        )

    async def resume(
        self, session: Conversation, request_id: str, correlation_id: str, *, automatic: bool = False
    ) -> dict[str, Any]:
        fingerprint = json.dumps(["resume", correlation_id, automatic])
        cached = self._cached(session, request_id, fingerprint)
        if cached is not None:
            return cached
        async with session.lock:
            return await self._resume_saved(
                session, request_id, fingerprint, correlation_id, automatic=automatic
            )

    async def _resume_saved(
        self, session: Conversation, request_id: str, fingerprint: str, correlation_id: str,
        *, message: str = "Check approval", automatic: bool = False,
    ) -> dict[str, Any]:
        original = session.pending.get(correlation_id)
        if original is None:
            raise WebError(
                "ESCALATION_NOT_FOUND", "This conversation has no pending request with that identifier.", 404
            )
        if original.get("check_state") == "uncertain":
            return self._finish(
                session, request_id, fingerprint, message, original["scenario_id"], [],
                "The last approval check lost its execution result. Review the action record "
                "before making another request; the device may already have run.", None,
            )
        if automatic and (
            not original.get("automatic") or time.monotonic() < original.get("next_check_at", 0)
        ):
            raise WebError("APPROVAL_CHECK_NOT_DUE", "This approval isn't due for an automatic check.", 409)
        trace: list[dict[str, Any]] = [{
            "name": "resumeEscalation", "arguments": {"correlation_id": correlation_id}, "invoked": True,
        }]
        warning = None
        try:
            result = await asyncio.wait_for(self._resume_call(correlation_id), timeout=180)
            if result.get("correlation_id") != correlation_id:
                raise ValueError("Escalation correlation mismatch")
            decision, execution = result.get("decision"), result.get("execution")
            if (
                decision not in {"ALLOW", "BLOCK", "ESCALATE", "AUTHORITY_UNAVAILABLE"}
                or execution not in {"PERFORMED", "NOT_PERFORMED", "UNKNOWN"}
                or (decision in {"BLOCK", "ESCALATE"} and execution != "NOT_PERFORMED")
                or (decision == "AUTHORITY_UNAVAILABLE" and execution == "PERFORMED")
            ):
                raise ValueError("Invalid escalation result")
            trace[0]["result"] = result
            if result.get("decision") in {"ALLOW", "BLOCK"}:
                session.pending.pop(correlation_id, None)
            elif result.get("decision") == "AUTHORITY_UNAVAILABLE":
                original.update(
                    automatic=False,
                    check_state="uncertain" if result.get("execution") == "UNKNOWN" else "unavailable",
                )
            elif result.get("decision") == "ESCALATE" and not automatic:
                original["automatic"] = True
        except Exception as error:
            LOGGER.warning("approval check incomplete error_type=%s", type(error).__name__)
            original.update(automatic=False, check_state="uncertain")
            warning = "The approval check could not be confirmed. Automatic checks stopped; review the action record."
        return self._finish(
            session, request_id, fingerprint, "Approval update" if automatic else message,
            original["scenario_id"], trace, "", warning, background=automatic,
        )

    def _finish(
        self,
        session: Conversation,
        request_id: str,
        fingerprint: str,
        message: str,
        scenario_id: str,
        trace: list[dict[str, Any]],
        answer: str,
        warning: str | None,
        *,
        captured_signals: dict[str, Any] | None = None,
        background: bool = False,
    ) -> dict[str, Any]:
        safe_trace = []
        for entry in trace:
            safe = {
                "name": entry.get("name"),
                "invoked": entry.get("invoked") is True,
                "arguments": entry.get("arguments", {}),
                "result": present_result(entry.get("result")),
            }
            if entry.get("reason"):
                safe["reason"] = entry["reason"]
            result = safe["result"] or {}
            correlation = result.get("correlation_id")
            if (
                result.get("decision") == "ESCALATE"
                and result.get("execution") == "NOT_PERFORMED"
                and correlation
            ):
                remember_approval(session.pending, safe, scenario_id)
            event = result.get("execution_event") or {}
            if (
                result.get("decision") == "ALLOW"
                and result.get("execution") == "PERFORMED"
                and isinstance(event.get("state"), dict)
            ):
                session.device_state = {
                    "state": event["state"],
                    "timestamp": event.get("timestamp"),
                }
            safe_trace.append(safe)
        reply = action_reply(safe_trace, answer, scenario_id)
        follow_up = (
            FOLLOW_UP if scenario_id == "conversation" and not reply.rstrip().endswith("?") else ""
        )
        turn = {
            "id": request_id,
            "message": message,
            "reply": reply,
            "scenario_id": scenario_id,
            "trace": safe_trace,
            "device_state": session.device_state,
            "warning": warning,
            "suggested_scene": suggested_scene(safe_trace, scenario_id),
            "dialogue": session.dialogue.public(),
            "captured_context": captured_signals,
            "follow_up": follow_up,
            "speech_text": f"{reply[:1650]} {follow_up}".strip(),
            "approvals": approval_snapshot(session.pending),
            "background": background,
            "notify": not background or not safe_trace or any(
                (entry.get("result") or {}).get("decision") != "ESCALATE" for entry in safe_trace
            ),
        }
        if turn["notify"]:
            session.history.extend(
                [{"role": "user", "text": message}, {"role": "assistant", "text": reply}]
            )
            session.history[:] = session.history[-12:]
            session.turns.append(turn)
            session.turns[:] = session.turns[-12:]
        if safe_trace and turn["notify"]:
            session.activity.append(turn)
            session.activity[:] = session.activity[-32:]
        session.replies[request_id] = (fingerprint, turn)
        while len(session.replies) > 32:
            session.replies.popitem(last=False)
        # These are references to durable MCP handoffs; bound local UI memory as well.
        while len(session.pending) > 32:
            session.pending.pop(next(iter(session.pending)))
        session.touched = time.monotonic()
        return turn

    async def _resume_mcp(self, correlation_id: str) -> dict[str, Any]:
        async with AsyncExitStack() as stack:
            headers = (
                {"Authorization": f"Bearer {self.settings.mcp_bearer_token}"}
                if self.settings.mcp_bearer_token
                else {}
            )
            http_client = await stack.enter_async_context(
                httpx2.AsyncClient(
                    headers=headers,
                    timeout=httpx2.Timeout(15, read=160),
                )
            )
            transport = streamable_http_client(self.settings.mcp_endpoint, http_client=http_client)
            client = await stack.enter_async_context(Client(transport))
            result = await client.call_tool("resumeEscalation", {"correlation_id": correlation_id})
            if not isinstance(result.structured_content, dict):
                raise ValueError("MCP returned no structured approval result")
            return result.structured_content
