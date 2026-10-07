"""The ambient UI shares a home, while localhost and conversation boundaries remain intact."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.ambient.engine import CanvasService
from app.web.assistant import Conversation, WebAssistant
from app.web.server import create_asgi_app
from app.web.settings import WebSettings
from tests.test_ambient_canvas import Planner, engine
from tests.test_web import client, settings
from tests.test_web_conversation import facts


def application():
    config, web = settings(), WebSettings()
    canvas, _ = engine()
    service = CanvasService(canvas, Planner())
    assistant = WebAssistant(config, web, lambda: None, canvas=service)
    return create_asgi_app(config, web, assistant)


@pytest.mark.asyncio
async def test_tv_routes_are_packaged_and_share_only_filtered_canvas_data():
    app = application()
    async with client(app) as first, client(app) as second:
        page = await first.get("/tv")
        assert page.status_code == 200 and "FireTV canvas" in page.text
        for path in (
            "/static/tv.js",
            "/static/tv.css",
            "/static/scene-coast.svg",
            "/static/frame-cooking.png",
        ):
            assert (await first.get(path)).status_code == 200
        request = {"request_id": str(uuid4()), "kind": "presence", "value": "leo"}
        response = await first.post("/api/canvas/simulate", json=request)
        assert response.status_code == 200 and response.json()["notes"]
        assert (await second.get("/api/canvas")).json()["notes"][0]["recipient"] == "leo"
        assert (await first.post("/api/canvas/simulate", json=request)).status_code == 200
        response = await second.post(
            "/api/canvas/simulate", json={**request, "request_id": str(uuid4()), "value": "guest"}
        )
        assert response.json()["notes"] == []
        snapshot = await first.get("/api/canvas")
        assert "math homework" not in snapshot.text
        assert "turns" not in snapshot.json() and "history" not in snapshot.json()


@pytest.mark.asyncio
async def test_browser_cannot_inject_sensor_provenance_or_a_payment_action():
    async with client(application()) as http:
        response = await http.post(
            "/api/canvas/simulate",
            json={"request_id": str(uuid4()), "kind": "presence", "value": "leo", "trusted": True},
        )
        assert response.status_code == 400
        response = await http.post(
            "/api/canvas/action",
            json={"request_id": str(uuid4()), "intent": "buy", "product": "field_jacket"},
        )
        assert response.status_code == 400
        response = await http.post(
            "/api/canvas/action",
            json={"request_id": str(uuid4()), "intent": "reading"},
            headers={"Origin": "https://untrusted.invalid"},
        )
        assert response.status_code == 403
        assert not (await http.get("/api/canvas")).json()["plan"]


@pytest.mark.asyncio
async def test_voice_canvas_reply_is_saved_for_existing_tts_contract():
    async with client(application()) as http:
        body = {
            "request_id": str(uuid4()),
            "message": "Tell Mom I took the dog out",
            "scenario_id": "canvas",
        }
        response = await http.post("/api/chat", json=body)
        assert response.status_code == 200
        turn = response.json()
        assert turn["id"] == body["request_id"] and "left a note" in turn["reply"]
        assert turn["trace"] == []
        assert (await http.post("/api/chat", json=body)).json() == turn
        reused = await http.post("/api/chat", json={**body, "message": "Something else"})
        assert reused.status_code == 409


@pytest.mark.asyncio
async def test_alexa_topic_change_cannot_reuse_old_gate_confirmation():
    class Agent:
        async def interpret_conversation(self, _prompt, _schema):
            return facts(intent="canvas")

    canvas, _ = engine()
    assistant = WebAssistant(
        settings(), WebSettings(), Agent, canvas=CanvasService(canvas, Planner())
    )
    session = Conversation()
    session.dialogue.action = "unlockDoor"
    session.dialogue.visitor = "delivery"
    session.dialogue.awaiting = "expected"
    turn = await assistant.chat(
        session, str(uuid4()), "Tell Mom I took the dog out", "conversation"
    )
    assert "left a note" in turn["reply"]
    assert session.dialogue.action is None and session.dialogue.awaiting is None
