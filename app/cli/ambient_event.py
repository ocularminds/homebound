"""Publish an explicit demo presence signal to the deployed EventBridge pipeline."""

from __future__ import annotations

import argparse
import json
import sys
import time
from uuid import uuid4

import boto3
from botocore.config import Config

from app.ambient.aws import EventBridgePublisher
from app.ambient.catalog import PEOPLE
from app.ambient.models import AmbientEvent


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish a normalized, simulated presence event. Never a real identity claim."
    )
    parser.add_argument("--bus-arn", required=True)
    parser.add_argument("--person", choices=[*PEOPLE, "empty"], required=True)
    parser.add_argument("--guest", action="store_true")
    parser.add_argument(
        "--sequence",
        type=int,
        required=True,
        help="Monotonically increasing sequence for this home and source.",
    )
    parser.add_argument("--region", default=None)
    args = parser.parse_args()
    event = AmbientEvent(
        str(uuid4()),
        "ring-simulator",
        "presence",
        args.sequence,
        time.time(),
        {"people": [] if args.person == "empty" else [args.person], "guest": args.guest},
    )
    try:
        session = boto3.Session(region_name=args.region)
        client = session.client(
            "eventbridgev2",
            config=Config(
                connect_timeout=5,
                read_timeout=15,
                retries={"total_max_attempts": 2, "mode": "adaptive"},
            ),
        )
        result = EventBridgePublisher(client, args.bus_arn).publish(event)
        print(json.dumps({"accepted": result, "event_id": event.id, "delivery_confirmed": False}))
        return 0
    except Exception as error:
        print(f"Ambient signal not confirmed ({type(error).__name__}).", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
