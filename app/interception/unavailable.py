"""Fail-closed port used until the official AgentSafe service is configured."""

from app.interception.ports import ActionRequestPort
from app.models.actions import ActionProposal, ActionResult


class GovernanceUnavailable(ActionRequestPort):
    """Never executes a tool proposal when AgentSafe is not reachable/configured."""

    async def request(self, proposal: ActionProposal) -> ActionResult:
        return ActionResult(
            decision="BLOCK",
            execution="NOT_PERFORMED",
            message=(
                "AgentSafe/Decionis execution authority is not configured. "
                "No Ring action was executed."
            ),
            correlation_id=proposal.correlation_id,
        )
