"""Home binding follows only the active Decionis Protocol policy version."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from scripts import sync_home_policy_binding as sync
from scripts.home_policy_binding import record_policy_version, write_private_json

ORG_ID = "123e4567-e89b-12d3-a456-426614174000"
OLD_BUNDLE_ID = "123e4567-e89b-12d3-a456-426614174001"
NEW_BUNDLE_ID = "123e4567-e89b-12d3-a456-426614174002"
HOME_RULES = [
    "homebound.authenticated-parent-disarm-allow",
    "homebound.child-disarm-escalation",
    "homebound.courier-unlock-in-window",
    "homebound.courier-unlock-outside-window",
    "homebound.courier-unlock-before-window",
]


def _binding() -> dict[str, object]:
    return {
        "home_id": "homebound-demo-home",
        "org_id": ORG_ID,
        "bundle_id": OLD_BUNDLE_ID,
        "policy_version": "homebound-household-v1",
    }


def _register(bundle_id: str = NEW_BUNDLE_ID, version: str = "homebound-household-v2") -> dict[str, object]:
    return {
        "org_id": ORG_ID,
        "active_bundle_id": bundle_id,
        "active_bundle_version": version,
        "no_active_bundle": False,
    }


def _bundles(
    bundle_id: str = NEW_BUNDLE_ID,
    version: str = "homebound-household-v2",
    rule_ids: list[str] | None = None,
) -> list[dict[str, object]]:
    return [
        {
            "bundle_id": bundle_id,
            "org_id": ORG_ID,
            "version": version,
            "lifecycle_state": "ACTIVE",
            "rules": [{"rule_id": rule_id} for rule_id in (rule_ids or HOME_RULES)],
        }
    ]


def test_synchronization_tracks_active_owner_version_for_the_same_home() -> None:
    updated = sync.build_synchronized_binding(
        _binding(), _register(), _bundles(), recorded_at="2026-10-02T12:00:00+00:00"
    )

    assert updated["home_id"] == "homebound-demo-home"
    assert updated["org_id"] == ORG_ID
    assert updated["bundle_id"] == NEW_BUNDLE_ID
    assert updated["policy_version"] == "homebound-household-v2"
    history = updated["version_history"]
    assert [(entry["policy_version"], entry["source"]) for entry in history] == [
        ("homebound-household-v1", "existing_home_binding"),
        ("homebound-household-v2", "decionis_protocol_active_bundle"),
    ]


@pytest.mark.parametrize(
    ("register", "bundles", "message"),
    [
        (_register(bundle_id=None, version=None), [], "no active policy"),
        ({**_register(), "org_id": "123e4567-e89b-12d3-a456-426614174099"}, _bundles(), "another organization"),
        (_register(), [], "missing from the Decionis bundle list"),
        (_register(), _bundles(rule_ids=HOME_RULES[:-1]), "no longer contains every HomeBound rule"),
        (_register(), _bundles(version="different-version"), "do not match the Decionis decision register"),
        (
            _register(),
            [{
                "bundle_id": NEW_BUNDLE_ID,
                "org_id": ORG_ID,
                "version": "homebound-household-v2",
                "lifecycle_state": "INACTIVE",
                "rules": [{"rule_id": rule_id} for rule_id in HOME_RULES],
            }],
            "not in ACTIVE lifecycle state",
        ),
    ],
)
def test_invalid_active_policy_snapshots_are_refused(
    register: dict[str, object], bundles: list[dict[str, object]], message: str
) -> None:
    with pytest.raises(RuntimeError, match=message):
        sync.build_synchronized_binding(
            _binding(), register, bundles, recorded_at="2026-10-02T12:00:00+00:00"
        )


def test_active_policy_change_during_reads_is_refused() -> None:
    responses = iter(
        [
            _register(),
            {"bundles": _bundles()},
            _register(bundle_id=OLD_BUNDLE_ID, version="another-owner-change"),
        ]
    )
    calls = []

    def get(path: str, query: dict[str, str]) -> dict[str, object]:
        calls.append((path, query))
        return next(responses)

    with pytest.raises(RuntimeError, match="changed during sync"):
        sync._active_policy_snapshot(ORG_ID, get)
    assert [path for path, _ in calls] == [
        sync.DECISION_REGISTER_PATH,
        sync.POLICY_BUNDLES_PATH,
        sync.DECISION_REGISTER_PATH,
    ]
    assert all(query == {"org_id": ORG_ID, "limit": "500"} for _, query in calls)


def test_sync_defaults_to_dry_run_and_apply_writes_private_binding(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / ".homebound" / "policy-binding.json"
    path.parent.mkdir()
    path.write_text(json.dumps(_binding()), encoding="utf-8")
    monkeypatch.setattr(sync, "BINDING_PATH", path)
    monkeypatch.setattr(sync, "_load_local_env", lambda: None)
    monkeypatch.setenv("EXECUTOR_TENANT_ID", ORG_ID)

    def get(endpoint: str, _query: dict[str, str]) -> dict[str, object]:
        if endpoint == sync.DECISION_REGISTER_PATH:
            return _register()
        return {"bundles": _bundles()}

    assert sync.synchronize(apply=False, get=get) == 0
    assert json.loads(path.read_text(encoding="utf-8")) == _binding()

    assert sync.synchronize(apply=True, get=get) == 0
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["bundle_id"] == NEW_BUNDLE_ID
    assert written["policy_version"] == "homebound-household-v2"
    assert len(written["version_history"]) == 2
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_binding_version_history_is_idempotent() -> None:
    initial = record_policy_version(
        _binding(),
        bundle_id=OLD_BUNDLE_ID,
        policy_version="homebound-household-v1",
        recorded_at="2026-10-02T12:00:00+00:00",
        source="publisher",
    )
    repeated = record_policy_version(
        initial,
        bundle_id=OLD_BUNDLE_ID,
        policy_version="homebound-household-v1",
        recorded_at="2026-10-03T12:00:00+00:00",
        source="sync",
    )
    assert len(repeated["version_history"]) == 1
    assert repeated["version_history"][0]["source"] == "publisher"


def test_private_binding_writer_sets_owner_only_permissions(tmp_path: Path) -> None:
    destination = tmp_path / ".homebound" / "policy-binding.json"
    write_private_json(destination, _binding())
    assert json.loads(destination.read_text(encoding="utf-8")) == _binding()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700
