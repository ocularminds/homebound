"""Construct the configured governance boundary for the MCP server."""

from pathlib import Path

from app.audit.pending_escalations import PendingEscalationStore
from app.config.settings import Settings
from app.interception.agentsafe_http import AgentSafeActionPort
from app.interception.ports import ActionRequestPort
from app.interception.unavailable import GovernanceUnavailable


def action_request_port(settings: Settings) -> ActionRequestPort:
    """Use AgentSafe only when its endpoint and caller credential are both set."""

    if settings.agentsafe_endpoint is None and settings.agentsafe_bearer_token is None:
        return GovernanceUnavailable()
    if settings.agentsafe_endpoint is None or settings.agentsafe_bearer_token is None:
        raise ValueError(
            "HOMEBOUND_AGENTSAFE_URL and HOMEBOUND_AGENTSAFE_BEARER_TOKEN must be set together"
        )
    database = Path(settings.audit_directory) / "pending-escalations.sqlite3"
    return AgentSafeActionPort(
        settings.agentsafe_endpoint,
        settings.agentsafe_bearer_token,
        PendingEscalationStore(database),
    )
