"""Finish platform log settings and write non-secret home receiver configuration."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import tempfile

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", default="homebound-canvas")
    parser.add_argument("--region", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--env-file", type=Path, default=Path(".homebound/cloud-deployment/runtime.env"))
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    config = Config(connect_timeout=5, read_timeout=30,
                    retries={"total_max_attempts": 3, "mode": "adaptive"})
    stack = session.client("cloudformation", config=config).describe_stacks(
        StackName=args.stack
    )["Stacks"][0]
    if stack["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
        raise SystemExit("Finish the application stack before configuring the home receiver.")
    outputs = {entry["OutputKey"]: entry["OutputValue"] for entry in stack["Outputs"]}
    logs = session.client("logs", config=config)
    # AgentCore creates DEFAULT during provisioning. Declaring that same group
    # as a new CloudFormation resource races the platform and fails creation.
    for key in ("RuntimeDefaultLogGroupName", "RuntimeEndpointLogGroupName"):
        name = outputs[key]
        try:
            logs.create_log_group(logGroupName=name, kmsKeyId=outputs["DataKeyArn"])
        except logs.exceptions.ResourceAlreadyExistsException:
            logs.associate_kms_key(logGroupName=name, kmsKeyId=outputs["DataKeyArn"])
        logs.put_retention_policy(logGroupName=name, retentionInDays=14)
        groups = [group for page in logs.get_paginator("describe_log_groups").paginate(
            logGroupNamePrefix=name
        ) for group in page["logGroups"] if group["logGroupName"] == name]
        if len(groups) != 1 or groups[0].get("kmsKeyId") != outputs["DataKeyArn"] or groups[0].get("retentionInDays") != 14:
            raise SystemExit("Platform log configuration did not pass read-back verification.")
    values = {
        "AWS_REGION": args.region,
        "HOMEBOUND_CANVAS_RUNTIME_ARN": outputs["RuntimeArn"],
        "HOMEBOUND_CANVAS_EVENT_QUEUE_URL": outputs["OutputQueueUrl"],
        "HOMEBOUND_CANVAS_GUARDRAIL_ID": outputs["GuardrailId"],
        "HOMEBOUND_CANVAS_GUARDRAIL_VERSION": outputs["GuardrailVersion"],
        "HOMEBOUND_CANVAS_REQUIRE_GUARDRAIL": "true",
        "CANVAS_BUS_ARN": outputs["EventBusArn"],
    }
    if args.profile:
        values["AWS_PROFILE"] = args.profile
    args.env_file.parent.mkdir(parents=True, exist_ok=True)
    text = "# Generated from CloudFormation outputs. Contains no credentials.\n"
    text += "".join(f"{key}={shlex.quote(value)}\n" for key, value in values.items())
    with tempfile.NamedTemporaryFile(mode="w", dir=args.env_file.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(text)
            handle.flush()
            os.replace(temporary, args.env_file)
        finally:
            temporary.unlink(missing_ok=True)
    print(f"Verified encrypted 14-day platform logs; wrote {args.env_file}.")


if __name__ == "__main__":
    try:
        main()
    except ClientError as error:
        raise SystemExit(f"AWS configuration failed: {error.response['Error']['Code']}") from None
