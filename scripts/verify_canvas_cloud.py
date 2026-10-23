"""Exercise the deployed supervisor; --events uses an isolated demo home receiver.

Stop other consumers before --events. It publishes labelled simulator events and
acknowledges them from this stack's output queue. No household notes are loaded.
"""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import time
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.ambient.aws import EventBridgePublisher, SqsCanvasConsumer, invoke_json
from app.ambient.catalog import INGREDIENTS, SCENES
from app.ambient.engine import CanvasEngine
from app.ambient.models import AmbientEvent, CanvasError, validate_command
from app.ambient.safety import OverlaySafety
from app.ambient.store import CanvasStore
from app.ambient.supervisor import validate_routed_event


def require(condition: bool, description: str) -> None:
    if not condition:
        raise RuntimeError(description)


async def verify(args: argparse.Namespace) -> dict:
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    config = Config(connect_timeout=5, read_timeout=90,
                    retries={"total_max_attempts": 2, "mode": "adaptive"})
    stack = session.client("cloudformation", config=config).describe_stacks(
        StackName=args.stack
    )["Stacks"][0]
    require(stack["StackStatus"] in {"CREATE_COMPLETE", "UPDATE_COMPLETE"},
            "The application stack is not complete.")
    outputs = {entry["OutputKey"]: entry["OutputValue"] for entry in stack["Outputs"]}
    report = {"stack": args.stack, "region": args.region, "verified_at": time.time(), "checks": []}

    def passed(name: str, **details) -> None:
        result = {"check": name, "passed": True, **details}
        report["checks"].append(result)
        print(json.dumps(result), flush=True)

    control = session.client("bedrock-agentcore-control", config=config)
    endpoint = control.get_agent_runtime_endpoint(
        agentRuntimeId=outputs["RuntimeId"], endpointName="canvas"
    )
    require(endpoint["status"] == "READY", "The canvas endpoint is not READY.")
    runtime = control.get_agent_runtime(
        agentRuntimeId=outputs["RuntimeId"], agentRuntimeVersion=endpoint["liveVersion"]
    )
    require(runtime["status"] == "READY", "The endpoint runtime version is not READY.")
    require(runtime["networkConfiguration"]["networkMode"] == "VPC", "Runtime is not private.")
    passed("private_runtime_and_endpoint_ready", version=endpoint["liveVersion"])

    logs = session.client("logs", config=config)
    for key in ("RuntimeDefaultLogGroupName", "RuntimeEndpointLogGroupName"):
        groups = [group for page in logs.get_paginator("describe_log_groups").paginate(
            logGroupNamePrefix=outputs[key]
        ) for group in page["logGroups"] if group["logGroupName"] == outputs[key]]
        require(len(groups) == 1 and groups[0].get("kmsKeyId") == outputs["DataKeyArn"]
                and groups[0].get("retentionInDays") == 14, "Platform logs are not configured.")
    passed("platform_logs_encrypted_with_14_day_retention")
    sources = [source for page in logs.get_paginator("describe_delivery_sources").paginate()
               for source in page["deliverySources"]
               if outputs["RuntimeArn"] in source.get("resourceArns", [])]
    require(any(source["logType"] == "USAGE_LOGS" for source in sources), "Usage log delivery is missing.")
    require(all(source["logType"] != "APPLICATION_LOGS" for source in sources),
            "Disable raw invocation payload logging before using the home receiver.")
    passed("usage_telemetry_without_raw_invocation_logging")

    client = session.client("bedrock-agentcore", config=config)
    signal = AmbientEvent(str(uuid4()), "ring-simulator", "presence", 1,
                          time.time(), {"people": ["leo"], "guest": False})
    result = invoke_json(client, outputs["RuntimeArn"],
                         {"operation": "event", "event": signal.public_envelope()}, str(uuid4()))
    require(validate_routed_event(result) == signal, "Runtime altered the source event.")
    passed("typed_event_integrity")

    context = {"scene": deepcopy(SCENES["cooking"]), "playback_id": str(uuid4()),
               "panel": None, "cart_products": [], "inventory_fresh": True}
    started = time.monotonic()
    result = invoke_json(client, outputs["RuntimeArn"], {
        "operation": "plan", "message": "Show me a recipe for this scene", "context": context,
    }, str(uuid4()))
    command = validate_command(result["command"])
    require(command["intent"] == "recipes", "Bedrock did not return the scene recipe intent.")
    passed("bedrock_scene_planning", seconds=round(time.monotonic()-started, 2))

    bedrock = session.client("bedrock-runtime", config=config)
    for name, message, action in (
        ("guardrail_allows_normal_text", "Dinner is ready", "NONE"),
        ("guardrail_blocks_synthetic_email", "Email demo@example.com", "GUARDRAIL_INTERVENED"),
    ):
        result = bedrock.apply_guardrail(
            guardrailIdentifier=outputs["GuardrailId"], guardrailVersion=outputs["GuardrailVersion"],
            source="INPUT", content=[{"text": {"text": message}}], outputScope="INTERVENTIONS",
        )
        require(result.get("action") == action, "Published Guardrails behavior did not match.")
        passed(name)

    if args.events:
        worker = session.client("lambda", config=config).get_event_source_mapping(
            UUID=outputs["ConsumerMappingId"]
        )
        require(worker["State"] == "Enabled", "The FIFO worker is not enabled.")
        sqs = session.client("sqs", config=config)
        for key in ("InputQueueUrl", "OutputQueueUrl"):
            attributes = sqs.get_queue_attributes(QueueUrl=outputs[key], AttributeNames=[
                "ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible",
                "ApproximateNumberOfMessagesDelayed",
            ])["Attributes"]
            require(all(int(value) == 0 for value in attributes.values()),
                    "Use an idle demo route and stop other receivers before --events.")
        publisher = EventBridgePublisher(session.client("eventbridgev2", config=config), outputs["EventBusArn"])
        consumer = SqsCanvasConsumer(sqs, outputs["OutputQueueUrl"])
        store = CanvasStore(":memory:", time.time())
        engine = CanvasEngine(store, OverlaySafety())
        sequence = int(time.time()*1000)

        async def deliver(kind: str, source: str, number: int, data: dict, outcome="applied") -> AmbientEvent:
            event = AmbientEvent(str(uuid4()), source, kind, number, time.time(), data)
            started = time.monotonic()
            require(await asyncio.to_thread(publisher.publish, event) == "PUBLISHED", "Event was not published.")
            while store.receipt(event.id) is None and time.monotonic()-started < 180:
                await consumer.poll_once(engine)
            receipt = store.receipt(event.id)
            require(receipt is not None and receipt[1] == outcome, f"Cloud {kind} event did not reach the receiver.")
            passed("event_delivered", kind=kind, outcome=outcome,
                   seconds=round(time.monotonic()-started, 2))
            return event

        try:
            first = await deliver("presence", "ring-simulator", sequence, {"people": ["leo"], "guest": False})
            require(any(note["id"] == "demo-leo" for note in (await engine.snapshot())["notes"]),
                    "Known-alone audience did not see its sample reminder.")
            require(await asyncio.to_thread(publisher.publish, first) == "DEDUPLICATED", "Bus deduplication failed.")
            await deliver("presence", "ring-simulator", sequence+1, {"people": ["leo"], "guest": True})
            require(not (await engine.snapshot())["notes"], "Guest audience received personal note text.")
            await deliver("presence", "ring-simulator", sequence, {"people": ["leo"], "guest": False}, "ignored")
            require(not (await engine.snapshot())["notes"], "Older presence removed guest privacy.")
            passed("deduplication_ordering_and_guest_privacy")
            await deliver("inventory", "pantry-simulator", sequence, {"available": list(INGREDIENTS)})
            require(set(store.load()["inventory"]["available"]) == set(INGREDIENTS), "Inventory was not applied.")
            playback = str(uuid4())
            for offset, phase in enumerate(("program", "break", "program")):
                await deliver("media", "firetv-simulator", sequence+offset,
                              {"scene": "park_chase", "playback_id": playback, "phase": phase})
                require((await engine.snapshot())["media"]["phase"] == phase, "Playback phase did not match.")
            passed("pantry_and_program_break_resume")
        finally:
            store.db.close()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", default="homebound-canvas")
    parser.add_argument("--region", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--events", action="store_true", help="Consume this idle demo route using a disposable receiver.")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = asyncio.run(verify(args))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2)+"\n")


if __name__ == "__main__":
    try:
        main()
    except ClientError as error:
        raise SystemExit(f"AWS verification failed in {error.operation_name}: {error.response['Error']['Code']}") from None
    except (CanvasError, RuntimeError) as error:
        raise SystemExit(str(error)) from None
