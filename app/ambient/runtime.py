"""AgentCore HTTP contract: /ping and /invocations on port 8080, behind IAM auth."""

from __future__ import annotations

import json
import os
import time
from typing import Any

import boto3
from botocore.config import Config
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.ambient.bedrock import BedrockCanvasPlanner
from app.ambient.models import CanvasError, validate_command, validate_note_request
from app.ambient.safety import OverlaySafety
from app.ambient.supervisor import route_event, validate_planning_context


def create_runtime_app(planner: Any, safety: OverlaySafety) -> Starlette:
    async def ping(_request: Request):
        return JSONResponse({"status": "Healthy"})

    async def invocations(request: Request):
        try:
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 16000:
                    raise CanvasError("REQUEST_TOO_LARGE", "The invocation is too large.", 413)
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise CanvasError("INVALID_REQUEST", "The invocation must be an object.")
            if value.get("operation") == "event" and set(value) == {"operation", "event"}:
                return JSONResponse(route_event(value["event"], time.time()))
            if value.get("operation") != "plan" or set(value) != {
                "operation",
                "message",
                "context",
            }:
                raise CanvasError("INVALID_REQUEST", "Choose a supported invocation.")
            message = value["message"]
            if not isinstance(message, str) or not 1 <= len(message.strip()) <= 2000:
                raise CanvasError("INVALID_REQUEST", "The message must be plain text.")
            context = validate_planning_context(value["context"])
            if await safety.screen(message, "INPUT") == "held":
                raise CanvasError("CONTENT_HELD", "The request could not be safely screened.", 422)
            command = validate_command(await planner.plan(message, context))
            if command["intent"] == "note":
                validate_note_request(command, message)
                if await safety.screen(command["text"]) == "held":
                    raise CanvasError("CONTENT_HELD", "The note could not be safely screened.", 422)
            return JSONResponse({"command": command})
        except CanvasError as error:
            return JSONResponse(
                {"error": error.code, "message": error.message}, status_code=error.status
            )
        except (ValueError, UnicodeError, TypeError):
            return JSONResponse({"error": "INVALID_REQUEST"}, status_code=400)
        except Exception:
            # No payloads, provider diagnostics, or Guardrails assessments in logs.
            return JSONResponse({"error": "SUPERVISOR_UNAVAILABLE"}, status_code=503)

    return Starlette(
        routes=[Route("/ping", ping), Route("/invocations", invocations, methods=["POST"])]
    )


def build_app() -> Starlette:
    def runtime():
        return boto3.Session(region_name=os.getenv("AWS_REGION", "us-east-1")).client(
            "bedrock-runtime",
            config=Config(
                connect_timeout=5,
                read_timeout=40,
                retries={"total_max_attempts": 2, "mode": "adaptive"},
            ),
        )

    return create_runtime_app(
        BedrockCanvasPlanner(runtime, os.getenv("BEDROCK_MODEL_ID", "")),
        OverlaySafety(
            runtime,
            os.getenv("HOMEBOUND_CANVAS_GUARDRAIL_ID", ""),
            os.getenv("HOMEBOUND_CANVAS_GUARDRAIL_VERSION", ""),
            required=True,
        ),
    )


app = build_app()
