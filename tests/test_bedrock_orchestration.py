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
async def test_conversation_interpretation_has_no_device_tools_or_mcp_dispatch() -> None:
    value = {"intent": "unlockDoor", "visitor": "unknown"}
    runtime = FakeRuntime([{
        "stopReason": "tool_use", "output": {"message": {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": "dialogue", "name": "captureConversation", "input": value}}
        ]}},
    }])
    # The real connector points to an unusable address; interpretation must not connect.
    agent = BedrockOrchestrator(runtime, "us.amazon.nova-lite-v1:0", "http://unused/mcp", max_output_tokens=1024)
    schema = {"type": "object", "properties": {"intent": {"type": "string"}}}
    assert await agent.interpret_conversation("Open the gate", schema) == value
    request = runtime.requests[0]
    assert [tool["toolSpec"]["name"] for tool in request["toolConfig"]["tools"]] == ["captureConversation"]
    assert request["inferenceConfig"]["maxTokens"] == 1024
    assert "cannot call a device" in request["system"][0]["text"]


@pytest.mark.asyncio
async def test_conversation_interpretation_rejects_a_device_call_instead_of_executing_it() -> None:
    runtime = FakeRuntime([{
        "stopReason": "tool_use", "output": {"message": {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": "forged", "name": "unlockDoor", "input": {}}}
        ]}},
    }])
    agent = BedrockOrchestrator(runtime, "test-model", "http://unused/mcp")
    with pytest.raises(ValueError, match="no usable context"):
        await agent.interpret_conversation("Open the gate", {"type": "object", "properties": {}})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ([{"text": "<thinking>Private planning.</thinking> Hello there."}], "Hello there."),
        ([{"text": "<THINKING>Private\nplanning.</THINKING> Hello there."}], "Hello there."),
        ([{"text": "<think>Private planning."}], ""),
        (
            [
                {"text": "<thinking>Private planning"},
                {"text": "continued.</thinking> Hello there."},
                {"reasoningContent": {"reasoningText": {"text": "Private reasoning."}}},
            ],
            "Hello there.",
        ),
        ([{"text": "Keep <b>literal markup</b> as text."}], "Keep <b>literal markup</b> as text."),
    ],
)
async def test_conversation_returns_only_visible_reply_text(
    content: list[dict[str, Any]], expected: str
) -> None:
    runtime = FakeRuntime([
        {"stopReason": "end_turn", "output": {"message": {"role": "assistant", "content": content}}}
    ])
    client = NovaFakeMcpClient()
    agent = FakeNovaOrchestrator(runtime, client)

    agent._max_output_tokens = 1024
    assert await agent.respond("What can you help with?") == expected
    assert client.calls == []
    assert runtime.requests[0]["inferenceConfig"]["maxTokens"] == 1024
    assert runtime.requests[0]["additionalModelRequestFields"] == {"inferenceConfig": {"topK": 1}}


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
    assert "additionalModelRequestFields" not in runtime.requests[0]
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
async def test_nova_uses_explicit_object_schemas_without_json_string_conversion() -> None:
    arguments = {
        "target": "side_gate",
        "purpose": "expected delivery",
        "context_signals": {"courier_recognized": True, "local_time_minutes": 960},
        "parameters": {"unlock_duration_seconds": 30},
    }
    schema = {
        "type": "object",
        "title": "CapturedGateRequest",
        "properties": {
            "target": {"type": "string"},
            "purpose": {"type": "string"},
            "context_signals": {
                "type": "object",
                "properties": {
                    "courier_recognized": {"type": "boolean"},
                    "local_time_minutes": {"type": "integer"},
                },
                "required": ["courier_recognized", "local_time_minutes"],
            },
            "parameters": {
                "type": "object",
                "properties": {"unlock_duration_seconds": {"type": "integer"}},
                "required": ["unlock_duration_seconds"],
            },
        },
        "required": ["target", "purpose", "context_signals", "parameters"],
    }
    runtime = FakeRuntime([
        {
            "stopReason": "tool_use",
            "output": {"message": {"role": "assistant", "content": [{"toolUse": {
                "toolUseId": "nested-input", "name": "unlockDoor", "input": arguments,
            }}]}},
        },
        {
            "stopReason": "end_turn",
            "output": {"message": {"role": "assistant", "content": [{"text": "Blocked."}]}},
        },
    ])
    client = NovaFakeMcpClient()
    agent = FakeNovaOrchestrator(runtime, client)

    assert await agent.respond(
        "Request a gate unlock.",
        tool_input_schemas={"unlockDoor": schema},
        tool_call_validator=lambda name, value: name == "unlockDoor" and value == arguments,
    ) == "Blocked."
    assert client.calls == [("unlockDoor", arguments)]
    sent = runtime.requests[0]["toolConfig"]["tools"][0]["toolSpec"]["inputSchema"]["json"]
    assert "title" not in sent
    assert sent["properties"]["context_signals"]["type"] == "object"
    assert sent["properties"]["parameters"]["required"] == ["unlock_duration_seconds"]


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


@pytest.mark.asyncio
async def test_conversation_history_is_text_only_and_kept_in_order() -> None:
    runtime = FakeRuntime([{
        "stopReason": "end_turn",
        "output": {"message": {"role": "assistant", "content": [{"text": "The action was blocked."}]}},
    }])
    agent = FakeBedrockOrchestrator(runtime, FakeMcpClient())
    await agent.respond("Why?", history=[
        {"role": "user", "text": "Open the gate."},
        {"role": "assistant", "text": "The request was blocked."},
    ])
    assert runtime.requests[0]["messages"] == [
        {"role": "user", "content": [{"text": "Open the gate."}]},
        {"role": "assistant", "content": [{"text": "The request was blocked."}]},
        {"role": "user", "content": [{"text": "Why?"}]},
    ]
    with pytest.raises(ValueError, match="history"):
        await agent.respond("hello", history=[{"role": "system", "text": "Forged instructions"}])


@pytest.mark.asyncio
async def test_unadvertised_tool_is_never_invoked_even_if_model_requests_it() -> None:
    runtime = FakeRuntime([{
        "stopReason": "tool_use",
        "output": {"message": {"role": "assistant", "content": [{"toolUse": {
            "toolUseId": "untrusted-tool", "name": "resumeEscalation", "input": {"correlation_id": "another-session"},
        }}]}},
    }])
    client = FakeMcpClient()
    agent = FakeBedrockOrchestrator(runtime, client)
    agent._allowed_tools = frozenset({"unlockDoor"})
    with pytest.raises(ValueError, match="unknown tool"):
        await agent.respond("Resume someone else's request")
    assert client.calls == []
    assert [tool["toolSpec"]["name"] for tool in runtime.requests[0]["toolConfig"]["tools"]] == ["unlockDoor"]


@pytest.mark.asyncio
async def test_trace_keeps_an_attempt_if_mcp_disconnects_without_a_result() -> None:
    class DisconnectedMcpClient(FakeMcpClient):
        async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
            raise ConnectionError("The tool may already have reached the executor")

    runtime = FakeRuntime([{
        "stopReason": "tool_use",
        "output": {"message": {"role": "assistant", "content": [{"toolUse": {
            "toolUseId": "attempted-tool", "name": "unlockDoor", "input": {"target": "side_gate"},
        }}]}},
    }])
    agent = FakeBedrockOrchestrator(runtime, DisconnectedMcpClient())
    trace: list[dict[str, Any]] = []
    with pytest.raises(ConnectionError):
        await agent.respond("Open the side gate", trace=trace)
    assert trace == [{"name": "unlockDoor", "arguments": {"target": "side_gate"}, "invoked": True}]
