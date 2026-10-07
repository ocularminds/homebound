"""AWS transports preserve source events and never treat delivery as device authorization."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import uuid4

from app.ambient.models import AmbientEvent, CanvasError, validate_command
from app.ambient.supervisor import validate_planning_context, validate_routed_event

LOGGER = logging.getLogger("homebound.ambient")


class EventBridgePublisher:
    """boto3 uses eventbridgev2; the current CLI calls this service eventsv2."""

    def __init__(self, client: Any, bus_arn: str) -> None:
        self.client, self.bus_arn = client, bus_arn

    def publish(self, event: AmbientEvent) -> str:
        event.validate()
        result = self.client.put_raw_events(
            EventBusArn=self.bus_arn,
            Entries=[
                {
                    "Data": json.dumps(event.public_envelope()).encode(),
                    "SystemMetadata": {
                        "ContentType": "application/json",
                        "EventGroupId": event.home_id,
                        "DeduplicationId": event.id,
                    },
                }
            ],
        )
        entries = result.get("Entries", [])
        if (
            result.get("FailedEntryCount") != 0
            or len(entries) != 1
            or entries[0].get("SuccessCode") not in {"PUBLISHED", "DEDUPLICATED"}
        ):
            raise CanvasError(
                "EVENT_NOT_ACCEPTED",
                "EventBridge did not accept the signal. No delivery has been confirmed.",
                503,
            )
        return entries[0]["SuccessCode"]


def invoke_json(
    client: Any, runtime_arn: str, payload: dict[str, Any], session_id: str
) -> dict[str, Any]:
    response = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        runtimeSessionId=session_id,
        qualifier="canvas",
        contentType="application/json",
        accept="application/json",
        payload=json.dumps(payload).encode(),
    )
    stream = response.get("response")
    try:
        if (
            response.get("statusCode") != 200
            or response.get("contentType", "").split(";")[0] != "application/json"
            or stream is None
        ):
            raise CanvasError(
                "SUPERVISOR_UNAVAILABLE", "The supervisor returned no usable result.", 503
            )
        raw = stream.read(64001)
        if len(raw) > 64000:
            raise CanvasError("INVALID_PLAN", "The supervisor result is too large.", 503)
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise CanvasError("INVALID_PLAN", "The supervisor result is invalid.", 503)
        return result
    finally:
        if stream is not None:
            stream.close()


class AgentCorePlanner:
    def __init__(self, client: Any, runtime_arn: str) -> None:
        self.client, self.runtime_arn = client, runtime_arn

    async def plan(self, message: str, context: dict[str, Any]) -> dict[str, str]:
        context = validate_planning_context(context)
        result = await asyncio.wait_for(
            asyncio.to_thread(
                invoke_json,
                self.client,
                self.runtime_arn,
                {"operation": "plan", "message": message, "context": context},
                str(uuid4()),
            ),
            timeout=60,
        )
        if set(result) != {"command"}:
            raise CanvasError("INVALID_PLAN", "The supervisor did not return a valid proposal.")
        return validate_command(result["command"])


class SqsCanvasConsumer:
    def __init__(self, client: Any, queue_url: str) -> None:
        self.client, self.queue_url = client, queue_url

    async def poll_once(self, engine: Any) -> int:
        response = await asyncio.to_thread(
            self.client.receive_message,
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=5,
            VisibilityTimeout=30,
        )
        completed = 0
        for message in response.get("Messages", []):
            try:
                raw = message["Body"]
                if not isinstance(raw, str) or len(raw) > 64000:
                    raise CanvasError("INVALID_ROUTE", "The routed event is too large.")
                event = validate_routed_event(json.loads(raw))
                try:
                    await engine.event(event)
                except CanvasError as error:
                    if error.code != "STALE_EVENT":
                        raise
                    # Expired observations are intentionally discarded, never replayed.
                await asyncio.to_thread(
                    self.client.delete_message,
                    QueueUrl=self.queue_url,
                    ReceiptHandle=message["ReceiptHandle"],
                )
                completed += 1
            except Exception as error:
                LOGGER.warning(
                    "canvas event retained for retry error_type=%s", type(error).__name__
                )
        return completed

    async def run(self, engine: Any) -> None:
        while True:
            try:
                await self.poll_once(engine)
            except Exception as error:
                LOGGER.warning(
                    "canvas event connection unavailable error_type=%s", type(error).__name__
                )
                await asyncio.sleep(5)
