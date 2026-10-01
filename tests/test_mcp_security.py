"""Local MCP endpoint configuration checks."""

import pytest

from app.cli.mcp_server import create_asgi_app
from app.config.settings import Settings


def settings(**changes: object) -> Settings:
    defaults: dict[str, object] = {
        "aws_region": "us-east-1",
        "bedrock_model_id": "",
        "mcp_endpoint": "http://127.0.0.1:8000/mcp",
        "mcp_bearer_token": None,
        "mcp_host": "127.0.0.1",
        "mcp_port": 8000,
        "mcp_allowed_hosts": ("127.0.0.1:8000",),
        "mcp_allowed_origins": (),
        "homebound_environment": "development",
    }
    defaults.update(changes)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_non_loopback_mcp_requires_bearer_token() -> None:
    with pytest.raises(ValueError, match="required off loopback"):
        create_asgi_app(settings(mcp_host="0.0.0.0"))


def test_production_mcp_requires_bearer_token() -> None:
    with pytest.raises(ValueError, match="required in production"):
        create_asgi_app(settings(homebound_environment="production"))
