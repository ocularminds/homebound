"""Start HomeBound's local stack and run the three live governed home scenarios."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import boto3
import httpx2
from botocore.config import Config
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from app.config.settings import Settings
from app.orchestration.bedrock import BedrockOrchestrator

LOGGER = logging.getLogger("homebound.demo")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENTSAFE_ENV = PROJECT_ROOT / "agentsafe" / ".env"


class DemoServices:
    """Own and shut down the local AgentSafe, archive, simulator, and MCP processes."""

    def __init__(self) -> None:
        self._processes: list[tuple[str, subprocess.Popen[bytes]]] = []

    def start(self, name: str, command: list[str]) -> None:
        process = subprocess.Popen(command, cwd=PROJECT_ROOT)
        self._processes.append((name, process))

    def stop(self) -> None:
        for _, process in reversed(self._processes):
            if process.poll() is None:
                process.terminate()
        for name, process in reversed(self._processes):
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            if process.returncode not in {0, -15, 143}:
                LOGGER.warning("local service stopped with a failure service=%s", name)


async def _mcp_call(settings: Settings, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async with AsyncExitStack() as stack:
        if settings.mcp_bearer_token:
            http_client = await stack.enter_async_context(
                httpx2.AsyncClient(
                    headers={"Authorization": f"Bearer {settings.mcp_bearer_token}"},
                    timeout=httpx2.Timeout(30.0, read=300.0),
                )
            )
            transport = streamable_http_client(
                settings.mcp_endpoint, http_client=http_client
            )
            client = await stack.enter_async_context(Client(transport))
        else:
            client = await stack.enter_async_context(Client(settings.mcp_endpoint))
        result = await client.call_tool(tool, arguments)
    if result.structured_content is not None:
        return result.structured_content
    return {"decision": "AUTHORITY_UNAVAILABLE", "execution": "NOT_PERFORMED", "message": "MCP returned no structured result."}


async def _wait_for(url: str, name: str, services: DemoServices, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        dead = [service for service, process in services._processes if process.poll() is not None]
        if dead:
            raise RuntimeError(f"A local service exited before becoming ready: {', '.join(dead)}")
        try:
            with urlopen(Request(url, headers={"accept": "application/json"}), timeout=1) as response:
                if response.status == 200:
                    return
        except (HTTPError, URLError, TimeoutError, OSError):
            pass
        await asyncio.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for {name} at {url}; inspect its startup output.")


def _require_loopback(url: str, label: str) -> str:
    parsed = urlsplit(url)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"{label} must point to a loopback service for the local demo")
    return f"{parsed.scheme}://{parsed.netloc}"


def _read_config(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _json_request(url: str, *, token_header: str, token: str) -> dict[str, Any]:
    request = Request(
        url,
        method="POST",
        headers={token_header: token, "accept": "application/json"},
    )
    with urlopen(request, timeout=5) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("The local simulator returned an invalid state response.")
    return value


def _print_result(result: dict[str, Any]) -> None:
    print(f"DECISION\n{result.get('decision', 'UNKNOWN')}")
    print(f"EXECUTION\n{result.get('execution', 'UNKNOWN')}")
    if result.get("correlation_id"):
        print(f"CORRELATION\n{result['correlation_id']}")
    if result.get("grant_id"):
        print(
            "AUTHORIZATION\n"
            f"grant={result['grant_id']} expires_at={result.get('authorization_expires_at') or 'unknown'}"
        )
    reasons = result.get("reason_codes") or []
    if reasons:
        print(f"REASON\n{', '.join(str(code) for code in reasons)}")
    if result.get("dossier_id"):
        proof = result.get("dossier_evidence") or {}
        proof_status = "verified" if proof.get("verified") is True else "verification unavailable"
        print(f"DECISION DOSSIER\n{result['dossier_id']} ({proof_status})")
    if result.get("execution_event"):
        event = result["execution_event"]
        print(f"RING SIMULATOR\n{event.get('result')} — {event.get('target')}")
    print(f"DETAIL\n{result.get('message', '')}")


async def _bedrock_scenario(
    orchestrator: BedrockOrchestrator,
    *,
    scenario: str,
    request_text: str,
    tool: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    prompt = (
        f"Run the single scripted HomeBound scenario named {scenario}. The scenario harness "
        "supplies the exact captured context below. Call exactly the named MCP tool once, "
        "using the supplied JSON arguments verbatim; do not add another action or change "
        "the target or context. The tool result is the authority result.\n\n"
        f"User request: {request_text}\n"
        f"Required tool: {tool}\n"
        f"Exact arguments: {json.dumps(arguments, separators=(',', ':'), sort_keys=True)}"
    )
    trace: list[dict[str, Any]] = []
    response = await orchestrator.respond(
        prompt,
        trace=trace,
        tool_call_validator=lambda called_tool, called_arguments: (
            called_tool == tool and called_arguments == arguments
        ),
    )
    calls = [item for item in trace if item.get("invoked") is True]
    if len(calls) != 1 or calls[0].get("name") != tool:
        raise RuntimeError(
            f"Bedrock did not make exactly one {tool} request for {scenario}; no expected outcome is assumed."
        )
    if calls[0].get("arguments") != arguments:
        raise RuntimeError(
            f"Bedrock changed the supplied tool arguments for {scenario}; the scenario stopped before evaluation."
        )
    result = calls[0].get("result")
    if not isinstance(result, dict):
        raise RuntimeError(f"MCP returned no structured action result for {scenario}.")
    print(f"ALEXA+/BEDROCK\n{response or 'Tool request completed.'}")
    print(f"MCP TOOL\n{tool}({json.dumps(arguments, sort_keys=True)})")
    _print_result(result)
    return result


async def _resume_presence(settings: Settings, result: dict[str, Any]) -> dict[str, Any]:
    correlation_id = result.get("correlation_id")
    if not isinstance(correlation_id, str) or not correlation_id:
        raise RuntimeError("The escalated action returned no correlation ID to resume.")
    print(
        "PRESENCE\nApprove or deny the open request in the household administrator's "
        "Decionis Presence flow. HomeBound will only continue after AgentSafe rechecks it."
    )
    deadline = time.monotonic() + 270
    while time.monotonic() < deadline:
        input("Complete the Presence ceremony, then press Enter to check its result. ")
        resumed = await _mcp_call(
            settings,
            "resumeEscalation",
            {"correlation_id": correlation_id},
        )
        _print_result(resumed)
        if resumed.get("decision") != "ESCALATE":
            return resumed
        print("Presence is still pending; the same bound handoff remains open.")
    raise RuntimeError("Presence approval expired before a terminal Decionis decision was returned.")


async def run_demo() -> int:
    settings = Settings.from_environment()
    config = _read_config(AGENTSAFE_ENV)
    required = {
        "DECIONIS_API_KEY": config.get("DECIONIS_API_KEY"),
        "EXECUTOR_TENANT_ID": config.get("EXECUTOR_TENANT_ID"),
        "EXECUTOR_CALLER_TOKEN": config.get("EXECUTOR_CALLER_TOKEN"),
        "PRESENCE_APPROVER_ID": config.get("PRESENCE_APPROVER_ID"),
        "DOWNSTREAM_CREDENTIAL": config.get("DOWNSTREAM_CREDENTIAL"),
        "HOMEBOUND_DOSSIER_ARCHIVER_TOKEN": config.get("HOMEBOUND_DOSSIER_ARCHIVER_TOKEN"),
        "HOMEBOUND_SIMULATOR_DEMO_TOKEN": config.get("HOMEBOUND_SIMULATOR_DEMO_TOKEN"),
    }
    missing = sorted(key for key, value in required.items() if not value)
    if missing:
        raise RuntimeError(
            "Set the required live Decionis, trusted parent approver, and local simulator "
            f"values in agentsafe/.env: {', '.join(missing)}"
        )
    if settings.dossier_archiver_bearer_token != config.get("HOMEBOUND_DOSSIER_ARCHIVER_TOKEN"):
        raise RuntimeError(
            "HOMEBOUND_DOSSIER_ARCHIVER_TOKEN in the root .env must match agentsafe/.env."
        )
    if settings.agentsafe_bearer_token != config.get("EXECUTOR_CALLER_TOKEN"):
        raise RuntimeError("The root AgentSafe caller token must match agentsafe/.env.")
    if not settings.bedrock_model_id:
        raise RuntimeError("Set BEDROCK_MODEL_ID to an enabled Bedrock Converse model or inference profile.")
    if shutil.which("node") is None:
        raise RuntimeError("Node.js 22.14 or newer is required for the official AgentSafe executor.")
    node_version = subprocess.check_output(
        ["node", "-p", "process.versions.node"], text=True
    ).strip()
    major, minor, *_ = (int(part) for part in node_version.split("."))
    if major < 22 or (major == 22 and minor < 14):
        raise RuntimeError("Node.js 22.14 or newer is required for the official AgentSafe executor.")

    mcp_origin = _require_loopback(settings.mcp_endpoint, "HOMEBOUND_MCP_ENDPOINT")
    agentsafe_origin = _require_loopback(settings.agentsafe_endpoint or "", "HOMEBOUND_AGENTSAFE_URL")
    archive_origin = _require_loopback(
        settings.dossier_archiver_endpoint or "", "HOMEBOUND_DOSSIER_ARCHIVER_URL"
    )
    simulator_url = "http://127.0.0.1:8200"
    simulator_admin_token = config["HOMEBOUND_SIMULATOR_DEMO_TOKEN"]

    services = DemoServices()
    try:
        services.start("agentsafe-and-dossier-archiver", [str(PROJECT_ROOT / "agentsafe" / "run-local.sh")])
        services.start("ring-simulator", [str(PROJECT_ROOT / "agentsafe" / "run-simulator.sh")])
        services.start("homebound-mcp", [sys.executable, "-m", "app.cli.mcp_server"])
        await _wait_for(f"{archive_origin}/healthz", "Decionis dossier archiver", services)
        await _wait_for(f"{agentsafe_origin}/ready", "AgentSafe executor", services)
        await _wait_for(f"{simulator_url}/healthz", "Ring simulator", services)
        await _wait_for(f"{mcp_origin}/healthz", "MCP server", services)

        runtime = boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region,
            config=Config(retries={"max_attempts": 5, "mode": "adaptive"}),
        )
        orchestrator = BedrockOrchestrator(
            runtime,
            settings.bedrock_model_id,
            settings.mcp_endpoint,
            settings.mcp_bearer_token,
            max_tool_calls_per_response=1,
        )
        courier_valid_time = os.getenv("HOMEBOUND_COURIER_VALID_TIME", "14:30")
        courier_wrong_time = os.getenv("HOMEBOUND_COURIER_WRONG_TIME", "23:30")
        scenarios = [
            (
                "SCENARIO 1 — KIDS HOME ALONE",
                "Alexa, disarm the Ring system.",
                "disarmSystem",
                {
                    "target": "home_security",
                    "reason": "home-alone child requested disarm",
                    "context_signals": {"user": "child", "time": "15:00", "location": "home"},
                    "parameters": {},
                },
                "ESCALATE",
                "ALLOW",
                "PERFORMED",
            ),
            (
                "SCENARIO 2 — COURIER, AUTHORIZED WINDOW",
                "The expected high-value courier is at the side gate during the approved window.",
                "unlockDoor",
                {
                    "target": "side_gate",
                    "purpose": "expected high-value courier delivery",
                    "context_signals": {
                        "actor": "delivery-agent",
                        "delivery_expected": True,
                        "courier_recognized": True,
                        "local_time": courier_valid_time,
                    },
                    "parameters": {"unlock_duration_seconds": 30},
                },
                "ALLOW",
                "ALLOW",
                "PERFORMED",
            ),
            (
                "SCENARIO 3 — COURIER, WRONG TIME",
                "The same expected courier is at the side gate outside the approved window.",
                "unlockDoor",
                {
                    "target": "side_gate",
                    "purpose": "expected high-value courier delivery",
                    "context_signals": {
                        "actor": "delivery-agent",
                        "delivery_expected": True,
                        "courier_recognized": True,
                        "local_time": courier_wrong_time,
                    },
                    "parameters": {"unlock_duration_seconds": 30},
                },
                "BLOCK",
                "BLOCK",
                "NOT_PERFORMED",
            ),
        ]
        scenario_results: list[
            tuple[str, str, str, dict[str, Any], dict[str, Any]]
        ] = []
        print(
            "HomeBound demo started. Each scenario resets only the local simulator to a "
            "secured baseline; no physical Ring device is contacted."
        )
        for title, request_text, tool, arguments, expected_initial, expected_final, expected_execution in scenarios:
            print(f"\n{title}\n\nREQUEST\n{request_text}")
            _json_request(
                f"{simulator_url}/demo/reset",
                token_header="x-homebound-demo-reset-token",
                token=simulator_admin_token,
            )
            result = await _bedrock_scenario(
                orchestrator,
                scenario=title,
                request_text=request_text,
                tool=tool,
                arguments=arguments,
            )
            initial = result
            if result.get("decision") == "ESCALATE" and title.startswith("SCENARIO 1"):
                result = await _resume_presence(settings, result)
            scenario_results.append(
                (expected_initial, expected_final, expected_execution, initial, result)
            )
            if title.startswith("SCENARIO 2"):
                device_state = _get_json(f"{simulator_url}/state")
                print(f"SIMULATOR STATE\nside_gate locked={device_state['door_locked']['side_gate']}")
            if title.startswith("SCENARIO 3"):
                device_state = _get_json(f"{simulator_url}/state")
                print(f"SIMULATOR STATE\nside_gate locked={device_state['door_locked']['side_gate']}")

        passed = True
        for index, (expected_initial, expected_final, expected_execution, initial, result) in enumerate(scenario_results, start=1):
            matches = (
                initial.get("decision") == expected_initial
                and result.get("decision") == expected_final
                and result.get("execution") == expected_execution
            )
            if not matches:
                passed = False
                LOGGER.error(
                    "scenario expectation differs from live authority result scenario=%d expected_initial=%s expected_final=%s actual_initial=%s actual_final=%s/%s",
                    index,
                    expected_initial,
                    expected_final,
                    initial.get("decision"),
                    result.get("decision"),
                    result.get("execution"),
                )
        print("\nDEMO RESULT\n" + ("ALL LIVE DECISIONS MATCHED" if passed else "ONE OR MORE LIVE DECISIONS DIFFERED"))
        return 0 if passed else 1
    finally:
        services.stop()


def _get_json(url: str) -> dict[str, Any]:
    with urlopen(Request(url, headers={"accept": "application/json"}), timeout=5) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("A local service returned invalid JSON.")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the three real Decionis-governed Ring simulator scenarios via Bedrock and MCP."
    )
    parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        status = asyncio.run(run_demo())
    except (RuntimeError, ValueError, OSError) as error:
        raise SystemExit(str(error)) from error
    raise SystemExit(status)


if __name__ == "__main__":
    main()
