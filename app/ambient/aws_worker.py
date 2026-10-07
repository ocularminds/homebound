"""SQS -> AgentCore -> SQS bridge. Partial batch failures retain individual source events."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import boto3
from botocore.config import Config

from app.ambient.aws import invoke_json
from app.ambient.supervisor import event_from_wire, validate_routed_event

_clients: tuple[Any, Any] | None = None


def process_batch(
    records: list[dict[str, Any]], runtime: Any, sqs: Any, runtime_arn: str, output_queue: str
) -> dict[str, Any]:
    failures = []
    for position, record in enumerate(records):
        try:
            raw = record["body"]
            if not isinstance(raw, str) or len(raw) > 16000:
                raise ValueError("Event size invalid")
            event = event_from_wire(json.loads(raw))
            session_id = hashlib.sha256(f"{event.home_id}:{event.id}".encode()).hexdigest()
            routed = invoke_json(
                runtime,
                runtime_arn,
                {"operation": "event", "event": event.public_envelope()},
                session_id,
            )
            returned_event = validate_routed_event(routed)
            if returned_event != event:
                raise ValueError("Supervisor changed the source event")
            sqs.send_message(
                QueueUrl=output_queue,
                MessageBody=json.dumps(routed),
                MessageGroupId=event.home_id,
                MessageDeduplicationId=event.id,
            )
        except Exception:
            failures.append({"itemIdentifier": record["messageId"]})
            # FIFO: leave later items unprocessed after the first failure.
            failures.extend({"itemIdentifier": r["messageId"]} for r in records[position + 1 :])
            break
    return {"batchItemFailures": failures}


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    global _clients
    if _clients is None:
        session = boto3.Session()
        config = Config(
            connect_timeout=5,
            read_timeout=65,
            retries={"total_max_attempts": 2, "mode": "adaptive"},
        )
        _clients = (
            session.client("bedrock-agentcore", config=config),
            session.client("sqs", config=config),
        )
    return process_batch(
        event["Records"],
        *_clients,
        os.environ["CANVAS_RUNTIME_ARN"],
        os.environ["CANVAS_OUTPUT_QUEUE_URL"],
    )
