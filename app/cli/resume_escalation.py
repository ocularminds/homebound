"""Resume one stored Decionis managed approval through AgentSafe."""

from __future__ import annotations

import argparse
import asyncio
import json

from app.config.settings import Settings
from app.interception.agentsafe_http import AgentSafeActionPort
from app.interception.factory import action_request_port


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check and resume one AgentSafe managed Presence escalation."
    )
    parser.add_argument("correlation_id", help="Correlation ID returned by the MCP action")
    args = parser.parse_args()
    port = action_request_port(Settings.from_environment())
    if not isinstance(port, AgentSafeActionPort):
        raise SystemExit("AgentSafe is not configured; escalation was not resumed.")
    result = asyncio.run(port.resume(args.correlation_id))
    print(json.dumps(result.as_dict(), indent=2))


if __name__ == "__main__":
    main()
