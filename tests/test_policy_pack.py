from pathlib import Path

import yaml


PACK_PATH = Path(__file__).parents[1] / "policies" / "homebound-household-zero-trust.yaml"


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
    assert "local_time > '15:00'" in courier["decision"]
    assert "ALLOW IF parameters.context_signals.actor == 'delivery-agent'" in courier["decision"]
    assert "parameters.context_signals.delivery_expected == true" in courier["decision"]
    assert "parameters.context_signals.courier_recognized == true" in courier["decision"]
    assert "unlock_duration_seconds == 30" in courier["decision"]


def test_homebound_pack_has_no_vendor_specific_device_actions() -> None:
    source = PACK_PATH.read_text(encoding="utf-8").lower()

    assert "ring." not in source
    assert "alexa" not in source
