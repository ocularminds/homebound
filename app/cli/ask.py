"""Send natural-language requests through Bedrock and the MCP server."""

from __future__ import annotations

import argparse
import asyncio
import logging

import boto3

from app.config.settings import Settings
from app.orchestration.bedrock import BedrockOrchestrator


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the HomeBound Bedrock agent")
    parser.add_argument("request", nargs="+", help="Natural-language request for the home")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = Settings.from_environment()
    if not settings.bedrock_model_id:
        raise SystemExit("Set BEDROCK_MODEL_ID to an enabled model ID or inference profile.")
    runtime = boto3.client("bedrock-runtime", region_name=settings.aws_region)
    agent = BedrockOrchestrator(
        runtime=runtime,
        model_id=settings.bedrock_model_id,
        mcp_endpoint=settings.mcp_endpoint,
        mcp_bearer_token=settings.mcp_bearer_token,
    )
    print(asyncio.run(agent.respond(" ".join(args.request))))


if __name__ == "__main__":
    main()
