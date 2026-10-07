"""Local-only HTTP API and static frontend; no Ring execution credentials."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import UUID

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from app.config.settings import Settings
from app.ambient.catalog import SCENES as CANVAS_SCENES
from app.ambient.engine import CanvasEngine, CanvasService
from app.ambient.models import CanvasError
from app.ambient.safety import OverlaySafety
from app.ambient.store import CanvasStore
from app.web.assistant import Conversation, WebAssistant, WebError
from app.web.conversation import DialogueContext, home_greeting
from app.web.escalations import approval_snapshot
from app.web.scenarios import SCENARIOS, public_scenarios
from app.web.settings import WebSettings
from app.web.voice import DeepgramVoice, MAX_AUDIO_BYTES, VoiceError

LOGGER = logging.getLogger("homebound.web")
STATIC_DIRECTORY = Path(__file__).parent / "static"
SESSION_COOKIE = "homebound_web_session"


class LocalBrowserBoundary:
    """Reject DNS rebinding and cross-origin mutation of the localhost assistant."""

    def __init__(self, app: Any, port: int) -> None:
        self.app = app
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        host = headers.get(b"host", b"").decode("latin-1").lower()
        origin = headers.get(b"origin", b"").decode("latin-1")
        cross_site = headers.get(b"sec-fetch-site") == b"cross-site"
        expected_origin = f"{scope.get('scheme', 'http')}://{host}"
        if host not in self.hosts or cross_site or (origin and origin != expected_origin):
            await JSONResponse(
                {"error": "ORIGIN_REJECTED", "message": "Open the simulator on its local address."},
                status_code=403,
            )(scope, receive, send)
            return
        if scope["method"] not in {"GET", "HEAD"} and headers.get(b"x-homebound-client") != b"web":
            await JSONResponse(
                {
                    "error": "CLIENT_HEADER_REQUIRED",
                    "message": "Use the local simulator interface.",
                },
                status_code=403,
            )(scope, receive, send)
            return

        async def secured_send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"permissions-policy", b"microphone=(self), camera=(), geolocation=()"),
                    (
                        b"content-security-policy",
                        b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                    ),
                ]
            await send(message)

        await self.app(scope, receive, secured_send)


class Conversations:
    def __init__(self) -> None:
        self.items: dict[str, Conversation] = {}

    def get(self, supplied: str | None) -> tuple[str, Conversation]:
        now = time.monotonic()
        for key, item in list(self.items.items()):
            if now - item.touched > 3600 and not item.lock.locked():
                self.items.pop(key)
        if supplied in self.items:
            session = self.items[supplied]
            session.touched = now
            return supplied, session  # type: ignore[return-value]
        if len(self.items) >= 64:
            raise WebError(
                "SESSION_LIMIT",
                "The simulator has too many open conversations. Try again later.",
                503,
            )
        key = secrets.token_urlsafe(32)
        session = self.items[key] = Conversation()
        return key, session


async def bounded_body(request: Request, limit: int) -> bytes:
    try:
        declared = int(request.headers.get("content-length", "0"))
    except ValueError:
        raise WebError("INVALID_LENGTH", "Invalid request size.") from None
    if declared < 0 or declared > limit:
        raise WebError("REQUEST_TOO_LARGE", "This request is too large.", 413)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise WebError("REQUEST_TOO_LARGE", "This request is too large.", 413)
    return bytes(body)


async def json_body(request: Request, fields: set[str]) -> dict[str, Any]:
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise WebError("JSON_REQUIRED", "Send a JSON request.", 415)
    try:
        body = json.loads(await bounded_body(request, 16_000))
    except (ValueError, UnicodeDecodeError):
        raise WebError("INVALID_JSON", "The request is not valid JSON.") from None
    if not isinstance(body, dict) or set(body) - fields:
        raise WebError("INVALID_REQUEST", "The request contains unsupported fields.")
    return body


def request_id(body: dict[str, Any]) -> str:
    value = body.get("request_id")
    try:
        if not isinstance(value, str):
            raise ValueError
        UUID(value)
    except ValueError:
        raise WebError("INVALID_REQUEST_ID", "A request identifier is required.") from None
    return value


def create_asgi_app(
    settings: Settings,
    web_settings: WebSettings,
    assistant: WebAssistant,
    voice: DeepgramVoice | None = None,
) -> Any:
    if settings.homebound_environment == "production":
        raise ValueError("The Alexa web simulator is a local development interface.")
    sessions = Conversations()
    voice = voice or DeepgramVoice(web_settings)
    if assistant.canvas is None:
        assistant.canvas = CanvasService(
            CanvasEngine(CanvasStore(":memory:", time.time()), OverlaySafety())
        )
    canvas = assistant.canvas

    def api(
        handler: Callable[[Request, Conversation], Awaitable[Response]],
    ) -> Callable[[Request], Awaitable[Response]]:
        async def wrapped(request: Request) -> Response:
            key = None
            try:
                key, session = sessions.get(request.cookies.get(SESSION_COOKIE))
                response = await handler(request, session)
            except (WebError, VoiceError, CanvasError) as error:
                response = JSONResponse(
                    {"error": error.code, "message": error.message}, status_code=error.status
                )
            except Exception as error:
                LOGGER.warning("web request failed error_type=%s", type(error).__name__)
                response = JSONResponse(
                    {
                        "error": "SERVICE_UNAVAILABLE",
                        "message": "The request could not be completed. Check the local service configuration.",
                    },
                    status_code=503,
                )
            if key:
                response.set_cookie(
                    SESSION_COOKIE,
                    key,
                    max_age=3600,
                    httponly=True,
                    samesite="strict",
                    secure=request.url.scheme == "https",
                )
            return response

        return wrapped

    async def bootstrap(_request: Request, session: Conversation) -> Response:
        return JSONResponse(
            {
                "assistant_configured": bool(settings.bedrock_model_id),
                "voice_configured": web_settings.voice_configured,
                "voice_provider": "Deepgram",
                "home_timezone": web_settings.home_timezone,
                "greeting": home_greeting(web_settings.home_timezone),
                "dialogue": session.dialogue.public(),
                "scenarios": public_scenarios(),
                "turns": session.turns,
                "activity": session.activity,
                "device_state": session.device_state,
                "pending": list(session.pending),
                "approvals": approval_snapshot(session.pending),
                "busy": session.lock.locked(),
            }
        )

    async def chat(request: Request, session: Conversation) -> Response:
        body = await json_body(request, {"request_id", "message", "scenario_id"})
        identifier = request_id(body)
        message = body.get("message")
        scenario_id = body.get("scenario_id", "conversation")
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 2000:
            raise WebError("MESSAGE_INVALID", "Use a request between 1 and 2,000 characters.")
        if not isinstance(scenario_id, str) or scenario_id not in {*SCENARIOS, "conversation", "canvas"}:
            raise WebError("SCENARIO_INVALID", "Select one of the available demo scenes.")
        return JSONResponse(await assistant.chat(session, identifier, message.strip(), scenario_id))

    async def resume(request: Request, session: Conversation) -> Response:
        body = await json_body(request, {"request_id", "correlation_id", "automatic"})
        identifier = request_id(body)
        correlation = body.get("correlation_id")
        if not isinstance(correlation, str) or not 1 <= len(correlation) <= 256:
            raise WebError("CORRELATION_INVALID", "Choose a pending request to check.")
        automatic = body.get("automatic", False)
        if type(automatic) is not bool:
            raise WebError("INVALID_REQUEST", "Automatic must be a boolean.")
        return JSONResponse(await assistant.resume(session, identifier, correlation, automatic=automatic))

    async def clear(_request: Request, session: Conversation) -> Response:
        if session.lock.locked():
            raise WebError("REQUEST_IN_PROGRESS", "Wait for the current request to finish.", 409)
        session.history.clear()
        session.turns.clear()
        session.dialogue = DialogueContext()
        # Keep pending handoffs and deduplication records when clearing visible chat.
        return JSONResponse({"cleared": True})

    async def transcribe(request: Request, _session: Conversation) -> Response:
        audio = await bounded_body(request, MAX_AUDIO_BYTES)
        transcript = await voice.transcribe(audio, request.headers.get("content-type", ""))
        return JSONResponse({"transcript": transcript})

    async def speak(request: Request, session: Conversation) -> Response:
        body = await json_body(request, {"request_id"})
        identifier = request_id(body)
        cached = session.replies.get(identifier)
        if cached is None:
            raise WebError(
                "REPLY_NOT_FOUND", "This reply is no longer available for playback.", 404
            )
        audio = await voice.speak(cached[1].get("speech_text", cached[1]["reply"]))
        return Response(audio, media_type="audio/mpeg")

    async def greet(request: Request, _session: Conversation) -> Response:
        await json_body(request, set())
        # Server-selected text only; the browser cannot turn this into arbitrary TTS.
        audio = await voice.speak(home_greeting(web_settings.home_timezone)["text"])
        return Response(audio, media_type="audio/mpeg")

    async def index(_request: Request) -> Response:
        return FileResponse(STATIC_DIRECTORY / "index.html")

    async def television(_request: Request) -> Response:
        return FileResponse(STATIC_DIRECTORY / "tv.html")

    async def canvas_payload() -> dict[str, Any]:
        payload = {
            **await canvas.engine.snapshot(),
            "voice_configured": web_settings.voice_configured,
            "home_timezone": web_settings.home_timezone,
        }
        stream = CANVAS_SCENES["park_chase"]["stream"]
        media_paths = [stream["src"], stream["poster"], stream["captions"]]
        media_paths += [item["src"] for item in stream["breaks"]]
        def available_asset(path: str) -> bool:
            asset = STATIC_DIRECTORY / path.removeprefix("/static/")
            try:
                return asset.is_file() and asset.stat().st_size > 0
            except OSError:
                return False

        available = all(available_asset(path) for path in media_paths)
        payload["programs"] = {"park_chase": {"available": available}}
        if payload["media"].get("stream"):
            payload["media"]["stream"]["available"] = available
        return payload

    async def canvas_state(_request: Request, _session: Conversation) -> Response:
        return JSONResponse(await canvas_payload())

    async def canvas_simulate(request: Request, _session: Conversation) -> Response:
        body = await json_body(request, {"request_id", "kind", "value"})
        await canvas.engine.simulate(request_id(body), body.get("kind"), body.get("value"))
        return JSONResponse(await canvas_payload())

    async def canvas_action(request: Request, _session: Conversation) -> Response:
        body = await json_body(request, {"request_id", "intent", "product"})
        intent, product = body.get("intent"), body.get("product", "unknown")
        if not isinstance(intent, str) or not isinstance(product, str):
            raise CanvasError("INVALID_ACTION", "Choose an available canvas action.")
        reply = await canvas.action(request_id(body), intent, product)
        return JSONResponse({"reply": reply, "canvas": await canvas_payload()})

    async def canvas_playback(request: Request, _session: Conversation) -> Response:
        body = await json_body(request, {"request_id", "playback_id", "phase"})
        playback_id, phase = body.get("playback_id"), body.get("phase")
        if not isinstance(playback_id, str) or not isinstance(phase, str):
            raise CanvasError("INVALID_PLAYBACK", "Choose an active video session.")
        await canvas.engine.playback(request_id(body), playback_id, phase)
        return JSONResponse(await canvas_payload())

    async def canvas_dismiss(request: Request, _session: Conversation) -> Response:
        body = await json_body(request, {"note_id"})
        if not isinstance(body.get("note_id"), str) or len(body["note_id"]) > 64:
            raise CanvasError("INVALID_NOTE", "Choose a visible note.")
        await canvas.engine.dismiss_note(body["note_id"])
        return JSONResponse(await canvas_payload())

    async def health(_request: Request) -> Response:
        return JSONResponse({"status": "ok", "service": "homebound-web"})

    @asynccontextmanager
    async def lifespan(_application: Starlette):
        consumer = (
            asyncio.create_task(canvas.consumer.run(canvas.engine)) if canvas.consumer else None
        )
        try:
            yield
        finally:
            if consumer:
                consumer.cancel()
                with suppress(asyncio.CancelledError):
                    await consumer
            canvas.engine.store.close()

    application = Starlette(
        lifespan=lifespan,
        routes=[
            Route("/", index),
            Route("/tv", television),
            Route("/healthz", health),
            Route("/api/bootstrap", api(bootstrap)),
            Route("/api/canvas", api(canvas_state)),
            Route("/api/canvas/simulate", api(canvas_simulate), methods=["POST"]),
            Route("/api/canvas/playback", api(canvas_playback), methods=["POST"]),
            Route("/api/canvas/action", api(canvas_action), methods=["POST"]),
            Route("/api/canvas/dismiss", api(canvas_dismiss), methods=["POST"]),
            Route("/api/chat", api(chat), methods=["POST"]),
            Route("/api/resume", api(resume), methods=["POST"]),
            Route("/api/clear", api(clear), methods=["POST"]),
            Route("/api/voice/transcribe", api(transcribe), methods=["POST"]),
            Route("/api/voice/speak", api(speak), methods=["POST"]),
            Route("/api/voice/greeting", api(greet), methods=["POST"]),
            Mount("/static", StaticFiles(directory=STATIC_DIRECTORY), name="static"),
        ]
    )
    return LocalBrowserBoundary(application, web_settings.port)
