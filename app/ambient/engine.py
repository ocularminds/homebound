"""Shared-home ambient state, with privacy-safe projections and durable replay checks."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import time
from typing import Any, Callable
from uuid import uuid4

from app.ambient.agents import ContextAgent, MediaAgent, ShoppingAgent
from app.ambient.catalog import PEOPLE, PRODUCTS, RECIPES, SCENES
from app.ambient.models import (
    AmbientEvent,
    CanvasError,
    fingerprint,
    validate_command,
    validate_note_request,
)
from app.ambient.safety import OverlaySafety
from app.ambient.store import CanvasStore


class CanvasEngine:
    def __init__(
        self, store: CanvasStore, safety: OverlaySafety, clock: Callable[[], float] = time.time
    ) -> None:
        self.store, self.safety, self.clock = store, safety, clock
        self.context, self.media, self.shopping = ContextAgent(), MediaAgent(), ShoppingAgent()
        self.lock = asyncio.Lock()
        self._simulation_lock = asyncio.Lock()
        self.runtime_mode = "deployment_required"
        self.events_mode = "local"

    def _cached(self, identifier: str, digest: str) -> str | None:
        receipt = self.store.receipt(identifier)
        if receipt and receipt[0] != digest:
            raise CanvasError(
                "EVENT_ID_REUSED",
                "This request identifier was already used for different content.",
                409,
            )
        return receipt[1] if receipt else None

    async def cached(self, identifier: str, digest: str) -> str | None:
        async with self.lock:
            return self._cached(identifier, digest)

    @staticmethod
    def _trace(state: dict[str, Any], agent: str, outcome: str) -> None:
        state["revision"] += 1
        state["trace"] = [
            {"agent": agent, "outcome": outcome, "revision": state["revision"]},
            *state["trace"],
        ][:8]

    async def snapshot(self) -> dict[str, Any]:
        async with self.lock:
            now, state = self.clock(), self.store.load()
            audience = self.context.audience(state, now)
            media = self.media.view(state, now)
            eligible = self.context.eligible(
                [note for note in self.store.notes(now) if self.safety.allows_saved(note)],
                state,
                now,
            )
            focused = media["attention"] == "focused" and media["phase"] == "program"
            notes = (
                []
                if focused
                else [
                    {
                        key: note[key]
                        for key in ("id", "recipient", "text", "sender", "created_at", "screening")
                    }
                    for note in eligible[:2]
                ]
            )
            panel = state["panel"]
            # Stale and guest audiences never receive hidden note text, including in traces.
            result = {
                "revision": state["revision"],
                "media": media,
                "audience": audience,
                "notes": notes,
                "note_waiting": bool(focused and eligible),
                "layout": "dashboard" if media["dashboard"] else "quiet" if focused else "ambient",
                "panel": panel,
                "recipes": self.shopping.recipes(state, now) if panel == "recipes" else [],
                "products": self.shopping.items(state) if panel == "shopping" else [],
                "cart": self.shopping.cart(state),
                "room": state["room"],
                "plan": state["plan"],
                "auto_dashboard": state["auto_dashboard"],
                "trace": state["trace"],
                "capabilities": {
                    "mode": "local_simulation",
                    "signals": "simulated",
                    "screening": self.safety.mode,
                    "payments": "not_connected",
                    "room_execution": "preview_only",
                    "ring_video": "not_connected",
                    "agentcore": self.runtime_mode,
                    "eventbridge": self.events_mode,
                },
            }
            # Expiry changes a projection without a mutation; clients compare this too.
            result["projection"] = fingerprint(result)
            result["generated_at"] = now
            return result

    async def planning_context(self) -> dict[str, Any]:
        async with self.lock:
            state, now = self.store.load(), self.clock()
            # No personal notes, raw presence events or historic utterances enter inference.
            return {
                "scene": deepcopy(SCENES[state["media"]["scene"]]),
                "playback_id": state["media"]["playback_id"],
                "panel": state["panel"],
                "cart_products": list(state["cart"]),
                "inventory_fresh": 0 <= now - state["inventory"]["observed_at"] < 86400,
            }

    async def event(
        self,
        event: AmbientEvent,
        *,
        request_digest: str | None = None,
        expected_playback_id: str | None = None,
    ) -> str:
        event.validate()
        digest = request_digest or fingerprint(event.public_envelope())
        async with self.lock:
            cached = self._cached(event.id, digest)
            if cached is not None:
                return cached
            now, state = self.clock(), self.store.load()
            # A browser player reports only the session it loaded. In particular,
            # an old ad's "ended" callback must not restore an unrelated program.
            if expected_playback_id and state["media"]["playback_id"] != expected_playback_id:
                with self.store.db:
                    self.store.remember(event.id, digest, "ignored", now)
                return "ignored"
            if not -5 <= now - event.observed_at <= 300:
                raise CanvasError(
                    "STALE_EVENT", "The ambient signal is stale or from the future.", 409
                )
            cursor = state["sequences"].get(event.source, {"sequence": 0, "observed_at": 0})
            outcome = "ignored"
            with self.store.db:
                if (
                    event.sequence > cursor["sequence"]
                    and event.observed_at >= cursor["observed_at"]
                ):
                    data = event.data
                    if event.kind == "presence":
                        state["presence"] = {**data, "observed_at": event.observed_at}
                        self._trace(
                            state, "Context", "Audience changed; display privacy recalculated."
                        )
                        outcome = "applied"
                    elif event.kind == "inventory":
                        state["inventory"] = {**data, "observed_at": event.observed_at}
                        self._trace(state, "Shopping", "Pantry snapshot refreshed.")
                        outcome = "applied"
                    else:
                        current = state["media"]
                        same = data["playback_id"] == current["playback_id"]
                        # A late break cannot replace a newly selected program.
                        if (same and data["scene"] == current["scene"]) or (
                            not same and data["phase"] == "program"
                        ):
                            current.update(
                                scene=data["scene"],
                                playback_id=data["playback_id"],
                                phase=data["phase"],
                                break_until=event.observed_at + 90
                                if data["phase"] == "break"
                                else 0,
                            )
                            if not same:
                                state["panel"] = None
                            if data["phase"] == "break" and state["auto_dashboard"]:
                                state["panel"] = None
                            self._trace(
                                state,
                                "Media",
                                "Break dashboard requested."
                                if data["phase"] == "break"
                                else "Program in view.",
                            )
                            outcome = "applied"
                    state["sequences"][event.source] = {
                        "sequence": event.sequence,
                        "observed_at": event.observed_at,
                    }
                    self.store.save(state)
                self.store.remember(event.id, digest, outcome, now)
            return outcome

    async def simulate(self, identifier: str, kind: str, value: Any) -> str:
        """Browser input selects fixtures. It cannot claim a trusted Ring/Alexa identity."""
        async with self._simulation_lock:
            return await self._simulate(identifier, kind, value)

    async def playback(self, identifier: str, playback_id: str, phase: str) -> str:
        """Report a local video transition, bound to its selected playback session."""
        if phase not in {"program", "break"}:
            raise CanvasError("INVALID_PLAYBACK", "Choose a program or commercial transition.")
        async with self._simulation_lock:
            async with self.lock:
                state, now = self.store.load(), self.clock()
                sequence = state["sequences"].get("firetv-simulator", {"sequence": 0})[
                    "sequence"
                ] + 1
            return await self.event(
                AmbientEvent(
                    identifier,
                    "firetv-simulator",
                    "media",
                    sequence,
                    now,
                    {"scene": "park_chase", "playback_id": playback_id, "phase": phase},
                ),
                request_digest=fingerprint(["local-player", playback_id, phase]),
                expected_playback_id=playback_id,
            )

    async def _simulate(self, identifier: str, kind: str, value: Any) -> str:
        # Serialize fixture construction with state changes, then let event own validation.
        async with self.lock:
            state, now = self.store.load(), self.clock()
            if (
                kind == "presence"
                and isinstance(value, str)
                and value in {*PEOPLE, "guest", "empty", "family"}
            ):
                people = (
                    [value]
                    if value in PEOPLE
                    else list(PEOPLE)
                    if value == "family"
                    else state["presence"]["people"]
                    if value == "guest"
                    else []
                )
                source, event_kind, data = (
                    "ring-simulator",
                    "presence",
                    {"people": people, "guest": value == "guest"},
                )
            elif kind == "scene" and isinstance(value, str) and value in SCENES:
                source, event_kind, data = (
                    "firetv-simulator",
                    "media",
                    {"scene": value, "playback_id": str(uuid4()), "phase": "program"},
                )
            elif kind == "phase" and isinstance(value, str) and value in {"program", "break"}:
                source, event_kind, data = (
                    "firetv-simulator",
                    "media",
                    {
                        "scene": state["media"]["scene"],
                        "playback_id": state["media"]["playback_id"],
                        "phase": value,
                    },
                )
            elif kind == "inventory" and isinstance(value, list):
                source, event_kind, data = "pantry-simulator", "inventory", {"available": value}
            else:
                raise CanvasError("INVALID_SIMULATION", "Choose an available demo signal.")
            sequence = state["sequences"].get(source, {"sequence": 0})["sequence"] + 1
        return await self.event(
            AmbientEvent(identifier, source, event_kind, sequence, now, data),
            request_digest=fingerprint(["simulation", kind, value]),
        )

    async def execute(
        self,
        identifier: str,
        digest: str,
        command: dict[str, str],
        *,
        screening: str = "held",
        playback_id: str | None = None,
    ) -> str:
        command = validate_command(command)
        async with self.lock:
            cached = self._cached(identifier, digest)
            if cached is not None:
                return cached
            now, state = self.clock(), self.store.load()
            intent = command["intent"]
            if (
                intent in {"identify", "cart_add"}
                and playback_id
                and playback_id != state["media"]["playback_id"]
            ):
                raise CanvasError(
                    "SCENE_CHANGED",
                    "The program changed while I was looking. Ask again about what's on now.",
                    409,
                )
            with self.store.db:
                if intent == "note":
                    if screening == "held":
                        return "I kept that note off the TV because its content could not be safely screened. Try a simple household reminder."
                    if (
                        len(
                            [
                                n
                                for n in self.store.notes(now)
                                if n["expires_at"] > now and not n["dismissed"]
                            ]
                        )
                        >= 50
                    ):
                        raise CanvasError(
                            "MEMORY_FULL",
                            "The note board is full. Dismiss a note before adding another.",
                            409,
                        )
                    self.store.put_note(
                        {
                            "id": identifier,
                            "recipient": command["recipient"],
                            "text": command["text"].strip(),
                            "sender": "You",
                            "created_at": now,
                            "expires_at": now + 86400,
                            "dismissed": False,
                            "screening": screening,
                            "policy_stamp": self.safety.policy_stamp,
                        }
                    )
                    name = PEOPLE.get(command["recipient"], "the household")
                    reply = f"I've left a note for {name}. It will appear when the audience and the moment are right."
                    agent, outcome = (
                        "Context",
                        "A screened note was saved with an audience restriction.",
                    )
                elif intent in {"identify", "recipes"}:
                    scene = SCENES[state["media"]["scene"]]
                    if (
                        intent == "identify"
                        and command["product"] in PRODUCTS
                        and command["product"] not in scene["items"]
                    ):
                        raise CanvasError(
                            "ITEM_NOT_IN_SCENE",
                            "I couldn't match that item to the current scene. Try asking about what's on screen.",
                        )
                    state["panel"] = (
                        "recipes" if intent == "recipes" or scene["recipe"] else "shopping"
                    )
                    if state["panel"] == "recipes":
                        reply = "I've matched the recipe ideas with the demo pantry. The TV shows what you have and what's missing."
                    elif scene["items"]:
                        reply = "I've put a similar style on the TV from the demo catalog. You can review it before adding it to your draft cart."
                    else:
                        state["panel"] = None
                        reply = "This program has no item metadata to identify. Try the cooking show or movie in Demo signals."
                    agent, outcome = (
                        "Shopping",
                        "Scene metadata and inventory were cross-referenced.",
                    )
                elif intent == "cart_add":
                    product = command["product"]
                    if product == "missing":
                        if not 0 <= now - state["inventory"]["observed_at"] < 86400:
                            raise CanvasError(
                                "STALE_INVENTORY",
                                "Refresh the pantry before adding missing ingredients.",
                                409,
                            )
                        recipe = RECIPES[SCENES[state["media"]["scene"]]["recipe"] or "lemon_pasta"]
                        missing = set(recipe["ingredients"]) - set(state["inventory"]["available"])
                        selected = [
                            key for key, item in PRODUCTS.items() if item["ingredient"] in missing
                        ]
                    elif product == "scene":
                        selected = SCENES[state["media"]["scene"]]["items"]
                    else:
                        selected = [product] if product in PRODUCTS else []
                    if not selected:
                        reply = (
                            "There isn't a matching demo item to add. Nothing changed in the cart."
                        )
                    else:
                        for key in selected:
                            state["cart"][key] = min(9, state["cart"].get(key, 0) + 1)
                        reply = "Added to your draft cart. No purchase has been made."
                    state["panel"] = "cart"
                    agent, outcome = "Shopping", "Draft cart reviewed; no payment submitted."
                elif intent in {"checkout", "cart_clear"}:
                    if intent == "cart_clear":
                        state["cart"] = {}
                    state["panel"] = "cart"
                    reply = (
                        "Your draft cart is empty."
                        if intent == "cart_clear"
                        else "Your draft cart is on the TV. Amazon Pay is not connected, so no order has been placed."
                    )
                    agent, outcome = "Shopping", "Draft cart reviewed; no payment submitted."
                elif intent == "reading":
                    if state["restore"] is None:
                        state["restore"] = {
                            "media": deepcopy(state["media"]),
                            "room": deepcopy(state["room"]),
                        }
                    state["media"].update(
                        scene="game",
                        playback_id=str(uuid4()),
                        muted=True,
                        captions=True,
                        phase="program",
                        break_until=0,
                    )
                    state["room"] = {"tv_area": 20, "reading_lamp": 85, "mode": "reading"}
                    state["plan"], state["panel"] = self.media.reading_plan(), "room"
                    reply = "Reading mode is previewed on the TV: game on, sound muted, captions on, and lighting set for a book. Physical room controls aren't connected."
                    agent, outcome = (
                        "Media",
                        "Five bounded steps previewed; physical execution not requested.",
                    )
                elif intent == "restore":
                    previous = state["restore"]
                    if previous:
                        state.update(previous)
                        state["media"].update(
                            playback_id=str(uuid4()), phase="program", break_until=0
                        )
                    state.update(restore=None, plan=[], panel=None)
                    reply = (
                        "The canvas preview is back to its previous room settings."
                        if previous
                        else "There isn't a previous room preview to restore."
                    )
                    agent, outcome = "Media", "Room preview restored."
                elif intent == "dashboard":
                    state["auto_dashboard"] = not state["auto_dashboard"]
                    reply = (
                        "The home dashboard will appear during signalled breaks."
                        if state["auto_dashboard"]
                        else "Automatic break dashboards are off."
                    )
                    agent, outcome = "Media", "Break dashboard preference changed."
                elif intent == "dismiss":
                    state["panel"] = None
                    reply, agent, outcome = "Back to your program.", "Media", "Canvas panel closed."
                else:
                    # Do not display arbitrary unscreened model prose on a shared display.
                    reply = "I can leave a note, find recipe ideas, show a scene item, or preview reading mode. What would you like?"
                    agent, outcome = "Supervisor", "A clearer canvas request is needed."
                self._trace(state, agent, outcome)
                self.store.save(state)
                self.store.remember(identifier, digest, reply, now)
            return reply

    async def dismiss_note(self, identifier: str) -> None:
        async with self.lock:
            now, state = self.clock(), self.store.load()
            eligible = self.context.eligible(
                [note for note in self.store.notes(now) if self.safety.allows_saved(note)],
                state,
                now,
            )
            note = next((n for n in eligible if n["id"] == identifier), None)
            if note is None:
                raise CanvasError(
                    "NOTE_UNAVAILABLE", "That note is no longer available to this audience.", 404
                )
            with self.store.db:
                note["dismissed"] = True
                self.store.put_note(note)
                self._trace(state, "Context", "An eligible note was dismissed.")
                self.store.save(state)


class CanvasService:
    def __init__(self, engine: CanvasEngine, planner: Any = None) -> None:
        self.engine, self.planner = engine, planner
        self._conversation_lock = asyncio.Lock()
        self.consumer: Any = None

    async def converse(self, identifier: str, message: str) -> str:
        digest = fingerprint(["canvas-conversation", message])
        async with self._conversation_lock:
            cached = await self.engine.cached(identifier, digest)
            if cached is not None:
                return cached
            if await self.engine.safety.screen(message, "INPUT") == "held":
                return "I kept that request off the shared screen because it could not be safely screened. Try a simple household reminder."
            if self.planner is None:
                raise CanvasError(
                    "BEDROCK_UNAVAILABLE",
                    "The canvas assistant is not configured. Demo signals are still available.",
                    503,
                )
            context = await self.engine.planning_context()
            command = validate_command(await self.planner.plan(message, context))
            screening = "held"
            if command["intent"] == "note":
                validate_note_request(command, message)
                screening = await self.engine.safety.screen(command["text"])
            return await self.engine.execute(
                identifier, digest, command, screening=screening, playback_id=context["playback_id"]
            )

    async def action(self, identifier: str, intent: str, product: str = "unknown") -> str:
        if intent not in {
            "identify",
            "recipes",
            "cart_add",
            "cart_clear",
            "checkout",
            "reading",
            "restore",
            "dashboard",
            "dismiss",
        }:
            raise CanvasError("INVALID_ACTION", "Choose an available canvas action.")
        command = {
            "intent": intent,
            "recipient": "unknown",
            "text": "",
            "product": product,
            "reply": "",
        }
        return await self.engine.execute(
            identifier, fingerprint(["canvas-action", command]), command
        )
