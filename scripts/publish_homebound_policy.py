"""Validate and publish the HomeBound rules into the tenant's existing bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4, uuid5

from scripts.home_policy_binding import record_policy_version, write_private_json

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / "agentsafe" / ".env"
RULES_PATH = ROOT / "policies" / "homebound-household-policy.rules.json"
API_ORIGIN = "https://api.decionis.com"
POLICY_VERSION = "homebound-household-v1"
EXPECTED_COMMERCE_RULES = {
    "commerce.margin-floor",
    "commerce.inventory-floor",
    "commerce.discount-stacking",
}


def _load_local_env() -> None:
    """Load only missing variables from the ignored AgentSafe env file."""

    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        row = line.strip()
        if not row or row.startswith("#") or "=" not in row:
            continue
        key, value = row.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _request(method: str, path: str, *, body: dict[str, Any] | None = None,
             idempotency_key: str | None = None, correlation_id: str | None = None) -> tuple[int, dict[str, Any]]:
    key = os.environ.get("DECIONIS_API_KEY", "")
    if not key:
        raise RuntimeError("DECIONIS_API_KEY is missing from agentsafe/.env.")
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    payload = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    if correlation_id:
        headers["X-Correlation-ID"] = correlation_id
    request = Request(f"{API_ORIGIN}{path}", data=payload, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            return response.status, data if isinstance(data, dict) else {}
    except HTTPError as error:
        try:
            body = json.loads(error.read().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            body = {}
        safe_detail = json.dumps(body, separators=(",", ":"))[:1200]
        for sensitive in (key, os.environ.get("EXECUTOR_TENANT_ID", "")):
            if sensitive:
                safe_detail = safe_detail.replace(sensitive, "[redacted]")
        raise RuntimeError(
            f"Decionis request failed ({method} {path}, HTTP {error.code}): {safe_detail}"
        ) from None
    except Exception as error:
        # urllib errors can contain the requested URL, which carries org_id.
        # Avoid printing response bodies or request headers at this boundary.
        code = getattr(error, "code", None)
        raise RuntimeError(f"Decionis request failed ({method} {path}, HTTP {code or 'network'}).") from None


def _bundle_list(org_id: str) -> list[dict[str, Any]]:
    query = urlencode({"org_id": org_id, "limit": 100})
    status, response = _request("GET", f"/v1/protocol/policies/bundles?{query}")
    if status != 200:
        raise RuntimeError(f"Policy bundle list returned HTTP {status}.")
    bundles = response.get("bundles") or response.get("items") or response.get("data") or []
    if not isinstance(bundles, list) or any(not isinstance(item, dict) for item in bundles):
        raise RuntimeError("Decionis returned an invalid policy bundle list.")
    return bundles


def build_candidate(current: dict[str, Any], org_id: str) -> dict[str, Any]:
    rules_document = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    home_rules = rules_document.get("rules")
    if not isinstance(home_rules, list) or len(home_rules) != 5:
        raise RuntimeError("The HomeBound policy rules file is incomplete.")
    existing_rules = current.get("rules")
    if not isinstance(existing_rules, list):
        raise RuntimeError("The active Decionis bundle has no rules list.")
    by_id = {rule.get("rule_id"): rule for rule in existing_rules if isinstance(rule, dict)}
    if set(by_id) != EXPECTED_COMMERCE_RULES:
        raise RuntimeError("The active bundle changed; refusing to replace unknown policies.")
    for rule in home_rules:
        by_id[rule["rule_id"]] = rule
    return {
        "protocol_version": "1.0.0",
        # Protocol revisions are immutable: use a new stable bundle ID while
        # copying the reviewed rules from the currently active bundle.
        "bundle_id": str(uuid5(UUID(current["bundle_id"]), POLICY_VERSION)),
        "org_id": org_id,
        "version": POLICY_VERSION,
        "effective_from": datetime.now(timezone.utc).isoformat(),
        "rules": list(by_id.values()),
        "metadata": {
            "author": "HomeBound",
            "source": "HomeBound household policy",
            "change_ticket": "homebound-production-policy-v1",
        },
    }


def _record_home_binding(org_id: str, bundle_id: str) -> None:
    """Store the verified association privately for the local HomeBound home."""

    path = ROOT / ".homebound" / "policy-binding.json"
    existing: dict[str, Any] = {}
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            existing = loaded
    if existing and existing.get("org_id") != org_id:
        raise RuntimeError("The existing HomeBound home is bound to another Decionis organization.")
    if existing and existing.get("policy_version") != POLICY_VERSION:
        # The policy seed is immutable. An owner may already have published a
        # newer workspace version; keep that binding for the sync command.
        return
    if existing and existing.get("bundle_id") not in {None, bundle_id}:
        raise RuntimeError("The existing HomeBound policy version is bound to another bundle.")
    home_id = os.environ.get("HOMEBOUND_HOME_ID") or existing.get("home_id") or str(uuid4())
    binding = record_policy_version(
        {
            **existing,
            "home_id": home_id,
            "org_id": org_id,
            "bundle_id": existing.get("bundle_id", bundle_id),
            "policy_version": existing.get("policy_version", POLICY_VERSION),
        },
        bundle_id=bundle_id,
        policy_version=POLICY_VERSION,
        recorded_at=datetime.now(timezone.utc).isoformat(),
        source="decionis_protocol_publisher",
    )
    write_private_json(path, binding)


def publish(*, publish_now: bool) -> int:
    _load_local_env()
    org_id = os.environ.get("EXECUTOR_TENANT_ID", "")
    if not org_id:
        raise RuntimeError("EXECUTOR_TENANT_ID is missing from agentsafe/.env.")
    bundles = _bundle_list(org_id)
    home_rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))["rules"]
    expected_by_id = {rule["rule_id"]: rule for rule in home_rules}
    already = next((bundle for bundle in bundles if bundle.get("version") == POLICY_VERSION), None)
    if already is not None:
        found_by_id = {
            rule.get("rule_id"): rule
            for rule in already.get("rules", [])
            if isinstance(rule, dict)
        }
        if all(found_by_id.get(rule_id) == rule for rule_id, rule in expected_by_id.items()) \
                and EXPECTED_COMMERCE_RULES <= set(found_by_id):
            _record_home_binding(org_id, already["bundle_id"])
            print("Home-to-org policy binding recorded locally; no tenant values were printed.")
            print(f"Already published: version={POLICY_VERSION}; rules={len(found_by_id)}")
            return 0
        raise RuntimeError("This immutable policy version already exists with different rules; bump the source version.")

    current = next((bundle for bundle in bundles if bundle.get("version") == "commerce-policy-v1"), None)
    if current is None:
        raise RuntimeError("Expected active commerce-policy-v1 bundle not found; no policy was published.")
    if len(bundles) != 1:
        raise RuntimeError("Unexpected additional bundles exist; inspect active policy before publishing.")
    candidate = build_candidate(current, org_id)
    validation_status, validation = _request("POST", "/v1/policies/validate", body=candidate)
    if validation_status != 200 or validation.get("valid") is not True:
        details = validation.get("errors")
        raise RuntimeError(f"Decionis rejected the policy candidate: {json.dumps(details)}")
    print(
        f"VALIDATED version={POLICY_VERSION} rules={len(candidate['rules'])} "
        f"preserved_commerce_rules={len(EXPECTED_COMMERCE_RULES)}"
    )
    if not publish_now:
        print("DRY RUN; rerun with --publish to submit this version.")
        return 0

    correlation_id = str(uuid4())
    status, result = _request(
        "POST",
        "/v1/protocol/policies/bundles",
        body=candidate,
        idempotency_key=(
            f"homebound-{POLICY_VERSION}-"
            + hashlib.sha256(
                json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()[:16]
        ),
        correlation_id=correlation_id,
    )
    if status not in {200, 201, 202} or result.get("accepted") is not True:
        raise RuntimeError(f"Decionis did not accept the policy bundle (HTTP {status}).")
    published = _bundle_list(org_id)
    active = next((bundle for bundle in published if bundle.get("version") == POLICY_VERSION), None)
    if active is None:
        raise RuntimeError("Decionis accepted the bundle but it is not visible in the org policy list.")
    found = {rule.get("rule_id") for rule in active.get("rules", []) if isinstance(rule, dict)}
    expected = {rule["rule_id"] for rule in json.loads(RULES_PATH.read_text())["rules"]}
    if not expected <= found or not EXPECTED_COMMERCE_RULES <= found:
        raise RuntimeError("Published bundle verification failed; expected rules are missing.")
    _record_home_binding(org_id, active["bundle_id"])
    print("Home-to-org policy binding recorded locally; no tenant values were printed.")
    print(
        f"PUBLISHED version={POLICY_VERSION} rules={len(found)} "
        f"homebound_rules={len(expected)} preserved_commerce_rules={len(EXPECTED_COMMERCE_RULES)}"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true", help="submit the validated bundle to Decionis")
    args = parser.parse_args()
    try:
        raise SystemExit(publish(publish_now=args.publish))
    except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
