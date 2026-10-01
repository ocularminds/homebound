"""Private append-only JSONL records of governed action outcomes."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models.actions import ActionProposal, ActionResult


class ActionAuditLog:
    """Persist every returned governance result beside local execution events."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._path.touch(mode=0o600, exist_ok=True)
        self._path.chmod(0o600)

    def append(
        self,
        proposal: ActionProposal,
        result: ActionResult,
        dossier_evidence: dict[str, Any] | None,
    ) -> None:
        record = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "correlation_id": proposal.correlation_id,
            "proposal": proposal.as_dict(),
            "result": result.as_dict(),
            "dossier_evidence": dossier_evidence,
        }
        line = (json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n").encode()
        descriptor = os.open(self._path, os.O_WRONLY | os.O_APPEND)
        try:
            remaining = memoryview(line)
            while remaining:
                written = os.write(descriptor, remaining)
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
