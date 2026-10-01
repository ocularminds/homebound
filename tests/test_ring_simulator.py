"""Mutation, replay, binding, and state tests for the explicitly local Ring simulator."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.execution.ring_simulator import RingSimulatorAdapter, SimulatorRefusal


def authorized_request(**changes: object) -> dict[str, object]:
    request: dict[str, object] = {
        "action": "unlockDoor",
        "target": "side_gate",
        "parameters": {
            "homebound_purpose": "expected courier",
            "context_signals": {"delivery_expected": True, "local_time": "14:30"},
            "device_parameters": {"unlock_duration_seconds": 30},
        },
        "idempotency_key": "idem-1",
        "correlation_id": "corr-1",
        "intent_id": "intent-1",
        "intent_hash": "sha256:bound-intent",
        "decision_id": "decision-1",
        "dossier_id": "dossier-1",
        "grant_id": "grant-1",
        "authorization_expires_at": "2030-01-01T00:00:00Z",
        "claim_attestation": None,
        "dossier_evidence": {
            "verified": True,
            "reference": "dossier-archive-ref",
            "trust_anchor": "DECIONIS_OFFICIAL",
        },
    }
    request.update(changes)
    return request


def test_allow_mutates_state_and_records_bound_event_once(tmp_path) -> None:
    simulator = RingSimulatorAdapter(
        tmp_path / "ring.sqlite3",
        now=lambda: datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
    )
    request = authorized_request()

    event = simulator.execute(request)
    replay = simulator.execute(request)

    assert event == replay
    assert event["result"] == "executed"
    assert event["action"] == "unlockDoor"
    assert event["target"] == "side_gate"
    assert event["timestamp"] == "2026-10-01T12:00:00+00:00"
    assert event["decision_id"] == "decision-1"
    assert event["grant_id"] == "grant-1"
    assert event["authorization_expires_at"] == "2030-01-01T00:00:00Z"
    assert simulator.state()["door_locked"]["side_gate"] is False
    assert simulator.find_event("idem-1") == event


@pytest.mark.parametrize(
    "changes",
    [
        {"target": "front_door"},
        {
            "parameters": {
                "homebound_purpose": "expected courier",
                "context_signals": {"delivery_expected": True, "local_time": "14:30"},
                "device_parameters": {"unlock_duration_seconds": 60},
            }
        },
        {"dossier_id": "different-dossier"},
        {"grant_id": "different-grant"},
    ],
)
def test_idempotency_rejects_mutated_bound_action(tmp_path, changes) -> None:
    simulator = RingSimulatorAdapter(tmp_path / "ring.sqlite3")
    simulator.execute(authorized_request())

    with pytest.raises(SimulatorRefusal, match="IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_ACTION"):
        simulator.execute(authorized_request(**changes))


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"decision_id": ""}, "AUTHORIZATION_BINDING_MISSING"),
        ({"dossier_evidence": {"verified": False}}, "DOSSIER_EVIDENCE_NOT_VERIFIED"),
        ({"dossier_evidence": {"verified": True, "reference": "x", "trust_anchor": "UNESTABLISHED"}}, "DOSSIER_EVIDENCE_NOT_VERIFIED"),
    ],
)
def test_simulator_refuses_missing_authority_or_dossier_proof(tmp_path, changes, code) -> None:
    simulator = RingSimulatorAdapter(tmp_path / "ring.sqlite3")

    with pytest.raises(SimulatorRefusal, match=code):
        simulator.execute(authorized_request(**changes))
    assert simulator.state()["door_locked"]["side_gate"] is True


def test_simulator_rejects_authorization_after_expiry(tmp_path) -> None:
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    simulator = RingSimulatorAdapter(tmp_path / "ring.sqlite3", now=lambda: now)

    with pytest.raises(SimulatorRefusal, match="AUTHORIZATION_EXPIRED"):
        simulator.execute(
            authorized_request(authorization_expires_at="2026-10-01T11:59:59Z")
        )

    with pytest.raises(SimulatorRefusal, match="AUTHORIZATION_EXPIRY_INVALID"):
        simulator.execute(authorized_request(authorization_expires_at="2030-01-01T00:00:00"))
    assert simulator.state()["door_locked"]["side_gate"] is True


def test_simulator_enforces_each_device_action_and_target(tmp_path) -> None:
    simulator = RingSimulatorAdapter(tmp_path / "ring.sqlite3")
    disarm = authorized_request(
        action="disarmSystem",
        target="home_security",
        idempotency_key="idem-2",
        decision_id="decision-2",
        dossier_id="dossier-2",
    )
    stream = authorized_request(
        action="viewStream",
        target="front_door",
        idempotency_key="idem-3",
        decision_id="decision-3",
        dossier_id="dossier-3",
    )

    disarm_event = simulator.execute(disarm)
    stream_event = simulator.execute(stream)

    assert disarm_event["result"] == "executed"
    assert simulator.state()["security_system_armed"]["home_security"] is False
    assert stream_event["result"] == "executed"
    assert simulator.state()["camera_stream_available"]["front_door"] is True
