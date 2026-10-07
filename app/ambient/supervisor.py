"""Typed agent routing for asynchronous events; no model on the playback-critical path."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.ambient.agents import ContextAgent, MediaAgent, ShoppingAgent
from app.ambient.catalog import PRODUCTS, SCENES
from app.ambient.models import AmbientEvent, CanvasError, fingerprint
from app.ambient.store import initial_state

AGENTS = {"presence": "Context", "media": "Media", "inventory": "Shopping"}
UI_INTENTS = {
    "presence": "recompute_notes",
    "media": "adapt_playback",
    "inventory": "refresh_recipes",
}


def event_from_wire(value: Any) -> AmbientEvent:
    if not isinstance(value, dict) or set(value) != {
        "id",
        "source",
        "kind",
        "sequence",
        "observed_at",
        "data",
        "home_id",
        "version",
    }:
        raise CanvasError("INVALID_EVENT", "The event envelope is invalid.")
    event = AmbientEvent(**value)
    event.validate()
    return event


def route_event(value: Any, now: float) -> dict[str, Any]:
    event = event_from_wire(value)
    preview = initial_state(now)
    if event.kind == "presence":
        preview["presence"] = {**event.data, "observed_at": event.observed_at}
        hint = {"private": ContextAgent.audience(preview, now)["private"]}
    elif event.kind == "media":
        preview["media"].update(**event.data, break_until=event.observed_at + 90)
        hint = {"dashboard": MediaAgent.view(preview, now)["dashboard"]}
    else:
        preview["inventory"] = {**event.data, "observed_at": event.observed_at}
        hint = {
            "ready_recipes": [r["id"] for r in ShoppingAgent.recipes(preview, now) if r["ready"]]
        }
    return {
        "version": 1,
        "event_id": event.id,
        "event_hash": fingerprint(value),
        "agent": AGENTS[event.kind],
        "ui_intent": UI_INTENTS[event.kind],
        "hint": hint,
        "event": value,
    }


def validate_routed_event(value: Any) -> AmbientEvent:
    if not isinstance(value, dict) or set(value) != {
        "version",
        "event_id",
        "event_hash",
        "agent",
        "ui_intent",
        "hint",
        "event",
    }:
        raise CanvasError("INVALID_ROUTE", "The routed event is invalid.")
    event = event_from_wire(value["event"])
    if (
        type(value["version"]) is not int
        or value["version"] != 1
        or value["event_id"] != event.id
        or value["event_hash"] != fingerprint(value["event"])
        or value["agent"] != AGENTS[event.kind]
        or value["ui_intent"] != UI_INTENTS[event.kind]
    ):
        raise CanvasError("INVALID_ROUTE", "The routed event does not match its source.")
    # Hints are advisory only. The receiver always recalculates the current audience.
    return event


def validate_planning_context(value: Any) -> dict[str, Any]:
    fields = {"scene", "playback_id", "panel", "cart_products", "inventory_fresh"}
    if not isinstance(value, dict) or set(value) != fields:
        raise CanvasError("INVALID_CONTEXT", "Only the public canvas context is accepted.")
    scene = value["scene"]
    if (
        not isinstance(scene, dict)
        or not isinstance(scene.get("id"), str)
        or scene["id"] not in SCENES
        or scene != SCENES[scene["id"]]
    ):
        raise CanvasError("INVALID_CONTEXT", "The scene is not in the configured catalog.")
    if (
        not isinstance(value["playback_id"], str)
        or len(value["playback_id"]) > 64
        or not value["playback_id"]
    ):
        raise CanvasError("INVALID_CONTEXT", "Invalid playback context.")
    if value["panel"] is not None and (
        not isinstance(value["panel"], str)
        or value["panel"] not in {"recipes", "shopping", "cart", "room"}
    ):
        raise CanvasError("INVALID_CONTEXT", "Invalid panel context.")
    products = value["cart_products"]
    if (
        not isinstance(products, list)
        or len(products) > len(PRODUCTS)
        or any(not isinstance(p, str) or p not in PRODUCTS for p in products)
        or type(value["inventory_fresh"]) is not bool
    ):
        raise CanvasError("INVALID_CONTEXT", "Invalid inventory context.")
    return deepcopy(value)
