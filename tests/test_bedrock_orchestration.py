"""Tests for Bedrock's MCP tool-use loop without making AWS calls."""

from __future__ import annotations

from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from app.orchestration.bedrock import BedrockOrchestrator


class FakeRuntime:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(deepcopy(kwargs))
        return self.responses.pop(0)


class FakeMcpClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> Any:
        return SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name="unlockDoor",
                    description="Request an exact door unlock",
                    input_schema={"type": "object", "properties": {"target": {"type": "string"}}},
                )
            ]
        )

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        return SimpleNamespace(
            structured_content={
                "decision": "BLOCK",
                "execution": "NOT_PERFORMED",
                "message": "No authority configured",
            },
            content=[],
            is_error=False,
        )


class FakeBedrockOrchestrator(BedrockOrchestrator):
    def __init__(self, runtime: FakeRuntime, client: FakeMcpClient) -> None:
        super().__init__(runtime, "test-model", "http://unused/mcp")
        self._fake_client = client

    @asynccontextmanager
    async def _connect_mcp(self) -> Any:
        yield self._fake_client


@pytest.mark.asyncio
async def test_bedrock_calls_mcp_and_returns_final_natural_language() -> None:
    runtime = FakeRuntime(
        [
            {
                "stopReason": "tool_use",
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "toolUse": {
                                    "toolUseId": "tool-1",
                                    "name": "unlockDoor",
                                    "input": {"target": "side_gate"},
                                }
                            }
                        ],
                    }
                },
            },
            {
                "stopReason": "end_turn",
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [{"text": "I could not unlock the gate."}],
                    }
                },
            },
        ]
    )
    client = FakeMcpClient()
    agent = FakeBedrockOrchestrator(runtime, client)

    answer = await agent.respond("Unlock the side gate for the delivery.")

    assert answer == "I could not unlock the gate."
    assert client.calls == [("unlockDoor", {"target": "side_gate"})]
    assert runtime.requests[0]["toolConfig"]["tools"][0]["toolSpec"]["name"] == "unlockDoor"
    assert runtime.requests[1]["messages"][-1]["content"][0]["toolResult"]["toolUseId"] == "tool-1"
    assert runtime.requests[1]["messages"][-1]["content"][0]["toolResult"]["content"][0]["json"]["execution"] == "NOT_PERFORMED"
