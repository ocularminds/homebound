"""Run the HomeBound MCP server over Streamable HTTP."""

from __future__ import annotations

import hmac
import json
import logging
from typing import Any

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from app.adapters.ring_mcp import RingMcpServer
from app.config.settings import Settings
from app.interception.factory import action_request_port
from app.models.policy import HomePolicyBinding

LOGGER = logging.getLogger("homebound.mcp")


class BearerTokenMiddleware:
    """Minimal constant-time bearer check for the local HTTP MCP endpoint."""

    def __init__(self, app: Any, token: str | None) -> None:
        self._app = app
        self._token = token

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope.get("path") == "/healthz":
            await self._app(scope, receive, send)
            return
        if not self._token:
            # create_asgi_app permits this mode only for local loopback development.
            await self._app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        supplied = authorization.removeprefix("Bearer ")
        if not authorization.startswith("Bearer ") or not hmac.compare_digest(
            supplied, self._token
        ):
            await self._json(send, 401, {"error": "unauthorized"})
            return
        await self._app(scope, receive, send)

    @staticmethod
    async def _json(send: Any, status: int, body: dict[str, str]) -> None:
        content = json.dumps(body).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": content})


async def healthz(_request: Request) -> Response:
    return JSONResponse({"status": "ok", "service": "homebound-mcp"})


def create_asgi_app(settings: Settings | None = None) -> Any:
    settings = settings or Settings.from_environment()
    if settings.mcp_host not in {"127.0.0.1", "localhost", "::1"}:
        if not settings.mcp_bearer_token:
            raise ValueError("HOMEBOUND_MCP_BEARER_TOKEN is required off loopback")
    if settings.homebound_environment == "production" and not settings.mcp_bearer_token:
        raise ValueError("HOMEBOUND_MCP_BEARER_TOKEN is required in production")

    policy_binding = HomePolicyBinding.from_file(settings.home_policy_binding_path)
    if settings.homebound_environment == "production" and policy_binding is None:
        raise ValueError("A published HomeBound policy binding is required in production.")
    mcp = RingMcpServer(
        action_request_port(settings), home_policy_binding=policy_binding
    ).server
    transport_security = TransportSecuritySettings(
        allowed_hosts=list(settings.mcp_allowed_hosts),
        allowed_origins=list(settings.mcp_allowed_origins),
    )
    application = mcp.streamable_http_app(transport_security=transport_security)
    application.routes.append(Route("/healthz", healthz, methods=["GET"]))
    return BearerTokenMiddleware(application, settings.mcp_bearer_token)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = Settings.from_environment()
    app = create_asgi_app(settings)
    LOGGER.info("MCP endpoint ready host=%s port=%s", settings.mcp_host, settings.mcp_port)
    uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port, log_level="info")


if __name__ == "__main__":
    main()
