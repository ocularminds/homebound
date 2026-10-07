"""AWS transport contracts use botocore Stubber or explicit in-memory service fixtures."""

from __future__ import annotations

from copy import deepcopy
import io
import json
from uuid import uuid4

import boto3
from botocore.stub import Stubber
import httpx2
import pytest

from app.ambient.aws import EventBridgePublisher, SqsCanvasConsumer, invoke_json
from app.ambient.aws_worker import process_batch
from app.ambient.models import AmbientEvent, CanvasError
from app.ambient.runtime import create_runtime_app
from app.ambient.safety import OverlaySafety
from app.ambient.supervisor import route_event, validate_routed_event
from tests.test_ambient_canvas import Clock, Planner, engine


def event():
    return AmbientEvent(
        str(uuid4()),
        "ring-simulator",
        "presence",
        1,
        Clock.now,
        {"people": ["leo"], "guest": False},
    )


@pytest.mark.parametrize("code", ["PUBLISHED", "DEDUPLICATED"])
def test_v2_publisher_preserves_raw_event_and_checks_entry_results(code):
    client = boto3.client(
        "eventbridgev2",
        region_name="us-east-1",
        aws_access_key_id="fixture",
        aws_secret_access_key="fixture",
    )
    stub = Stubber(client)
    signal = event()
    bus = "arn:aws:events:us-east-1:123456789012:event-busv2/home/" + "a" * 25
    stub.add_response(
        "put_raw_events",
        {"FailedEntryCount": 0, "Entries": [{"SuccessCode": code}]},
        {
            "EventBusArn": bus,
            "Entries": [
                {
                    "Data": json.dumps(signal.public_envelope()).encode(),
                    "SystemMetadata": {
                        "ContentType": "application/json",
                        "EventGroupId": "local-home",
                        "DeduplicationId": signal.id,
                    },
                }
            ],
        },
    )
    with stub:
        assert EventBridgePublisher(client, bus).publish(signal) == code
    stub.assert_no_pending_responses()


@pytest.mark.parametrize(
    "response",
    [
        {"FailedEntryCount": 1, "Entries": [{"ErrorCode": "InternalFailure"}]},
        {"Entries": []},
        {"FailedEntryCount": 0, "Entries": [{}]},
    ],
)
def test_publish_http_success_does_not_hide_entry_failure(response):
    class Client:
        def put_raw_events(self, **_kwargs):
            return response

    with pytest.raises(CanvasError, match="did not accept"):
        EventBridgePublisher(Client(), "test-bus").publish(event())


