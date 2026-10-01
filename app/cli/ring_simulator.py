"""Run the loopback Ring simulator as AgentSafe's only downstream provider."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from app.audit.dossier_archive import DossierArchiveClient
from app.execution.ring_simulator import RingSimulatorAdapter, SimulatorAuth, SimulatorRefusal

LOGGER = logging.getLogger("homebound.ring_simulator")


async def healthz(_request: Request) -> Response:
    return JSONResponse({"status": "ok", "service": "ring-simulator"})


def create_asgi_app(
    simulator: RingSimulatorAdapter,
    simulator_token: str,
    dossier_archiver: DossierArchiveClient,
    demo_reset_token: str | None = None,
) -> Any:
    if len(simulator_token) < 32:
        raise ValueError("HOMEBOUND_SIMULATOR_TOKEN must contain at least 32 characters")
    auth = SimulatorAuth(simulator_token)
    reset_auth = SimulatorAuth(demo_reset_token) if demo_reset_token else None

    async def execute(request: Request) -> Response:
        if not auth.verify(request.headers.get("x-homebound-simulator-token")):
            return JSONResponse({"code": "UNAUTHORIZED"}, status_code=401)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise SimulatorRefusal("REQUEST_INVALID")
            _require_header_match(request, body)
            event = simulator.execute(body)
            LOGGER.info(
                "simulated Ring action executed action=%s target=%s correlation_id=%s decision_id=%s",
                event["action"],
                event["target"],
                event["correlation_id"],
                event["decision_id"],
            )
            return JSONResponse(event)
        except SimulatorRefusal as error:
            return JSONResponse({"code": error.code}, status_code=409 if error.code.startswith("IDEMPOTENCY") else 422)
        except (ValueError, TypeError):
            return JSONResponse({"code": "REQUEST_INVALID"}, status_code=400)

    async def archive_dossier(request: Request) -> Response:
        if not auth.verify(request.headers.get("x-homebound-simulator-token")):
            return JSONResponse({"code": "UNAUTHORIZED"}, status_code=401)
        dossier_id = request.path_params["lookup_key"]
        if request.headers.get("x-agent-safe-dossier-id") != dossier_id:
            return JSONResponse({"code": "DOSSIER_BINDING_MISMATCH"}, status_code=409)
        correlation_id = request.headers.get("x-homebound-correlation-id", "")
        try:
            result = await asyncio.to_thread(dossier_archiver.archive, dossier_id, correlation_id)
        except Exception as error:
            LOGGER.warning(
                "dossier archival failed dossier_id=%s error_type=%s",
                dossier_id,
                type(error).__name__,
            )
            return JSONResponse({"code": "DOSSIER_ARCHIVE_UNAVAILABLE"}, status_code=503)
        if result.get("verified") is not True:
            return JSONResponse({"code": "DOSSIER_VERIFICATION_FAILED", "evidence": result}, status_code=409)
        return JSONResponse(result)

    async def evidence_or_reconcile(request: Request) -> Response:
        value = request.path_params["lookup_key"]
        if request.method == "GET":
            event = simulator.find_event(value)
            if event is None:
                return JSONResponse({"code": "NOT_EXECUTED"}, status_code=404)
            return JSONResponse(event)
        if request.method == "POST":
            return await archive_dossier(request)
        return JSONResponse({"code": "REQUEST_INVALID"}, status_code=400)

    async def state(_request: Request) -> Response:
        return JSONResponse(simulator.state())

    async def demo_reset(request: Request) -> Response:
        if reset_auth is None or not reset_auth.verify(
            request.headers.get("x-homebound-demo-reset-token")
        ):
            return JSONResponse({"code": "UNAUTHORIZED"}, status_code=401)
        reset_state = simulator.reset_for_demo()
        LOGGER.info("simulator returned to the secured demo baseline")
        return JSONResponse({"reset": True, "state": reset_state})

    return Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/actions", execute, methods=["POST"]),
            Route("/evidence/{lookup_key:str}", evidence_or_reconcile, methods=["GET", "POST"]),
            Route("/state", state, methods=["GET"]),
            Route("/demo/reset", demo_reset, methods=["POST"]),
        ]
    )


def _require_header_match(request: Request, body: dict[str, Any]) -> None:
    bindings = {
        "idempotency_key": "idempotency-key",
        "intent_id": "x-agent-safe-intent-id",
        "intent_hash": "x-agent-safe-intent-hash",
        "decision_id": "x-agent-safe-decision-id",
        "dossier_id": "x-agent-safe-dossier-id",
        "grant_id": "x-agent-safe-grant-id",
        "authorization_expires_at": "x-agent-safe-authorization-expires-at",
    }
    if any(request.headers.get(header) != body.get(field) for field, header in bindings.items()):
        raise SimulatorRefusal("AUTHORIZATION_HEADER_MISMATCH")
    if request.headers.get("x-homebound-correlation-id") != body.get("correlation_id"):
        raise SimulatorRefusal("CORRELATION_ID_MISMATCH")
    supplied_claim = request.headers.get("x-agent-safe-claim-attestation")
    body_claim = body.get("claim_attestation")
    if body_claim is not None and supplied_claim != body_claim:
        raise SimulatorRefusal("CLAIM_ATTESTATION_MISMATCH")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    host = os.getenv("HOMEBOUND_SIMULATOR_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("The Ring simulator must bind to loopback.")
    port = int(os.getenv("HOMEBOUND_SIMULATOR_PORT", "8200"))
    audit_directory = Path(os.getenv("HOMEBOUND_AUDIT_DIRECTORY", "audit"))
    simulator = RingSimulatorAdapter(audit_directory / "ring-simulator.sqlite3")
    archiver_url = os.getenv("HOMEBOUND_DOSSIER_ARCHIVER_URL", "http://127.0.0.1:8101")
    archiver_token = os.getenv("HOMEBOUND_DOSSIER_ARCHIVER_TOKEN", "")
    if not archiver_token:
        raise SystemExit("Configure HOMEBOUND_DOSSIER_ARCHIVER_TOKEN for the Ring simulator.")
    archiver = DossierArchiveClient(archiver_url, archiver_token)
    token = os.getenv("HOMEBOUND_SIMULATOR_TOKEN", "")
    reset_token = os.getenv("HOMEBOUND_SIMULATOR_DEMO_TOKEN") or None
    if reset_token is not None and len(reset_token) < 32:
        raise SystemExit("HOMEBOUND_SIMULATOR_DEMO_TOKEN must contain at least 32 characters.")
    app = create_asgi_app(simulator, token, archiver, reset_token)
    LOGGER.info("Ring simulator ready host=%s port=%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
