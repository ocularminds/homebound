"""Specialist agents return bounded data. None owns hardware or payment credentials."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.ambient.catalog import INGREDIENTS, PEOPLE, PRODUCTS, RECIPES, SCENES


class ContextAgent:
    """Deterministic audience policy runs before retrieval, inference and rendering."""

    @staticmethod
    def audience(state: dict[str, Any], now: float) -> dict[str, Any]:
        presence = state["presence"]
        fresh = 0 <= now - presence["observed_at"] < 300
        people = presence["people"] if fresh else []
        private = not fresh or presence["guest"] or len(people) != 1
        return {
            "people": people,
            "names": [PEOPLE[p] for p in people],
            "guest": presence["guest"] if fresh else False,
            "private": private,
            "fresh": fresh,
        }

    def eligible(
        self, notes: list[dict[str, Any]], state: dict[str, Any], now: float
    ) -> list[dict[str, Any]]:
        audience = self.audience(state, now)
        if not audience["fresh"] or not audience["people"]:
            return []
        return [
            note
            for note in notes
            if note["expires_at"] > now
            and not note["dismissed"]
            and note["screening"] != "held"
            and (
                note["recipient"] == "household"
                or (not audience["private"] and set(audience["people"]) == {note["recipient"]})
            )
        ]


class MediaAgent:
    """Playback events, not model guesses or timers, decide when content resumes."""

    @staticmethod
    def view(state: dict[str, Any], now: float) -> dict[str, Any]:
        media = state["media"]
        on_break = media["phase"] == "break" and now < media["break_until"]
        return {
            **deepcopy(SCENES[media["scene"]]),
            "phase": "break" if on_break else "program",
            "dashboard": bool(on_break and state["auto_dashboard"]),
            "muted": media["muted"],
            "captions": media["captions"],
            "playback_id": media["playback_id"],
        }

    @staticmethod
    def reading_plan() -> list[dict[str, Any]]:
        return [
            {
                "capability": "media.search",
                "target": "living_room_tv",
                "value": "live_game",
                "label": "Keep the game on",
            },
            {
                "capability": "media.set_volume",
                "target": "living_room_tv",
                "value": 0,
                "label": "Mute TV audio",
            },
            {
                "capability": "media.set_captions",
                "target": "living_room_tv",
                "value": True,
                "label": "Turn captions on",
            },
            {
                "capability": "home.lighting.level",
                "target": "tv_area",
                "value": 20,
                "label": "Dim the TV area to 20%",
            },
            {
                "capability": "home.lighting.level",
                "target": "reading_lamp",
                "value": 85,
                "label": "Brighten the reading lamp to 85%",
            },
        ]


class ShoppingAgent:
    """Join known scene metadata, inventory and offers. Never synthesize a checkout."""

    @staticmethod
    def recipes(state: dict[str, Any], now: float) -> list[dict[str, Any]]:
        inventory = state["inventory"]
        fresh = 0 <= now - inventory["observed_at"] < 86400
        available = set(inventory["available"]) if fresh else set()
        result = []
        for recipe in RECIPES.values():
            missing = [i for i in recipe["ingredients"] if i not in available]
            result.append(
                {
                    **recipe,
                    "ingredients": [
                        {"id": i, "name": INGREDIENTS[i], "available": i in available}
                        for i in recipe["ingredients"]
                    ],
                    "missing": missing,
                    "inventory_fresh": fresh,
                    "ready": fresh and not missing,
                }
            )
        return sorted(result, key=lambda r: (not r["ready"], len(r["missing"])))

    @staticmethod
    def items(state: dict[str, Any]) -> list[dict[str, Any]]:
        return [deepcopy(PRODUCTS[key]) for key in SCENES[state["media"]["scene"]]["items"]]

    @staticmethod
    def cart(state: dict[str, Any]) -> dict[str, Any]:
        items = [{**PRODUCTS[key], "quantity": quantity} for key, quantity in state["cart"].items()]
        return {
            "items": items,
            "total_minor": sum(item["price_minor"] * item["quantity"] for item in items),
            "currency": "EUR",
            "checkout_available": False,
            "status": "draft",
            "source": "demo_catalog",
        }