class Runtime:
    def __init__(self):
        self.calls = []
        self.tamper = False

    def invoke_agent_runtime(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["qualifier"] == "canvas"
        body = json.loads(kwargs["payload"])
        result = route_event(body["event"], Clock.now)
        if self.tamper:
            result["event"]["data"]["guest"] = True
        return {
            "statusCode": 200,
            "contentType": "application/json",
            "response": io.BytesIO(json.dumps(result).encode()),
        }


class Queue:
    def __init__(self):
        self.sent = []
        self.deleted = []
        self.messages = []

    def send_message(self, **kwargs):
        self.sent.append(kwargs)

    def receive_message(self, **kwargs):
        assert kwargs["WaitTimeSeconds"] == 5
        return {"Messages": self.messages}

    def delete_message(self, **kwargs):
        self.deleted.append(kwargs)


def test_worker_preserves_source_and_reuses_delivery_deduplication():
    runtime, queue, signal = Runtime(), Queue(), event()
    records = [{"messageId": "1", "body": json.dumps(signal.public_envelope())}]
    assert process_batch(records, runtime, queue, "runtime", "out") == {"batchItemFailures": []}
    assert queue.sent[0]["MessageDeduplicationId"] == signal.id
    assert validate_routed_event(json.loads(queue.sent[0]["MessageBody"])) == signal


def test_worker_retains_tampered_event_and_later_fifo_records():
    runtime, queue = Runtime(), Queue()
    runtime.tamper = True
    records = [{"messageId": str(i), "body": json.dumps(event().public_envelope())} for i in (1, 2)]
    assert process_batch(records, runtime, queue, "runtime", "out")["batchItemFailures"] == [
        {"itemIdentifier": "1"},
        {"itemIdentifier": "2"},
    ]
    assert not queue.sent and len(runtime.calls) == 1


@pytest.mark.asyncio
async def test_receiver_commits_before_delete_and_recalculates_privacy_from_current_state():
    canvas, clock = engine()
    queue, signal = Queue(), event()
    routed = route_event(signal.public_envelope(), clock())
    routed["hint"] = {"private": False, "html": "do not trust advisory hints"}
    queue.messages = [{"Body": json.dumps(routed), "ReceiptHandle": "receipt"}]
    consumer = SqsCanvasConsumer(queue, "out")
    assert await consumer.poll_once(canvas) == 1
    assert len(queue.deleted) == 1
    assert (await canvas.snapshot())["notes"][0]["recipient"] == "leo"
    await canvas.simulate(str(uuid4()), "presence", "guest")
    assert await consumer.poll_once(canvas) == 1
    assert not (await canvas.snapshot())["notes"]


@pytest.mark.asyncio
async def test_receiver_keeps_malformed_or_mismatched_messages_for_dlq():
    canvas, _ = engine()
    queue = Queue()
    routed = route_event(event().public_envelope(), Clock.now)
    routed["event_hash"] = "changed"
    queue.messages = [{"Body": json.dumps(routed), "ReceiptHandle": "receipt"}]
    assert await SqsCanvasConsumer(queue, "out").poll_once(canvas) == 0
    assert not queue.deleted and not (await canvas.snapshot())["notes"]


def test_agentcore_closes_stream_and_rejects_invalid_media_type():
    stream = io.BytesIO(b"private result")

    class Client:
        def invoke_agent_runtime(self, **_kwargs):
            return {"statusCode": 200, "contentType": "text/html", "response": stream}

    with pytest.raises(CanvasError):
        invoke_json(Client(), "runtime", {}, str(uuid4()))
    assert stream.closed


@pytest.mark.asyncio
async def test_agentcore_http_protocol_rejects_tool_blocks_and_private_context():
    canvas, _ = engine()
    planner = Planner()
    app = create_runtime_app(planner, OverlaySafety())
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://runtime"
    ) as http:
        assert (await http.get("/ping")).json() == {"status": "Healthy"}
        context = await canvas.planning_context()
        bad = await http.post(
            "/invocations",
            json={
                "operation": "plan",
                "message": {"toolUse": {"name": "unlockDoor"}},
                "context": context,
            },
        )
        assert bad.status_code == 400
        bad = await http.post(
            "/invocations",
            json={
                "operation": "plan",
                "message": "Leave a note",
                "context": {**context, "notes": ["private note"]},
            },
        )
        assert bad.status_code == 400 and not planner.calls
        good = await http.post(
            "/invocations",
            json={
                "operation": "plan",
                "message": "Tell Mom I took the dog out",
                "context": context,
            },
        )
        assert good.status_code == 200 and good.json()["command"]["intent"] == "note"
        signal = event()
        response = await http.post(
            "/invocations", json={"operation": "event", "event": signal.public_envelope()}
        )
        assert response.status_code == 200 and response.json()["agent"] == "Context"


@pytest.mark.asyncio
async def test_runtime_requires_guardrails_for_user_text_but_can_route_structured_events():
    canvas, _ = engine()
    planner = Planner()
    app = create_runtime_app(planner, OverlaySafety(required=True))
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://runtime"
    ) as http:
        response = await http.post(
            "/invocations",
            json={
                "operation": "plan",
                "message": "Tell Mom I took the dog out",
                "context": await canvas.planning_context(),
            },
        )
        assert response.status_code == 422 and not planner.calls
        response = await http.post(
            "/invocations", json={"operation": "event", "event": event().public_envelope()}
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_saved_local_notes_are_held_when_a_published_guardrail_is_required():
    canvas, _ = engine()
    from app.ambient.engine import CanvasService

    await CanvasService(canvas, Planner()).converse(str(uuid4()), "Tell Mom I took the dog out")
    await canvas.simulate(str(uuid4()), "presence", "mom")
    assert len((await canvas.snapshot())["notes"]) == 2
    canvas.safety = OverlaySafety(lambda: None, "configured-guardrail", "2")
    notes = (await canvas.snapshot())["notes"]
    assert len(notes) == 1 and notes[0]["screening"] == "demo_fixture"


def test_route_rejects_changed_event_and_invalid_protocol_version():
    routed = route_event(event().public_envelope(), Clock.now)
    changed = deepcopy(routed)
    changed["event"]["data"]["people"] = ["mom"]
    with pytest.raises(CanvasError):
        validate_routed_event(changed)
    changed = deepcopy(routed)
    changed["event"]["version"] = True
    with pytest.raises(CanvasError):
        validate_routed_event(changed)
