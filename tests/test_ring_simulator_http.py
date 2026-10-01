"""HTTP boundary tests for the local simulator and its demo-only reset control."""

from __future__ import annotations

from pathlib import Path

import httpx2
import pytest

from app.cli.ring_simulator import create_asgi_app
from app.execution.ring_simulator import RingSimulatorAdapter


class EvidenceFixture:
    def archive(self, dossier_id: str, correlation_id: str) -> dict[str, object]:
        return {
            "dossier_id": dossier_id,
            "correlation_id": correlation_id,
            "reference": f"dossier-{dossier_id}",
            "verified": True,
            "trust_anchor": "DECIONIS_OFFICIAL",
        }


def action_body() -> dict[str, object]:
    return {
        "action": "unlockDoor",
        "target": "side_gate",
        "parameters": {"device_parameters": {"unlock_duration_seconds": 30}},
        "idempotency_key": "idem-1",
        "correlation_id": "corr-1",
        "intent_id": "intent-1",
        "intent_hash": "sha256:intent-1",
        "decision_id": "decision-1",
        "dossier_id": "dossier-1",
        "grant_id": "grant-1",
        "authorization_expires_at": "2030-01-01T00:00:00Z",
        "claim_attestation": None,
        "dossier_evidence": {
            "verified": True,
            "reference": "dossier-ref",
            "trust_anchor": "DECIONIS_OFFICIAL",
        },
    }


@pytest.mark.asyncio
async def test_simulator_rejects_direct_request_and_only_dispatches_bound_executor_call(
    tmp_path: Path,
) -> None:
    simulator = RingSimulatorAdapter(tmp_path / "ring.sqlite3")
    app = create_asgi_app(simulator, "s" * 40, EvidenceFixture(), "d" * 40)
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        direct = await client.post("/actions", json=action_body())
        assert direct.status_code == 401
        assert simulator.state()["door_locked"]["side_gate"] is True

        request = action_body()
        headers = {
            "x-homebound-simulator-token": "s" * 40,
            "idempotency-key": request["idempotency_key"],
            "x-agent-safe-intent-id": request["intent_id"],
            "x-agent-safe-intent-hash": request["intent_hash"],
            "x-agent-safe-decision-id": request["decision_id"],
            "x-agent-safe-dossier-id": request["dossier_id"],
            "x-agent-safe-grant-id": request["grant_id"],
            "x-agent-safe-authorization-expires-at": request["authorization_expires_at"],
            "x-homebound-correlation-id": request["correlation_id"],
        }
        allowed = await client.post("/actions", json=request, headers=headers)
        assert allowed.status_code == 200
        assert allowed.json()["result"] == "executed"

        mismatch = await client.post(
            "/actions",
            json={**action_body(), "target": "front_door"},
            headers=headers,
        )
        assert mismatch.status_code == 409
        assert mismatch.json()["code"] == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_ACTION"


@pytest.mark.asyncio
async def test_demo_reset_requires_separate_local_harness_token(tmp_path: Path) -> None:
    simulator = RingSimulatorAdapter(tmp_path / "ring.sqlite3")
    simulator.execute(
        {
            **action_body(),
            "action": "unlockDoor",
        }
    )
    app = create_asgi_app(simulator, "s" * 40, EvidenceFixture(), "d" * 40)
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        denied = await client.post("/demo/reset")
        assert denied.status_code == 401
        reset = await client.post(
            "/demo/reset", headers={"x-homebound-demo-reset-token": "d" * 40}
        )

    assert reset.status_code == 200
    assert reset.json()["state"]["door_locked"]["side_gate"] is True
