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


class NovaFakeMcpClient(FakeMcpClient):
    async def list_tools(self) -> Any:
        return SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name="unlockDoor",
                    description="Request an exact door unlock",
                    input_schema={
                        "type": "object",
                        "title": "unlockDoorArguments",
                        "properties": {
                            "target": {"type": "string", "title": "Target"},
                            "purpose": {"type": "string", "title": "Purpose"},
                            "context_signals": {
                                "type": "object",
                                "title": "Context Signals",
                                "additionalProperties": True,
                            },
                            "parameters": {
                                "type": "object",
                                "title": "Parameters",
                                "additionalProperties": True,
                                "anyOf": [
                                    {"type": "object", "additionalProperties": True},
                                    {"type": "null"},
                                ],
                            },
                        },
                        "required": ["target", "purpose", "context_signals"],
                    },
                )
            ]
        )


class FakeBedrockOrchestrator(BedrockOrchestrator):
    def __init__(self, runtime: FakeRuntime, client: FakeMcpClient) -> None:
        super().__init__(runtime, "test-model", "http://unused/mcp")
        self._fake_client = client

    @asynccontextmanager
    async def _connect_mcp(self) -> Any:
        yield self._fake_client


class FakeNovaOrchestrator(FakeBedrockOrchestrator):
    def __init__(self, runtime: FakeRuntime, client: NovaFakeMcpClient) -> None:
        BedrockOrchestrator.__init__(
            self, runtime, "us.amazon.nova-lite-v1:0", "http://unused/mcp"
        )
        self._fake_client = client


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


@pytest.mark.asyncio
async def test_demo_trace_captures_result_and_enforces_per_request_tool_limit() -> None:
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
                            },
                            {
                                "toolUse": {
                                    "toolUseId": "tool-2",
                                    "name": "disarmSystem",
                                    "input": {"target": "home_security"},
                                }
                            },
                        ],
                    }
                },
            },
            {
                "stopReason": "end_turn",
                "output": {
                    "message": {"role": "assistant", "content": [{"text": "Done."}]}
                },
            },
        ]
    )
    client = FakeMcpClient()
    base = FakeBedrockOrchestrator(runtime, client)
    base._max_tool_calls_per_response = 1
    trace: list[dict[str, Any]] = []

    answer = await base.respond("run one action", trace=trace)

    assert answer == "Done."
    assert [name for name, _ in client.calls] == ["unlockDoor"]
    assert trace[0]["invoked"] is True
    assert trace[0]["result"]["decision"] == "BLOCK"
    assert trace[1]["invoked"] is False
    assert trace[1]["reason"] == "TOOL_CALL_LIMIT_REACHED"


@pytest.mark.asyncio
async def test_demo_fixture_mismatch_is_rejected_before_mcp_invocation() -> None:
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
                                    "input": {"target": "front_door"},
                                }
                            }
                        ],
                    }
                },
            },
            {
                "stopReason": "end_turn",
                "output": {
                    "message": {"role": "assistant", "content": [{"text": "Stopped."}]}
                },
            },
        ]
    )
    client = FakeMcpClient()
    base = FakeBedrockOrchestrator(runtime, client)
    trace: list[dict[str, Any]] = []

    answer = await base.respond(
        "run an exact scenario",
        trace=trace,
        tool_call_validator=lambda name, args: name == "unlockDoor" and args == {"target": "side_gate"},
    )

    assert answer == "Stopped."
    assert client.calls == []
    assert trace == [
        {
            "name": "unlockDoor",
            "arguments": {"target": "front_door"},
            "invoked": False,
            "reason": "SCENARIO_INPUT_MISMATCH",
        }
    ]


@pytest.mark.asyncio
async def test_nova_schema_and_json_string_fields_map_back_to_structured_mcp_inputs() -> None:
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
                                    "toolUseId": "nova-tool-1",
                                    "name": "unlockDoor",
                                    "input": {
                                        "target": "side_gate",
                                        "purpose": "expected courier",
                                        "context_signals": '{"delivery_expected":true,"local_time":"14:30"}',
                                        "parameters": '{"unlock_duration_seconds":30}',
                                    },
                                }
                            }
                        ],
                    }
                },
            },
            {
                "stopReason": "end_turn",
                "output": {
                    "message": {"role": "assistant", "content": [{"text": "Blocked safely."}]}
                },
            },
        ]
    )
    client = NovaFakeMcpClient()
    agent = FakeNovaOrchestrator(runtime, client)

    answer = await agent.respond("Request the courier gate action.")

    assert answer == "Blocked safely."
    assert client.calls == [
        (
            "unlockDoor",
            {
                "target": "side_gate",
                "purpose": "expected courier",
                "context_signals": {"delivery_expected": True, "local_time": "14:30"},
                "parameters": {"unlock_duration_seconds": 30},
            },
        )
    ]
    schema = runtime.requests[0]["toolConfig"]["tools"][0]["toolSpec"]["inputSchema"]["json"]
    assert set(schema) == {"type", "properties", "required"}
    assert schema["properties"]["context_signals"]["type"] == "string"
    assert schema["properties"]["parameters"]["type"] == "string"
    assert runtime.requests[0]["inferenceConfig"]["temperature"] == 0.0


@pytest.mark.asyncio
async def test_nova_rejects_malformed_json_objects_before_mcp() -> None:
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
                                    "toolUseId": "nova-tool-2",
                                    "name": "unlockDoor",
                                    "input": {
                                        "target": "side_gate",
                                        "purpose": "delivery",
                                        "context_signals": "{not-json}",
                                    },
                                }
                            }
                        ],
                    }
                },
            },
            {
                "stopReason": "end_turn",
                "output": {
                    "message": {"role": "assistant", "content": [{"text": "Not sent."}]}
                },
            },
        ]
    )
    client = NovaFakeMcpClient()
    agent = FakeNovaOrchestrator(runtime, client)
    trace: list[dict[str, Any]] = []

    answer = await agent.respond("Request a door action.", trace=trace)

    assert answer == "Not sent."
    assert client.calls == []
    assert trace == [
        {
            "name": "unlockDoor",
            "arguments": {
                "target": "side_gate",
                "purpose": "delivery",
                "context_signals": "{not-json}",
            },
            "invoked": False,
            "reason": "INVALID_TOOL_ARGUMENTS",
        }
    ]
