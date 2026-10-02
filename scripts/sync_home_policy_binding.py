"""Sync the private home binding to the Decionis workspace's active policy version."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.models.policy import HomePolicyBinding
from scripts.home_policy_binding import record_policy_version, write_private_json
from scripts.publish_homebound_policy import (
    API_ORIGIN,
    RULES_PATH,
    _load_local_env,
)

BINDING_PATH = PROJECT_ROOT / ".homebound" / "policy-binding.json"
DECISION_REGISTER_PATH = "/v1/protocol/decision-register"
POLICY_BUNDLES_PATH = "/v1/protocol/policies/bundles"
HOME_RULE_IDS = frozenset(
    rule["rule_id"] for rule in json.loads(RULES_PATH.read_text(encoding="utf-8"))["rules"]
)
ProtocolGet = Callable[[str, dict[str, str]], dict[str, Any]]


def _protocol_get(path: str, query: dict[str, str]) -> dict[str, Any]:
    """Read one org-scoped Protocol resource without exposing auth or query values."""

    api_key = os.environ.get("DECIONIS_API_KEY", "")
    if not api_key:
        raise RuntimeError("DECIONIS_API_KEY is missing from agentsafe/.env.")
    url = f"{API_ORIGIN}{path}?{urlencode(query)}"
    request = Request(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise RuntimeError(f"Decionis Protocol read failed for {path} (HTTP {error.code}).") from None
    except Exception:
        raise RuntimeError(f"Decionis Protocol read failed for {path} (network or response error).") from None
    if not isinstance(payload, dict):
        raise RuntimeError(f"Decionis Protocol returned an invalid response for {path}.")
    return payload


def _active_policy_snapshot(org_id: str, get: ProtocolGet = _protocol_get) -> tuple[dict[str, Any], dict[str, Any]]:
    query = {"org_id": org_id, "limit": "500"}
    register = get(DECISION_REGISTER_PATH, query)
    bundles_response = get(POLICY_BUNDLES_PATH, query)
    confirmed = get(DECISION_REGISTER_PATH, query)
    active = (register.get("active_bundle_id"), register.get("active_bundle_version"))
    confirmed_active = (confirmed.get("active_bundle_id"), confirmed.get("active_bundle_version"))
    if active != confirmed_active:
        raise RuntimeError("The active Decionis policy changed during sync; retry the command.")
    bundles = bundles_response.get("bundles") or bundles_response.get("items") or bundles_response.get("data")
    if not isinstance(bundles, list) or any(not isinstance(item, dict) for item in bundles):
        raise RuntimeError("Decionis returned an invalid policy bundle list.")
    return register, {"bundles": bundles}


def build_synchronized_binding(
    binding: dict[str, Any],
    register: dict[str, Any],
    bundles: list[dict[str, Any]],
    *,
    recorded_at: str,
) -> dict[str, Any]:
    """Validate the shared active-policy view and build a home-bound version update."""

    current = HomePolicyBinding(
        home_id=binding["home_id"],
        org_id=binding["org_id"],
        bundle_id=binding["bundle_id"],
        policy_version=binding["policy_version"],
    )
    if register.get("org_id") != current.org_id:
        raise RuntimeError("Decionis decision register belongs to another organization.")
    active_id = register.get("active_bundle_id")
    active_version = register.get("active_bundle_version")
    if not isinstance(active_id, str) or not isinstance(active_version, str) or not active_version:
        raise RuntimeError("Decionis has no active policy bundle for this home.")
    bundle = next((item for item in bundles if item.get("bundle_id") == active_id), None)
    if bundle is None:
        raise RuntimeError("The active policy is missing from the Decionis bundle list.")
    if bundle.get("org_id") != current.org_id or bundle.get("version") != active_version:
        raise RuntimeError("The active policy details do not match the Decionis decision register.")
    if bundle.get("lifecycle_state", "ACTIVE") != "ACTIVE":
        raise RuntimeError("The active policy bundle is not in ACTIVE lifecycle state.")
    rules = bundle.get("rules")
    if not isinstance(rules, list):
        raise RuntimeError("The active policy bundle has no rule list.")
    present_rule_ids = {rule.get("rule_id") for rule in rules if isinstance(rule, dict)}
    if not HOME_RULE_IDS <= present_rule_ids:
        raise RuntimeError("The active policy no longer contains every HomeBound rule; review before sync.")

    return record_policy_version(
        binding,
        bundle_id=active_id,
        policy_version=active_version,
        recorded_at=recorded_at,
        source="decionis_protocol_active_bundle",
    )


def synchronize(*, apply: bool, get: ProtocolGet = _protocol_get) -> int:
    """Preview or apply the active Decionis policy version to the private home record."""

    _load_local_env()
    if not BINDING_PATH.is_file():
        raise RuntimeError("No private HomeBound policy binding exists; publish a policy first.")
    binding = json.loads(BINDING_PATH.read_text(encoding="utf-8"))
    if not isinstance(binding, dict):
        raise RuntimeError("The private HomeBound policy binding is invalid.")
    current = HomePolicyBinding(
        home_id=binding["home_id"],
        org_id=binding["org_id"],
        bundle_id=binding["bundle_id"],
        policy_version=binding["policy_version"],
    )
    if os.environ.get("EXECUTOR_TENANT_ID") != current.org_id:
        raise RuntimeError("The configured Decionis organization does not match this home binding.")
    register, bundle_response = _active_policy_snapshot(current.org_id, get)
    updated = build_synchronized_binding(
        binding,
        register,
        bundle_response["bundles"],
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )
    changed = updated != binding
    print(
        f"HOME POLICY SYNC current={current.policy_version} "
        f"active={updated['policy_version']} "
        f"new_version={updated['bundle_id'] != current.bundle_id or updated['policy_version'] != current.policy_version}"
    )
    if not apply:
        print("DRY RUN; rerun with --apply to update the local home binding.")
        return 0
    if changed:
        write_private_json(BINDING_PATH, updated)
        print("UPDATED private home binding and version history; no tenant values were printed.")
    else:
        print("Home binding is already current; no file changes were needed.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the verified active version locally")
    args = parser.parse_args()
    try:
        raise SystemExit(synchronize(apply=args.apply))
    except (RuntimeError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
