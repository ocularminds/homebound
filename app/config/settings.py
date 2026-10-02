"""Small environment configuration shared by the local commands."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    aws_region: str
    bedrock_model_id: str
    mcp_endpoint: str
    mcp_bearer_token: str | None
    mcp_host: str
    mcp_port: int
    mcp_allowed_hosts: tuple[str, ...]
    mcp_allowed_origins: tuple[str, ...]
    homebound_environment: str
    agentsafe_endpoint: str | None = None
    agentsafe_bearer_token: str | None = None
    audit_directory: str = "audit"
    dossier_archiver_endpoint: str | None = None
    dossier_archiver_bearer_token: str | None = None
    home_policy_binding_path: str = ".homebound/policy-binding.json"

    @classmethod
    def from_environment(cls) -> "Settings":
        host = os.getenv("HOMEBOUND_MCP_HOST", "127.0.0.1")
        port = int(os.getenv("HOMEBOUND_MCP_PORT", "8000"))
        allowed_hosts = tuple(
            item.strip()
            for item in os.getenv(
                "HOMEBOUND_MCP_ALLOWED_HOSTS",
                f"localhost:{port},127.0.0.1:{port},[::1]:{port}",
            ).split(",")
            if item.strip()
        )
        allowed_origins = tuple(
            item.strip()
            for item in os.getenv("HOMEBOUND_MCP_ALLOWED_ORIGINS", "").split(",")
            if item.strip()
        )
        return cls(
            aws_region=os.getenv("AWS_REGION", "us-east-1"),
            bedrock_model_id=os.getenv("BEDROCK_MODEL_ID", ""),
            mcp_endpoint=os.getenv("HOMEBOUND_MCP_ENDPOINT", "http://127.0.0.1:8000/mcp"),
            mcp_bearer_token=os.getenv("HOMEBOUND_MCP_BEARER_TOKEN") or None,
            mcp_host=host,
            mcp_port=port,
            mcp_allowed_hosts=allowed_hosts,
            mcp_allowed_origins=allowed_origins,
            homebound_environment=os.getenv("HOMEBOUND_ENV", "development").lower(),
            agentsafe_endpoint=os.getenv("HOMEBOUND_AGENTSAFE_URL") or None,
            agentsafe_bearer_token=os.getenv("HOMEBOUND_AGENTSAFE_BEARER_TOKEN") or None,
            audit_directory=os.getenv("HOMEBOUND_AUDIT_DIRECTORY", "audit"),
            dossier_archiver_endpoint=os.getenv("HOMEBOUND_DOSSIER_ARCHIVER_URL") or None,
            dossier_archiver_bearer_token=os.getenv("HOMEBOUND_DOSSIER_ARCHIVER_TOKEN") or None,
            home_policy_binding_path=os.getenv(
                "HOMEBOUND_POLICY_BINDING_PATH", ".homebound/policy-binding.json"
            ),
        )
