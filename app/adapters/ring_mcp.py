"""Real MCP server exposing declarative Ring action requests."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server import MCPServer

from app.interception.ports import ActionRequestPort
from app.interception.unavailable import GovernanceUnavailable
from app.models.actions import ActionProposal, RingAction

LOGGER = logging.getLogger(__name__)


class RingMcpServer:
    """Expose Ring actions over MCP without holding a Ring SDK or device port."""

    def __init__(self, action_request: ActionRequestPort | None = None) -> None:
        self._action_request = action_request or GovernanceUnavailable()
        self.server = MCPServer(
            "HomeBound Ring Actions",
            instructions=(
                "These tools submit proposals for governed execution. A tool call is not "
                "authorization. Report the returned decision and execution status exactly."
            ),
        )
        self._register_tools()

    async def _submit(
        self,
        action: RingAction,
        target: str,
        purpose: str,
        parameters: dict[str, Any] | None,
        context_signals: dict[str, Any] | None,
    ) -> dict[str, Any]:
        proposal = ActionProposal(
            action=action,
            target=target,
            purpose=purpose,
            parameters=parameters or {},
            context_signals=context_signals or {},
        )
        LOGGER.info(
            "intent captured action=%s target=%s correlation_id=%s",
            proposal.action,
            proposal.target,
            proposal.correlation_id,
        )
        result = await self._action_request.request(proposal)
        LOGGER.info(
            "action result decision=%s execution=%s correlation_id=%s",
            result.decision,
            result.execution,
            result.correlation_id,
        )
        return result.as_dict()

    def _register_tools(self) -> None:
        @self.server.tool(title="Request Ring door unlock")
        async def unlockDoor(
            target: str,
            purpose: str,
            context_signals: dict[str, Any],
            parameters: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            """Request an unlock for one named Ring-linked door or gate.

            Required context_signals should include available delivery and time signals.
            Signals supplied by an agent are claims until verified by trusted context.
            """

            return await self._submit(
                "unlockDoor", target, purpose, parameters, context_signals
            )

        @self.server.tool(title="Request Ring security disarm")
        async def disarmSystem(
            target: str,
            reason: str,
            context_signals: dict[str, Any],
            parameters: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            """Request that one named Ring security system be disarmed."""

            return await self._submit(
                "disarmSystem", target, reason, parameters, context_signals
            )

        @self.server.tool(title="Request Ring camera stream")
        async def viewStream(
            target: str,
            purpose: str,
            context_signals: dict[str, Any],
            parameters: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            """Request access to a camera stream by its exact device target."""

            return await self._submit("viewStream", target, purpose, parameters, context_signals)

        resume = getattr(self._action_request, "resume", None)
        if callable(resume):

            @self.server.tool(title="Resume managed Decionis approval")
            async def resumeEscalation(correlation_id: str) -> dict[str, Any]:
                """Re-present one saved handoff; AgentSafe rechecks approval and its exact intent."""

                LOGGER.info("managed escalation resume requested correlation_id=%s", correlation_id)
                result = await resume(correlation_id)
                LOGGER.info(
                    "managed escalation result decision=%s execution=%s correlation_id=%s",
                    result.decision,
                    result.execution,
                    result.correlation_id,
                )
                return result.as_dict()
