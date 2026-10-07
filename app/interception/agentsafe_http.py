"""HTTP client for the official AgentSafe trusted-executor process."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from weakref import WeakValueDictionary

import httpx2

from app.audit.action_log import ActionAuditLog
from app.audit.dossier_archive import DossierArchiveClient
from app.audit.pending_escalations import PendingEscalationStore
from app.interception.ports import ActionRequestPort
from app.models.actions import ActionProposal, ActionResult
from app.models.policy import HomePolicyBinding

LOGGER = logging.getLogger(__name__)
JsonSender = Callable[[str, dict[str, Any]], Awaitable[tuple[int, dict[str, Any]]]]
DECIONIS_ACTIONS = {
    "unlockDoor": "home.entry.unlock",
    "disarmSystem": "home.security.disarm",
    "viewStream": "home.camera.view_stream",
}


class AgentSafeActionPort(ActionRequestPort):
    """Submit proposals and resume managed approvals through AgentSafe HTTP."""

    def __init__(
        self,
        endpoint: str,
        bearer_token: str,
        pending_escalations: PendingEscalationStore,
        *,
        dossier_archiver: DossierArchiveClient | None = None,
        audit_log: ActionAuditLog | None = None,
        sender: JsonSender | None = None,
        transport_factory: Callable[[], httpx2.AsyncBaseTransport] | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        parsed = urlsplit(endpoint)
        loopback_http = parsed.scheme == "http" and parsed.hostname in {
            "127.0.0.1",
            "localhost",
            "::1",
        }
        if parsed.scheme != "https" and not loopback_http:
            raise ValueError("AgentSafe URL must use HTTPS except for loopback development")
        if not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("AgentSafe URL must be an absolute origin without query or fragment")
        if not bearer_token.strip():
            raise ValueError("AgentSafe caller token is required")
        self._endpoint = endpoint.rstrip("/")
        self._bearer_token = bearer_token
        self._pending = pending_escalations
        self._dossier_archiver = dossier_archiver
        self._audit_log = audit_log
        self._sender = sender
        self._transport_factory = transport_factory
        self._timeout_seconds = timeout_seconds
        self._resume_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    async def request(self, proposal: ActionProposal) -> ActionResult:
        """Ask AgentSafe to capture, govern and, only on authority, dispatch."""

        payload = {
            "proposal": {
                # The official Execution Intent action-name contract is lowercase.
                # MCP keeps its public consumer-facing camelCase tool names.
                "action": DECIONIS_ACTIONS[proposal.action],
                "target": proposal.target,
                "parameters": {
                    "homebound_purpose": proposal.purpose,
                    "context_signals": proposal.context_signals,
                    "device_parameters": proposal.parameters,
                    **(
                        {"homebound_policy_binding": proposal.home_policy_binding.as_dict()}
                        if proposal.home_policy_binding is not None
                        else {}
                    ),
                },
            },
            "idempotency_key": proposal.idempotency_key,
            "correlation_id": proposal.correlation_id,
        }
        status, body = await self._post("/v1/actions", payload)
        if not 200 <= status < 300:
            return await self._finish(
                proposal, self._http_refusal(status, body, proposal.correlation_id)
            )

        result = self._map_response(body, proposal.correlation_id)
        if result.decision == "ESCALATE":
            handoff = body.get("escalation")
            if not isinstance(handoff, dict):
                return await self._finish(
                    proposal,
                    self._unavailable(
                        proposal.correlation_id,
                        "AgentSafe returned an escalation without a resumable handoff.",
                        "ESCALATION_HANDOFF_MISSING",
                    ),
                )
            try:
                await asyncio.to_thread(
                    self._pending.save,
                    proposal.correlation_id,
                    proposal.as_dict(),
                    handoff,
                )
            except (OSError, ValueError, sqlite3.Error) as error:
                LOGGER.error(
                    "pending escalation could not be persisted correlation_id=%s error_type=%s",
                    proposal.correlation_id,
                    type(error).__name__,
                )
                return await self._finish(
                    proposal,
                    self._unavailable(
                        proposal.correlation_id,
                        "Decionis opened an approval request, but HomeBound could not save its resume state.",
                        "ESCALATION_HANDOFF_NOT_PERSISTED",
                    ),
                )
        return await self._finish(proposal, result)

    async def resume(self, correlation_id: str) -> ActionResult:
        """Present the saved handoff unchanged; AgentSafe rechecks the intent."""

        # The web listener and a manual MCP client can check the same handoff.
        # Serialize those checks so an older response cannot overwrite a new one.
        lock = self._resume_locks.setdefault(correlation_id, asyncio.Lock())
        async with lock:
            return await self._resume_saved(correlation_id)

    async def _resume_saved(self, correlation_id: str) -> ActionResult:
        pending = await asyncio.to_thread(self._pending.get, correlation_id)
        if pending is None:
            return self._unavailable(
                correlation_id,
                "No pending managed escalation was found for that correlation ID.",
                "ESCALATION_NOT_FOUND",
            )
        status, body = await self._post("/v1/escalations", pending.handoff)
        proposal = _proposal_from_dict(pending.proposal)
        if status == 409 and body.get("code") == "INTENT_EXPIRED":
            await asyncio.to_thread(self._pending.close, correlation_id, "EXPIRED")
            result = ActionResult(
                decision="BLOCK",
                execution="NOT_PERFORMED",
                message="The approval window expired. No Ring action was executed.",
                correlation_id=correlation_id,
                authority_outcome="INTENT_EXPIRED",
                reason_codes=("INTENT_EXPIRED",),
            )
            return await self._finish(proposal, _with_handoff(result, pending.handoff))
        if not 200 <= status < 300:
            return await self._finish(
                proposal,
                _with_handoff(self._http_refusal(status, body, correlation_id), pending.handoff),
            )

        result = _with_handoff(self._map_response(body, correlation_id), pending.handoff)
        if result.decision == "ESCALATE":
            next_handoff = body.get("escalation")
            if not isinstance(next_handoff, dict):
                return await self._finish(
                    proposal,
                    _with_handoff(
                        self._unavailable(
                            correlation_id,
                            "AgentSafe returned a pending decision without the updated handoff.",
                            "ESCALATION_HANDOFF_MISSING",
                        ),
                        pending.handoff,
                    ),
                )
            await asyncio.to_thread(
                self._pending.update_handoff, correlation_id, next_handoff
            )
        elif result.decision in {"ALLOW", "BLOCK"}:
            terminal = "RESOLVED" if result.decision == "ALLOW" else "DENIED"
            await asyncio.to_thread(self._pending.close, correlation_id, terminal)
        # An authority outage is not a denial. Retain the original handoff so
        # the same intent can be checked after the connection is healthy.
        return await self._finish(proposal, result)

    async def _finish(self, proposal: ActionProposal, result: ActionResult) -> ActionResult:
        """Archive proof for any returned dossier and append its local action record."""

        evidence = result.dossier_evidence
        event_evidence = (
            result.execution_event.get("dossier_evidence")
            if result.execution_event is not None
            else None
        )
        if isinstance(event_evidence, dict) and event_evidence.get("verified") is True:
            evidence = event_evidence
        elif result.dossier_id and self._dossier_archiver is not None:
            try:
                evidence = await asyncio.to_thread(
                    self._dossier_archiver.archive,
                    result.dossier_id,
                    result.correlation_id,
                )
            except Exception as error:
                LOGGER.warning(
                    "Decision Dossier archive unavailable dossier_id=%s error_type=%s",
                    result.dossier_id,
                    type(error).__name__,
                )
                evidence = {
                    "dossier_id": result.dossier_id,
                    "correlation_id": result.correlation_id,
                    "verified": False,
                    "error_code": "DOSSIER_ARCHIVE_UNAVAILABLE",
                }
        result = replace(result, dossier_evidence=evidence)

        if self._audit_log is not None:
            try:
                await asyncio.to_thread(self._audit_log.append, proposal, result, evidence)
                result = replace(result, audit_recorded=True)
            except (OSError, ValueError, TypeError, sqlite3.Error) as error:
                LOGGER.error(
                    "action audit record could not be persisted correlation_id=%s error_type=%s",
                    proposal.correlation_id,
                    type(error).__name__,
                )
                result = replace(result, audit_recorded=False)
        return result

    async def _post(self, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if self._sender is not None:
            return await self._sender(path, payload)
        try:
            transport = self._transport_factory() if self._transport_factory else None
            async with httpx2.AsyncClient(
                timeout=self._timeout_seconds, transport=transport
            ) as client:
                response = await client.post(
                    f"{self._endpoint}{path}",
                    headers={"Authorization": f"Bearer {self._bearer_token}"},
                    json=payload,
                )
            body = response.json()
            return response.status_code, body if isinstance(body, dict) else {}
        except (httpx2.HTTPError, ValueError, OSError) as error:
            LOGGER.warning(
                "AgentSafe request unavailable path=%s error_type=%s",
                path,
                type(error).__name__,
            )
            return 503, {"code": "AGENTSAFE_UNREACHABLE"}

    @classmethod
    def _http_refusal(
        cls, status: int, body: dict[str, Any], correlation_id: str
    ) -> ActionResult:
        code = body.get("code")
        if status == 409 and code == "INTENT_EXPIRED":
            return ActionResult(
                decision="BLOCK",
                execution="NOT_PERFORMED",
                message="AgentSafe refused the expired escalation. No action ran.",
                correlation_id=correlation_id,
                authority_outcome=str(code),
                reason_codes=(str(code),),
            )
        safe_code = ""
        if (
            isinstance(code, str)
            and code
            and code[0].isalpha()
            and code.isascii()
            and code == code.upper()
            and code.replace("_", "").isalnum()
        ):
            safe_code = f"_{code}"
        result = cls._unavailable(
            correlation_id,
            "AgentSafe or Decionis did not return an enforceable decision. No Ring action ran.",
            f"AGENTSAFE_HTTP_{status}{safe_code}",
        )
        if code == "AGENTSAFE_UNREACHABLE":
            return replace(
                result,
                execution="UNKNOWN",
                message="The executor response was lost. Check the action record before trying again.",
            )
        return result

    @staticmethod
    def _map_response(body: dict[str, Any], correlation_id: str) -> ActionResult:
        verdict = body.get("verdict")
        mode = body.get("mode")
        outcome = body.get("outcome")
        decision_id = _optional_string(body.get("decision_id"))
        dossier_id = _optional_string(body.get("dossier_id"))
        reason_codes = tuple(
            item for item in body.get("reason_codes", []) if isinstance(item, str)
        ) if isinstance(body.get("reason_codes"), list) else ()
        authorization = body.get("authorization")
        authorization = authorization if isinstance(authorization, dict) else {}
        escalation = body.get("escalation")
        common = {
            "correlation_id": correlation_id,
            "decision_id": decision_id,
            "dossier_id": dossier_id,
            "grant_id": _optional_string(authorization.get("grant_id")),
            "authorization_expires_at": _optional_string(authorization.get("expires_at")),
            "intent_id": _optional_string(body.get("intent_id")),
            "intent_hash": _optional_string(body.get("intent_hash")),
            "authority_outcome": _optional_string(outcome),
            "reason_codes": reason_codes,
            **_escalation_fields(escalation),
            "execution_event": _optional_dict(body.get("result")),
        }

        if mode != "ENFORCEMENT" or body.get("fail_closed") is True or verdict is None:
            return ActionResult(
                decision="AUTHORITY_UNAVAILABLE",
                execution="NOT_PERFORMED",
                message="No enforcement decision was available. No Ring action ran.",
                **common,
            )
        if verdict == "BLOCK":
            reason = reason_codes[0] if reason_codes else "Decionis policy blocked the request."
            return ActionResult(
                decision="BLOCK",
                execution="NOT_PERFORMED",
                message=f"Decionis blocked the request: {reason}. No Ring action ran.",
                **common,
            )
        if verdict == "ESCALATE":
            return ActionResult(
                decision="ESCALATE",
                execution="NOT_PERFORMED",
                message=(
                    "Decionis is waiting for managed Presence approval. "
                    "No Ring action ran."
                ),
                **common,
            )
        if verdict == "ALLOW":
            executed = body.get("executed") is True and outcome == "COMPLETED"
            unknown = outcome == "UNKNOWN_AFTER_DISPATCH"
            message = (
                "The executor could not confirm the device result. Do not repeat the action."
                if unknown
                else "AgentSafe executed the authorized action."
                if executed
                else "Decionis allowed the action, but AgentSafe did not complete execution."
            )
            return ActionResult(
                decision="ALLOW",
                execution="UNKNOWN" if unknown else "PERFORMED" if executed else "NOT_PERFORMED",
                message=message,
                **common,
            )
        return ActionResult(
            decision="AUTHORITY_UNAVAILABLE",
            execution="NOT_PERFORMED",
            message="AgentSafe returned an unknown outcome. No Ring action ran.",
            **common,
        )

    @staticmethod
    def _unavailable(
        correlation_id: str, message: str, reason_code: str
    ) -> ActionResult:
        return ActionResult(
            decision="AUTHORITY_UNAVAILABLE",
            execution="NOT_PERFORMED",
            message=message,
            correlation_id=correlation_id,
            authority_outcome="AUTHORITY_UNAVAILABLE",
            reason_codes=(reason_code,),
        )


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _optional_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _proposal_from_dict(value: dict[str, Any]) -> ActionProposal:
    return ActionProposal(
        action=value["action"],
        target=value["target"],
        purpose=value["purpose"],
        parameters=value.get("parameters", {}),
        context_signals=value.get("context_signals", {}),
        home_policy_binding=(
            HomePolicyBinding(**value["home_policy_binding"])
            if isinstance(value.get("home_policy_binding"), dict)
            else None
        ),
        correlation_id=value["correlation_id"],
        idempotency_key=value["idempotency_key"],
        captured_at=value["captured_at"],
    )


def _escalation_fields(value: Any) -> dict[str, str | None]:
    if not isinstance(value, dict):
        return {}
    managed = value.get("escalation")
    if isinstance(managed, dict):
        intent = value.get("intent") if isinstance(value.get("intent"), dict) else {}
        expires = [managed.get("expiresAt"), intent.get("expiresAt")]
        valid = []
        for date in expires:
            try:
                parsed = datetime.fromisoformat(date.replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    valid.append((parsed.timestamp(), date))
            except (ValueError, TypeError, AttributeError):
                pass
        return {
            "escalation_id": _optional_string(managed.get("escalationId")),
            "escalation_expires_at": min(valid)[1] if valid else None,
            "escalation_status": _optional_string(managed.get("status")),
            "escalation_mode": "MANAGED" if value.get("mode") == "MANAGED" else None,
        }
    return {
        "escalation_id": _optional_string(value.get("request_id")),
        "escalation_expires_at": _optional_string(value.get("expires_at")),
        "escalation_mode": "DIRECT" if value.get("mode") == "DIRECT" else None,
    }


def _with_handoff(result: ActionResult, handoff: dict[str, Any]) -> ActionResult:
    fields = {
        key: value for key, value in _escalation_fields(handoff).items()
        if getattr(result, key) is None
    }
    terminal_status = next(
        (code for code in result.reason_codes if code in {"EXPIRED", "REJECTED", "CANCELLED", "BLOCKED"}),
        None,
    )
    if "INTENT_EXPIRED" in result.reason_codes:
        terminal_status = "EXPIRED"
    if terminal_status:
        fields["escalation_status"] = terminal_status
    elif result.decision == "ALLOW":
        fields["escalation_status"] = "GRANT_READY"
    elif result.decision == "BLOCK":
        fields["escalation_status"] = "BLOCKED"
    return replace(result, **fields)
