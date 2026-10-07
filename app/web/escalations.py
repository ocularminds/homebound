"""Public approval state, derived only from saved, session-owned MCP handoffs."""

from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any

PENDING_STATUSES = {
    "PENDING_PRESENCE", "PRESENCE_REQUESTED", "AWAITING_APPROVER",
    "PRESENCE_VERIFIED", "REAUTHORIZING",
}
STATUS_LABELS = {
    "PENDING_PRESENCE": "Preparing approval",
    "PRESENCE_REQUESTED": "Approval requested",
    "AWAITING_APPROVER": "Waiting for approval",
    "PRESENCE_VERIFIED": "Approval verified; checking authorization",
    "REAUTHORIZING": "Checking authorization",
}
ACTION_LABELS = {
    "unlockDoor": "Open the side gate",
    "disarmSystem": "Disable home security",
    "viewStream": "View the front door camera",
}


def remaining_seconds(expires_at: Any) -> float | None:
    if not isinstance(expires_at, str):
        return None
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            return None
        return (expiry - datetime.now(timezone.utc)).total_seconds()
    except ValueError:
        return None


def remember_approval(
    pending: dict[str, dict[str, Any]], entry: dict[str, Any], scenario_id: str
) -> None:
    result = entry["result"]
    correlation = result["correlation_id"]
    record = pending.setdefault(correlation, {
        "scenario_id": scenario_id,
        "action": entry["name"],
        "target": entry.get("arguments", {}).get("target"),
        "label": ACTION_LABELS.get(entry["name"], "Home request"),
        "automatic": True,
    })
    record.update({
        "correlation_id": correlation,
        "escalation_id": result.get("escalation_id") or record.get("escalation_id"),
        "status": result.get("escalation_status") or record.get("status"),
        "expires_at": result.get("escalation_expires_at") or record.get("expires_at"),
        "check_state": "waiting",
    })
    remaining = remaining_seconds(record["expires_at"])
    record["automatic"] = bool(
        record["automatic"] and record["escalation_id"]
        and record["status"] in PENDING_STATUSES and remaining is not None and remaining > 0
    )
    record["next_check_at"] = time.monotonic() + min(5, max(0.1, remaining or 5))


def approval_snapshot(pending: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    approvals = []
    for correlation, record in pending.items():
        remaining = remaining_seconds(record.get("expires_at"))
        check_state = record.get("check_state", "waiting")
        status_label = {
            "unavailable": "Approval check unavailable",
            "uncertain": "Result needs review",
            "paused": "Automatic checks paused",
        }.get(check_state, STATUS_LABELS.get(record.get("status"), "Waiting for approval"))
        if remaining is not None and remaining <= 0 and check_state == "waiting":
            status_label = "Approval window ended; checking final result"
        approvals.append({
            "correlation_id": correlation,
            "label": record.get("label", "Home request"),
            "target": record.get("target"),
            "status": record.get("status"),
            "status_label": status_label,
            "check_state": check_state,
            "expires_at": record.get("expires_at"),
            "can_check": check_state != "uncertain",
            "automatic": record.get("automatic", False),
            "next_check_in": max(0, record.get("next_check_at", 0) - time.monotonic()),
        })
    return approvals
