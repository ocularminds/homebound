"""Safe candidate construction for versioned Decionis policy publication."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import publish_homebound_policy
from scripts.publish_homebound_policy import EXPECTED_COMMERCE_RULES, build_candidate


def _commerce_bundle() -> dict[str, object]:
    return {
        "bundle_id": "123e4567-e89b-12d3-a456-426614174000",
        "version": "commerce-policy-v1",
        "rules": [
            {"rule_id": rule_id, "name": rule_id, "when": {}, "then": {"action": "REQUIRE_REVIEW"}}
            for rule_id in sorted(EXPECTED_COMMERCE_RULES)
        ],
    }


def test_candidate_merges_homebound_rules_and_preserves_all_existing_rules() -> None:
    candidate = build_candidate(_commerce_bundle(), "123e4567-e89b-12d3-a456-426614174001")

    ids = {rule["rule_id"] for rule in candidate["rules"]}
    assert EXPECTED_COMMERCE_RULES <= ids
    assert {
        "homebound.authenticated-parent-disarm-allow",
        "homebound.child-disarm-escalation",
        "homebound.courier-unlock-in-window",
        "homebound.courier-unlock-outside-window",
        "homebound.courier-unlock-before-window",
    } <= ids
    assert candidate["bundle_id"] != _commerce_bundle()["bundle_id"]
    assert candidate["version"] == "homebound-household-v1"
    assert {rule["then"].get("severity") for rule in candidate["rules"] if rule["rule_id"].startswith("homebound.")} <= {
        "routine",
        "elevated",
        "urgent",
    }


def test_candidate_refuses_to_overwrite_an_unrecognized_bundle() -> None:
    current = _commerce_bundle()
    current["rules"] = [{"rule_id": "another-product.policy"}]

    with pytest.raises(RuntimeError, match="changed"):
        build_candidate(current, "123e4567-e89b-12d3-a456-426614174001")


def test_rechecking_the_immutable_seed_does_not_roll_back_an_owner_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    binding_path = tmp_path / ".homebound" / "policy-binding.json"
    binding_path.parent.mkdir()
    current = {
        "home_id": "homebound-demo-home",
        "org_id": "123e4567-e89b-12d3-a456-426614174000",
        "bundle_id": "123e4567-e89b-12d3-a456-426614174002",
        "policy_version": "homebound-household-v2",
        "version_history": [{
            "bundle_id": "123e4567-e89b-12d3-a456-426614174002",
            "policy_version": "homebound-household-v2",
            "recorded_at": "2026-10-02T12:00:00+00:00",
            "source": "owner-workspace",
        }],
    }
    binding_path.write_text(json.dumps(current), encoding="utf-8")
    monkeypatch.setattr(publish_homebound_policy, "ROOT", tmp_path)
    publish_homebound_policy._record_home_binding(
        "123e4567-e89b-12d3-a456-426614174000",
        "123e4567-e89b-12d3-a456-426614174001",
    )
    assert json.loads(binding_path.read_text(encoding="utf-8")) == current


def test_publisher_refuses_to_reassign_home_to_another_org(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    binding_path = tmp_path / ".homebound" / "policy-binding.json"
    binding_path.parent.mkdir()
    binding_path.write_text(
        json.dumps({
            "home_id": "homebound-demo-home",
            "org_id": "123e4567-e89b-12d3-a456-426614174000",
            "bundle_id": "123e4567-e89b-12d3-a456-426614174001",
            "policy_version": "homebound-household-v1",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(publish_homebound_policy, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="another Decionis organization"):
        publish_homebound_policy._record_home_binding(
            "123e4567-e89b-12d3-a456-426614174099",
            "123e4567-e89b-12d3-a456-426614174001",
        )
