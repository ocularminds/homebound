"""Stable association between one HomeBound home and its Decionis policy."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class HomePolicyBinding:
    """Versioned home-to-policy reference; it grants no authority by itself."""

    home_id: str
    org_id: str
    bundle_id: str
    policy_version: str

    def __post_init__(self) -> None:
        if not self.home_id.strip() or len(self.home_id) > 120:
            raise ValueError("home_id must be a non-empty stable identifier")
        UUID(self.org_id)
        UUID(self.bundle_id)
        if not self.policy_version.strip() or len(self.policy_version) > 100:
            raise ValueError("policy_version must be a non-empty version identifier")

    def as_dict(self) -> dict[str, str]:
        """Expose a JSON-safe binding for the exact AgentSafe intent and audit."""

        return asdict(self)

    @classmethod
    def from_file(cls, path: str | Path) -> HomePolicyBinding | None:
        """Load the private local binding file; missing means not yet provisioned."""

        source = Path(path)
        if not source.exists():
            return None
        raw: Any = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("home policy binding must be a JSON object")
        return cls(
            home_id=raw["home_id"],
            org_id=raw["org_id"],
            bundle_id=raw["bundle_id"],
            policy_version=raw["policy_version"],
        )
