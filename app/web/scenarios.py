"""Fixed demo context, never identity evidence or an authority decision."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from typing import Any
from zoneinfo import ZoneInfo


SCENARIOS: dict[str, dict[str, Any]] = {
    "everyday": {
        "title": "Everyday at home",
        "description": "Ask about your home. No household identity is assumed.",
        "time": "Home-local time",
        "request": "What can you help me with?",
    },
    "child": {
        "title": "Kids home alone",
        "description": "A child wants to disarm the home security system.",
        "time": "15:00",
        "request": "Alexa, disarm the Ring system.",
        "tool": "disarmSystem",
        "arguments": {
            "target": "home_security",
            "reason": "home-alone child requested disarm",
            "context_signals": {
                "user": "child",
                "time": "15:00",
                "location": "home",
                "device_group": "security_infrastructure",
            },
            "parameters": {},
        },
    },
    "courier": {
        "title": "An expected delivery",
        "description": "A recognized courier arrives during the delivery window.",
        "time": "16:00",
        "request": "Alexa, yes, open the side gate for the expected courier.",
        "tool": "unlockDoor",
        "arguments": {
            "target": "side_gate",
            "purpose": "expected high-value courier delivery",
            "context_signals": {
                "actor": "delivery-agent",
                "delivery_expected": True,
                "courier_recognized": True,
                "recognition_source": "camera",
                "household_confirmation": True,
                "local_time": "16:00",
                "local_time_minutes": 960,
            },
            "parameters": {"unlock_duration_seconds": 30},
        },
    },
    "late_courier": {
        "title": "A delivery after hours",
        "description": "The same courier arrives outside the delivery window.",
        "time": "18:01",
        "request": "Alexa, yes, let the expected courier through the side gate after hours.",
        "tool": "unlockDoor",
        "arguments": {
            "target": "side_gate",
            "purpose": "expected high-value courier delivery",
            "context_signals": {
                "actor": "delivery-agent",
                "delivery_expected": True,
                "courier_recognized": True,
                "recognition_source": "camera",
                "household_confirmation": True,
                "local_time": "18:01",
                "local_time_minutes": 1081,
            },
            "parameters": {"unlock_duration_seconds": 30},
        },
    },
}

HOME_TOOLS = frozenset({"unlockDoor", "disarmSystem", "viewStream"})
TARGETS = {"unlockDoor": "side_gate", "disarmSystem": "home_security", "viewStream": "front_door"}


def same_json(left: Any, right: Any) -> bool:
    """Unlike Python equality, keep booleans, integers, and floats distinct."""
    try:
        return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(
            right, sort_keys=True, allow_nan=False
        )
    except (TypeError, ValueError):
        return False


def public_scenarios() -> list[dict[str, str]]:
    return [
        {"id": key, **{name: item[name] for name in ("title", "description", "time", "request")}}
        for key, item in SCENARIOS.items()
    ]


def captured_context(scenario_id: str, home_timezone: str) -> dict[str, Any]:
    scenario = SCENARIOS[scenario_id]
    if "arguments" in scenario:
        return deepcopy(scenario["arguments"]["context_signals"])
    now = datetime.now(ZoneInfo(home_timezone))
    return {
        "local_time": now.strftime("%H:%M"),
        "local_time_minutes": now.hour * 60 + now.minute,
        "signal_source": "web_simulator_clock",
    }


def home_tool_schemas(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Describe the known scene fields directly instead of asking for JSON strings."""
    scalar_types = {bool: "boolean", int: "integer", str: "string"}
    context_schema = {
        "type": "object",
        "properties": {
            name: {
                "type": scalar_types[type(value)],
                "description": f"Captured scene value: {json.dumps(value)}. Copy exactly.",
            }
            for name, value in context.items()
        },
        "required": list(context),
    }
    schemas = {}
    for name in HOME_TOOLS:
        purpose_field = "reason" if name == "disarmSystem" else "purpose"
        device_fields = (
            {"unlock_duration_seconds": {"type": "integer", "description": "Must be 30."}}
            if name == "unlockDoor"
            else {}
        )
        schemas[name] = {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": f"Use {TARGETS[name]}."},
                purpose_field: {"type": "string", "description": "The reason for this request."},
                "context_signals": deepcopy(context_schema),
                "parameters": {
                    "type": "object",
                    "properties": device_fields,
                    "required": list(device_fields),
                },
            },
            "required": ["target", purpose_field, "context_signals", "parameters"],
        }
    return schemas


def valid_home_call(name: str, arguments: dict[str, Any], context: dict[str, Any]) -> bool:
    if name not in HOME_TOOLS or not isinstance(arguments, dict):
        return False
    purpose_field = "reason" if name == "disarmSystem" else "purpose"
    if set(arguments) - {"target", purpose_field, "context_signals", "parameters"}:
        return False
    if arguments.get("target") != TARGETS[name] or not same_json(
        arguments.get("context_signals"), context
    ):
        return False
    purpose = arguments.get(purpose_field)
    if not isinstance(purpose, str) or not 1 <= len(purpose.strip()) <= 500:
        return False
    required_parameters = {"unlock_duration_seconds": 30} if name == "unlockDoor" else {}
    return same_json(arguments.get("parameters", {}), required_parameters)
