"""Construct the configured governance boundary for the MCP server."""

from pathlib import Path

from app.audit.action_log import ActionAuditLog
from app.audit.dossier_archive import DossierArchiveClient
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
    if (settings.dossier_archiver_endpoint is None) != (
        settings.dossier_archiver_bearer_token is None
    ):
        raise ValueError(
            "HOMEBOUND_DOSSIER_ARCHIVER_URL and HOMEBOUND_DOSSIER_ARCHIVER_TOKEN must be set together"
        )
    dossier_archiver = (
        DossierArchiveClient(
            settings.dossier_archiver_endpoint,
            settings.dossier_archiver_bearer_token,
        )
        if settings.dossier_archiver_endpoint and settings.dossier_archiver_bearer_token
        else None
    )
    return AgentSafeActionPort(
        settings.agentsafe_endpoint,
        settings.agentsafe_bearer_token,
        PendingEscalationStore(database),
        dossier_archiver=dossier_archiver,
        audit_log=ActionAuditLog(Path(settings.audit_directory) / "actions.jsonl"),
    )
