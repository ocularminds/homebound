import json
from pathlib import Path

import yaml


PACK_PATH = Path(__file__).parents[1] / "policies" / "homebound-household-zero-trust.yaml"
RULES_PATH = Path(__file__).parents[1] / "policies" / "homebound-household-policy.rules.json"


def test_homebound_exchange_pack_has_required_catalog_shape() -> None:
    pack = yaml.safe_load(PACK_PATH.read_text(encoding="utf-8"))

    assert pack["apiVersion"] == "decionis.dev/v1"
    assert pack["kind"] == "PolicyPack"
    assert pack["metadata"]["name"] == PACK_PATH.stem
    assert pack["metadata"]["surface"] == "home"
    assert pack["defaults"]["mode"] == "shadow"
    assert pack["defaults"]["emit_dossier"] is True
    assert {rule["name"] for rule in pack["rules"]} == {
        "govern_security_disarm",
        "govern_side_gate_courier_unlock",
    }


def test_household_rules_encode_escalate_allow_and_wrong_time_block() -> None:
    pack = yaml.safe_load(PACK_PATH.read_text(encoding="utf-8"))
    security = next(rule for rule in pack["rules"] if rule["name"] == "govern_security_disarm")
    courier = next(rule for rule in pack["rules"] if rule["name"] == "govern_side_gate_courier_unlock")

    assert "ESCALATE IF parameters.context_signals.user == 'child'" in security["decision"]
    assert "ALLOW IF parameters.context_signals.authenticated_user_role == 'parent'" in security[
        "decision"
    ]
    assert "BLOCK IF parameters.context_signals.actor == 'delivery-agent'" in courier[
        "decision"
    ]
    assert "local_time < '14:00'" in courier["decision"]
    assert "local_time > '18:00'" in courier["decision"]
    assert "ALLOW IF parameters.context_signals.actor == 'delivery-agent'" in courier["decision"]
    assert "parameters.context_signals.delivery_expected == true" in courier["decision"]
    assert "parameters.context_signals.courier_recognized == true" in courier["decision"]
    assert "parameters.context_signals.recognition_source == 'camera'" in courier[
        "decision"
    ]
    assert "parameters.context_signals.household_confirmation == true" in courier[
        "decision"
    ]
    assert "local_time <= '18:00'" in courier["decision"]
    assert "unlock_duration_seconds == 30" in courier["decision"]


def test_homebound_pack_has_no_vendor_specific_device_actions() -> None:
    source = PACK_PATH.read_text(encoding="utf-8").lower()

    assert "ring." not in source
    assert "alexa" not in source


def test_protocol_draft_keeps_owner_inputs_separate_from_public_pack() -> None:
    document = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    contract = document["metadata"]["home_context_contract"]
    assert document["status"] == "VERSIONED_PROTOCOL_RULES_TEMPLATE"
    assert contract["parent_roster_source"] == (
        "Owner-managed parent email and role in HomeBound or Decionis workspace"
    )
    assert contract["presence_role"] == "APPROVER"
    assert contract["courier_recognition_source"] == "camera"
    assert contract["voice_confirmation"] == "household_confirmation"
    assert contract["default_delivery_window_local"] == {
        "start": "14:00",
        "end": "18:00",
    }
    assert "new org-scoped Decionis Protocol policy version" in contract["owner_override"]


def test_protocol_rules_match_agentsafe_intent_shape_and_numeric_local_time() -> None:
    document = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    assert len(document["rules"]) == 5
    by_id = {rule["rule_id"]: rule for rule in document["rules"]}

    parent_override = by_id["homebound.authenticated-parent-disarm-allow"]
    assert parent_override["enabled"] is False
    child = by_id["homebound.child-disarm-escalation"]
    assert child["enabled"] is True
    assert child["then"]["action"] == "ESCALATE"
    assert child["then"]["authority"]["selector"]["role_id"] == "APPROVER"

    valid = by_id["homebound.courier-unlock-in-window"]["when"]["all"]
    predicates = {item["field"]: item for item in valid}
    assert predicates["context.agent_safe.action.type"]["value"] == "home.entry.unlock"
    assert predicates["context.agent_safe.action.resource"]["value"] == "side_gate"
    time_predicates = [
        item
        for item in valid
        if item["field"].endswith("local_time_minutes")
    ]
    assert {(item["operator"], item["value"]) for item in time_predicates} == {
        ("GTE", 840),
        ("LTE", 1080),
    }

    outside = by_id["homebound.courier-unlock-outside-window"]["when"]["all"]
    assert any(
        item["field"].endswith("local_time_minutes")
        and item["operator"] == "GT"
        and item["value"] == 1080
        for item in outside
    )
    before = by_id["homebound.courier-unlock-before-window"]["when"]["all"]
    assert any(
        item["field"].endswith("local_time_minutes")
        and item["operator"] == "LT"
        and item["value"] == 840
        for item in before
    )
