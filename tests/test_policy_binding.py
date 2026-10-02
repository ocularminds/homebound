"""Contract tests for the local home-to-policy binding."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.policy import HomePolicyBinding


def test_home_policy_binding_loads_and_preserves_versioned_association(tmp_path: Path) -> None:
    path = tmp_path / "policy-binding.json"
    path.write_text(
        json.dumps(
            {
                "home_id": "homebound-demo-home",
                "org_id": "123e4567-e89b-12d3-a456-426614174000",
                "bundle_id": "123e4567-e89b-12d3-a456-426614174001",
                "policy_version": "homebound-household-v1",
            }
        ),
        encoding="utf-8",
    )

    binding = HomePolicyBinding.from_file(path)

    assert binding is not None
    assert binding.as_dict() == {
        "home_id": "homebound-demo-home",
        "org_id": "123e4567-e89b-12d3-a456-426614174000",
        "bundle_id": "123e4567-e89b-12d3-a456-426614174001",
        "policy_version": "homebound-household-v1",
    }


def test_home_policy_binding_rejects_malformed_tenant_or_bundle_ids() -> None:
    with pytest.raises(ValueError):
        HomePolicyBinding(
            home_id="homebound-demo-home",
            org_id="not-a-uuid",
            bundle_id="123e4567-e89b-12d3-a456-426614174001",
            policy_version="homebound-household-v1",
        )


def test_missing_binding_file_means_unprovisioned_home(tmp_path: Path) -> None:
    assert HomePolicyBinding.from_file(tmp_path / "missing.json") is None
