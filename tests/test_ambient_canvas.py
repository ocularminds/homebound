"""Ambient privacy and lifecycle tests. External services are explicit fixtures."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.ambient.bedrock import BedrockCanvasPlanner
from app.ambient.engine import CanvasEngine, CanvasService
from app.ambient.models import AmbientEvent, CanvasError, fingerprint, validate_command
from app.ambient.safety import OverlaySafety
from app.ambient.store import CanvasStore


class Clock:
    now = 1800000000.0

    def __call__(self):
        return self.now


def engine(path: str = ":memory:", safety=None):
    clock = Clock()
    return CanvasEngine(CanvasStore(path, clock()), safety or OverlaySafety(), clock), clock


def command(intent="note", **values):
    return {
        "intent": intent,
        "recipient": "mom",
        "text": "I took the dog out",
        "product": "unknown",
        "reply": "",
        **values,
    }


class Planner:
    def __init__(self, result=None):
        self.result = result or command()
        self.calls = []
        self.started = asyncio.Event()
        self.release = None

    async def plan(self, message, context):
        self.calls.append(deepcopy(context))
        self.started.set()
        if self.release:
            await self.release.wait()
        return deepcopy(self.result)


async def presence(canvas, person):
    await canvas.simulate(str(uuid4()), "presence", person)


@pytest.mark.asyncio
async def test_personal_notes_never_reach_guest_unknown_or_other_person_payloads():
    canvas, clock = engine()
    await presence(canvas, "leo")
    assert [n["recipient"] for n in (await canvas.snapshot())["notes"]] == ["leo"]
    assert "math homework" not in json.dumps(await canvas.planning_context())
    for audience in ("guest", "empty", "mom", "family"):
        await presence(canvas, audience)
        payload = json.dumps(await canvas.snapshot())
        assert "math homework" not in payload
        if audience != "mom":
            assert "dog out" not in payload
    await presence(canvas, "leo")
    clock.now += 301
    data = await canvas.snapshot()
    assert data["notes"] == [] and not data["audience"]["fresh"]
    assert "math homework" not in json.dumps(data)


@pytest.mark.asyncio
async def test_focused_program_holds_note_content_until_break_then_resumes():
    canvas, clock = engine()
    await presence(canvas, "mom")
    await canvas.simulate(str(uuid4()), "scene", "movie")
    data = await canvas.snapshot()
    assert data["note_waiting"] is True and data["notes"] == []
    assert "dog out" not in json.dumps(data)
    playback = data["media"]["playback_id"]
    await canvas.simulate(str(uuid4()), "phase", "break")
    data = await canvas.snapshot()
    assert data["media"]["dashboard"] and data["notes"]
    await canvas.simulate(str(uuid4()), "phase", "program")
    data = await canvas.snapshot()
    assert not data["media"]["dashboard"]
    assert data["media"]["playback_id"] == playback
    assert data["note_waiting"] and not data["notes"]
    await canvas.simulate(str(uuid4()), "phase", "break")
    clock.now += 91
    assert not (await canvas.snapshot())["media"]["dashboard"]


@pytest.mark.asyncio
async def test_queued_break_does_not_extend_its_original_lifetime():
    canvas, clock = engine()
    await canvas.simulate(str(uuid4()), "scene", "game")
    data = await canvas.snapshot()
    observed = clock()
    clock.now += 91
    event = AmbientEvent(
        str(uuid4()),
        "firetv-simulator",
        "media",
        2,
        observed,
        {"scene": "game", "playback_id": data["media"]["playback_id"], "phase": "break"},
    )
    await canvas.event(event)
    assert not (await canvas.snapshot())["media"]["dashboard"]


@pytest.mark.asyncio
async def test_event_replays_and_old_breaks_cannot_replace_new_program():
    canvas, clock = engine()
    await canvas.simulate(str(uuid4()), "scene", "game")
    data = await canvas.snapshot()
    old_playback = data["media"]["playback_id"]
    await canvas.simulate(str(uuid4()), "scene", "cooking")
    late = AmbientEvent(
        str(uuid4()),
        "firetv-simulator",
        "media",
        3,
        clock(),
        {"scene": "game", "playback_id": old_playback, "phase": "break"},
    )
    assert await canvas.event(late) == "ignored"
    assert (await canvas.snapshot())["media"]["id"] == "cooking"
    assert await canvas.event(late) == "ignored"
    with pytest.raises(CanvasError, match="different content"):
        await canvas.event(replace(late, data={**late.data, "phase": "program"}))
    older = replace(late, id=str(uuid4()), sequence=1)
    assert await canvas.event(older) == "ignored"


@pytest.mark.asyncio
async def test_fixture_request_retry_is_idempotent_and_survives_restart(tmp_path: Path):
    path = str(tmp_path / "memory.sqlite3")
    canvas, _ = engine(path)
    identifier = str(uuid4())
    assert await canvas.simulate(identifier, "scene", "game") == "applied"
    first = await canvas.snapshot()
    assert await canvas.simulate(identifier, "scene", "game") == "applied"
    assert (await canvas.snapshot())["revision"] == first["revision"]
    canvas.store.close()
    restarted, _ = engine(path)
    assert await restarted.simulate(identifier, "scene", "game") == "applied"
    assert (await restarted.snapshot())["media"]["playback_id"] == first["media"]["playback_id"]
    with pytest.raises(CanvasError):
        await restarted.simulate(identifier, "scene", "coast")


@pytest.mark.asyncio
async def test_replayed_or_stale_presence_cannot_remove_guest_privacy():
    canvas, clock = engine()
    await presence(canvas, "leo")
    await presence(canvas, "guest")
    event = AmbientEvent(
        str(uuid4()), "ring-simulator", "presence", 1, clock(), {"people": ["leo"], "guest": False}
    )
    assert await canvas.event(event) == "ignored"
    assert (await canvas.snapshot())["notes"] == []
    with pytest.raises(CanvasError, match="stale"):
        await canvas.event(replace(event, id=str(uuid4()), sequence=9, observed_at=clock() - 301))
    with pytest.raises(CanvasError):
        await canvas.event(replace(event, id=str(uuid4()), sequence=9, source="verified-ring"))


@pytest.mark.asyncio
async def test_notes_persist_without_replaying_model_and_expire(tmp_path: Path):
    canvas, clock = engine(str(tmp_path / "notes.sqlite3"))
    planner = Planner()
    service = CanvasService(canvas, planner)
    identifier = str(uuid4())
    first = await service.converse(identifier, "Tell Mom I took the dog out")
    assert await service.converse(identifier, "Tell Mom I took the dog out") == first
    assert len(planner.calls) == 1
    assert len(canvas.store.notes(clock())) == 3
    await presence(canvas, "mom")
    assert any(n["id"] == identifier for n in (await canvas.snapshot())["notes"])
    assert all("notes" not in context and "people" not in context for context in planner.calls)
    clock.now += 86401
    await presence(canvas, "mom")
    assert not (await canvas.snapshot())["notes"]


@pytest.mark.asyncio
async def test_shared_note_requires_explicit_household_audience_and_exact_content():
    canvas, _ = engine()
    planner = Planner(command(recipient="household"))
    service = CanvasService(canvas, planner)
    with pytest.raises(CanvasError, match="Who is"):
        await service.converse(str(uuid4()), "Tell Mom I took the dog out")
    planner.result = command(text="The bank account is closed")
    with pytest.raises(CanvasError, match="exact note"):
        await service.converse(str(uuid4()), "Tell Mom I took the dog out")
    planner.result = command(recipient="household")
    await service.converse(str(uuid4()), "Tell everyone I took the dog out")
    await presence(canvas, "mom")
    await presence(canvas, "guest")
    notes = (await canvas.snapshot())["notes"]
    assert len(notes) == 1 and notes[0]["recipient"] == "household"


@pytest.mark.asyncio
async def test_model_cannot_redirect_note_to_a_person_mentioned_in_its_body():
    canvas, _ = engine()
    planner = Planner(command(recipient="leo", text="Leo took the dog out"))
    service = CanvasService(canvas, planner)
    with pytest.raises(CanvasError, match="Who is"):
        await service.converse(str(uuid4()), "Tell Mom Leo took the dog out")
    assert len(canvas.store.notes(Clock.now)) == 2
    planner.result = command(recipient="mom", text="Leo took the dog out")
    await service.converse(str(uuid4()), "Alexa, tell my mum Leo took the dog out")
    await presence(canvas, "mom")
    assert any(n["text"] == "Leo took the dog out" for n in (await canvas.snapshot())["notes"])


@pytest.mark.asyncio
async def test_guest_arrival_is_not_blocked_by_slow_bedrock():
    canvas, _ = engine()
    await presence(canvas, "mom")
    planner = Planner()
    planner.release = asyncio.Event()
    service = CanvasService(canvas, planner)
    job = asyncio.create_task(service.converse(str(uuid4()), "Tell Mom I took the dog out"))
    await planner.started.wait()
    await asyncio.wait_for(presence(canvas, "guest"), timeout=0.2)
    assert not (await canvas.snapshot())["notes"]
    planner.release.set()
    await job
    assert not (await canvas.snapshot())["notes"]


@pytest.mark.asyncio
async def test_scene_changed_during_inference_rejects_stale_cart_selection():
    canvas, _ = engine()
    await canvas.simulate(str(uuid4()), "scene", "movie")
    planner = Planner(command("cart_add", product="scene"))
    planner.release = asyncio.Event()
    service = CanvasService(canvas, planner)
    job = asyncio.create_task(service.converse(str(uuid4()), "Add that jacket to the cart"))
    await planner.started.wait()
    await canvas.simulate(str(uuid4()), "scene", "cooking")
    planner.release.set()
    with pytest.raises(CanvasError, match="program changed"):
        await job
    assert not (await canvas.snapshot())["cart"]["items"]


@pytest.mark.asyncio
async def test_pantry_freshness_and_draft_cart_never_submit_a_purchase():
    canvas, clock = engine()
    service = CanvasService(canvas)
    await canvas.simulate(str(uuid4()), "scene", "cooking")
    await service.action(str(uuid4()), "recipes")
    recipes = {r["id"]: r for r in (await canvas.snapshot())["recipes"]}
    assert recipes["tomato_toast"]["ready"]
    assert recipes["lemon_pasta"]["missing"] == ["olive_oil"]
    await service.action(str(uuid4()), "cart_add", "missing")
    data = await canvas.snapshot()
    assert data["cart"]["items"][0]["id"] == "olive_oil"
    reply = await service.action(str(uuid4()), "checkout")
    assert "no order" in reply.lower() and not data["cart"]["checkout_available"]
    clock.now += 86401
    await service.action(str(uuid4()), "recipes")
    assert not any(r["ready"] for r in (await canvas.snapshot())["recipes"])
    with pytest.raises(CanvasError, match="Refresh the pantry"):
        await service.action(str(uuid4()), "cart_add", "missing")


@pytest.mark.asyncio
async def test_room_preview_is_bounded_and_restore_is_idempotent():
    canvas, _ = engine()
    service = CanvasService(canvas)
    before = await canvas.snapshot()
    await service.action(str(uuid4()), "reading")
    await service.action(str(uuid4()), "reading")
    data = await canvas.snapshot()
    assert data["media"]["id"] == "game" and data["media"]["muted"] and data["media"]["captions"]
    assert len(data["plan"]) == 5
    assert {s["target"] for s in data["plan"]} == {"living_room_tv", "reading_lamp", "tv_area"}
    assert data["capabilities"]["room_execution"] == "preview_only"
    identifier = str(uuid4())
    await service.action(identifier, "restore")
    await service.action(identifier, "restore")
    restored = await canvas.snapshot()
    assert restored["room"] == before["room"] and restored["media"]["id"] == before["media"]["id"]


@pytest.mark.asyncio
async def test_note_dismissal_rechecks_current_audience():
    canvas, _ = engine()
    await presence(canvas, "leo")
    await presence(canvas, "guest")
    with pytest.raises(CanvasError, match="no longer available"):
        await canvas.dismiss_note("demo-leo")
    await presence(canvas, "leo")
    await canvas.dismiss_note("demo-leo")
    assert not (await canvas.snapshot())["notes"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result", [{"action": "GUARDRAIL_INTERVENED"}, {}, RuntimeError("private diagnostics")]
)
async def test_guardrails_interventions_errors_and_malformed_results_hold_notes(result):
    class Runtime:
        def apply_guardrail(self, **kwargs):
            assert kwargs["guardrailVersion"] == "3" and kwargs["source"] == "OUTPUT"
            if isinstance(result, Exception):
                raise result
            return result

    safety = OverlaySafety(lambda: Runtime(), "test-guardrail", "3")
    assert await safety.screen("Dog has been walked") == "held"


@pytest.mark.asyncio
async def test_sensitive_inputs_are_held_before_inference_and_required_guardrail_has_no_fallback():
    canvas, _ = engine()
    planner = Planner()
    service = CanvasService(canvas, planner)
    reply = await service.converse(str(uuid4()), "Tell Mom the password is bananas")
    assert "off the shared screen" in reply and planner.calls == []
    assert await OverlaySafety(required=True).screen("A normal reminder") == "held"
    with pytest.raises(ValueError, match="published"):
        OverlaySafety(lambda: None, "rail", "DRAFT")


@pytest.mark.asyncio
async def test_bedrock_only_gets_one_data_tool_and_bounded_tokens():
    class Runtime:
        def converse(self, **kwargs):
            assert kwargs["inferenceConfig"]["maxTokens"] == 700
            assert [x["toolSpec"]["name"] for x in kwargs["toolConfig"]["tools"]] == [
                "composeCanvas"
            ]
            assert "notes" not in json.loads(kwargs["messages"][0]["content"][0]["text"])["canvas"]
            return {
                "output": {
                    "message": {
                        "content": [{"toolUse": {"name": "composeCanvas", "input": command()}}]
                    }
                }
            }

    canvas, _ = engine()
    planner = BedrockCanvasPlanner(lambda: Runtime(), "model")
    assert (await planner.plan("Tell Mom I took the dog out", await canvas.planning_context()))[
        "intent"
    ] == "note"


@pytest.mark.parametrize(
    "bad",
    [
        command(intent="unlockDoor"),
        command(product="https://shop.invalid"),
        command(text={"script": "alert(1)"}),
        {**command(), "execute": True},
    ],
)
def test_untrusted_plans_have_no_open_ended_actions_or_ui(bad):
    with pytest.raises(CanvasError):
        validate_command(bad)


@pytest.mark.asyncio
async def test_note_event_identifier_reuse_cannot_change_the_recipient():
    canvas, _ = engine()
    identifier = str(uuid4())
    await canvas.execute(
        identifier, fingerprint(command()), command(), screening="local_demo_screening"
    )
    with pytest.raises(CanvasError):
        await canvas.execute(
            identifier,
            fingerprint(command(recipient="leo")),
            command(recipient="leo"),
            screening="local_demo_screening",
        )
