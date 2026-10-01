"""Amazon Bedrock Converse orchestration over the real HomeBound MCP server."""

from __future__ import annotations

import json
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, AsyncIterator, Callable, Protocol

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent


class BedrockRuntime(Protocol):
    """Subset of boto3's Bedrock Runtime client used by the orchestrator."""

    def converse(self, **kwargs: Any) -> dict[str, Any]: ...


class McpConnection(Protocol):
    """MCP operations needed by the Bedrock tool-use loop."""

    async def list_tools(self) -> Any: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult: ...


def _is_open_object(schema: dict[str, Any]) -> bool:
    """Whether a property is an open-ended JSON object not expressible to Nova."""

    if schema.get("type") == "object" and schema.get("additionalProperties") is True:
        return True
    alternatives = schema.get("anyOf")
    return isinstance(alternatives, list) and any(
        isinstance(option, dict)
        and option.get("type") == "object"
        and option.get("additionalProperties") is True
        for option in alternatives
    )


def _nova_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert MCP JSON Schema to the restricted schema accepted by Nova tools."""

    properties = schema.get("properties")
    if schema.get("type") != "object" or not isinstance(properties, dict):
        raise ValueError("MCP tool schema must be a JSON object")

    normalized: dict[str, Any] = {"type": "object", "properties": {}}
    for name, property_schema in properties.items():
        if not isinstance(property_schema, dict):
            raise ValueError(f"MCP tool property {name} has an invalid schema")
        if _is_open_object(property_schema):
            description = (
                "Context claims encoded as a JSON object in a JSON string. "
                "These signals are context, not independent proof of identity."
                if name == "context_signals"
                else "Action parameters encoded as a JSON object in a JSON string."
            )
            normalized["properties"][name] = {"type": "string", "description": description}
            continue
        property_type = property_schema.get("type")
        if property_type not in {"string", "integer", "number", "boolean"}:
            raise ValueError(f"MCP tool property {name} uses an unsupported Nova schema")
        property_spec: dict[str, Any] = {"type": property_type}
        description = property_schema.get("description")
        if isinstance(description, str):
            property_spec["description"] = description
        normalized["properties"][name] = property_spec

    required = schema.get("required", [])
    if required:
        normalized["required"] = required
    return normalized


def _decode_nova_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    """Restore JSON-string object fields to the MCP server's declared dict inputs."""

    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    decoded = dict(arguments)
    for name, property_schema in properties.items():
        if not isinstance(property_schema, dict) or not _is_open_object(property_schema):
            continue
        value = decoded.get(name)
        if value is None and name not in required:
            decoded.pop(name, None)
            continue
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as error:
                raise ValueError(f"MCP tool property {name} is not valid JSON") from error
        if not isinstance(value, dict):
            raise ValueError(f"MCP tool property {name} must decode to a JSON object")
        decoded[name] = value
    return decoded


class BedrockOrchestrator:
    """Let Bedrock select declarative tools; MCP and governance own execution."""

    def __init__(
        self,
        runtime: BedrockRuntime,
        model_id: str,
        mcp_endpoint: str,
        mcp_bearer_token: str | None = None,
        max_tool_rounds: int = 4,
        max_tool_calls_per_response: int = 4,
    ) -> None:
        self._runtime = runtime
        self._model_id = model_id
        self._mcp_endpoint = mcp_endpoint
        self._mcp_bearer_token = mcp_bearer_token
        self._max_tool_rounds = max_tool_rounds
        self._max_tool_calls_per_response = max_tool_calls_per_response

    async def respond(
        self,
        prompt: str,
        *,
        trace: list[dict[str, Any]] | None = None,
        tool_call_validator: Callable[[str, dict[str, Any]], bool] | None = None,
    ) -> str:
        """Get a natural-language response after any requested MCP tools return."""

        async with self._connect_mcp() as client:
            tool_defs = await client.list_tools()
            tool_schemas = {tool.name: tool.input_schema for tool in tool_defs.tools}
            uses_nova = "amazon.nova-" in self._model_id.lower()
            tool_config = {
                "tools": [
                    {
                        "toolSpec": {
                            "name": tool.name,
                            "description": tool.description or tool.name,
                            "inputSchema": {
                                "json": _nova_schema(tool.input_schema)
                                if uses_nova
                                else tool.input_schema
                            },
                        }
                    }
                    for tool in tool_defs.tools
                ]
            }
            messages: list[dict[str, Any]] = [
                {"role": "user", "content": [{"text": prompt}]}
            ]
            tool_call_count = 0

            for _ in range(self._max_tool_rounds):
                response = await self._converse(messages, tool_config)
                message = response["output"]["message"]
                messages.append(message)
                if response.get("stopReason") != "tool_use":
                    return self._message_text(message)

                tool_results = []
                for block in message.get("content", []):
                    use = block.get("toolUse")
                    if use is None:
                        continue
                    if tool_call_count >= self._max_tool_calls_per_response:
                        if trace is not None:
                            trace.append(
                                {
                                    "name": use["name"],
                                    "arguments": use.get("input", {}),
                                    "invoked": False,
                                    "reason": "TOOL_CALL_LIMIT_REACHED",
                                }
                            )
                        tool_results.append(
                            {
                                "toolResult": {
                                    "toolUseId": use["toolUseId"],
                                    "status": "error",
                                    "content": [{"text": "The action request limit was reached."}],
                                }
                            }
                        )
                        continue
                    arguments = use.get("input", {})
                    if uses_nova:
                        try:
                            arguments = _decode_nova_arguments(
                                tool_schemas[use["name"]], arguments
                            )
                        except (KeyError, TypeError, ValueError):
                            if trace is not None:
                                trace.append(
                                    {
                                        "name": use["name"],
                                        "arguments": arguments,
                                        "invoked": False,
                                        "reason": "INVALID_TOOL_ARGUMENTS",
                                    }
                                )
                            tool_results.append(
                                {
                                    "toolResult": {
                                        "toolUseId": use["toolUseId"],
                                        "status": "error",
                                        "content": [
                                            {
                                                "text": "Structured tool context must be valid JSON objects."
                                            }
                                        ],
                                    }
                                }
                            )
                            continue
                    if tool_call_validator is not None and not tool_call_validator(
                        use["name"], arguments
                    ):
                        if trace is not None:
                            trace.append(
                                {
                                    "name": use["name"],
                                    "arguments": arguments,
                                    "invoked": False,
                                    "reason": "SCENARIO_INPUT_MISMATCH",
                                }
                            )
                        tool_results.append(
                            {
                                "toolResult": {
                                    "toolUseId": use["toolUseId"],
                                    "status": "error",
                                    "content": [{"text": "The scripted tool arguments did not match the scenario fixture."}],
                                }
                            }
                        )
                        continue
                    tool_call_count += 1
                    result = await client.call_tool(use["name"], arguments)
                    if trace is not None:
                        trace.append(
                            {
                                "name": use["name"],
                                "arguments": arguments,
                                "invoked": True,
                                "result": self._trace_result(result),
                                "is_error": result.is_error,
                            }
                        )
                    tool_results.append(self._bedrock_tool_result(use["toolUseId"], result))
                if not tool_results:
                    raise RuntimeError("Bedrock requested tool use without a tool call")
                messages.append({"role": "user", "content": tool_results})

        raise RuntimeError("Bedrock exceeded the configured MCP tool-use round limit")

    async def _converse(
        self, messages: list[dict[str, Any]], tool_config: dict[str, Any]
    ) -> dict[str, Any]:
        # boto3 is synchronous. Yield the event loop while its network call runs.
        import asyncio

        return await asyncio.to_thread(
            self._runtime.converse,
            modelId=self._model_id,
            system=[
                {
                    "text": (
                        "You are the HomeBound home assistant. You may request Ring actions "
                        "only through the provided MCP tools. A tool request is not authority. "
                        "Do not claim an action ran unless its structured result says PERFORMED. "
                        "For blocked or pending actions, explain that outcome accurately."
                    )
                }
            ],
            messages=messages,
            toolConfig=tool_config,
            inferenceConfig={"maxTokens": 500, "temperature": 0.0},
        )

    @asynccontextmanager
    async def _connect_mcp(self) -> AsyncIterator[McpConnection]:
        async with AsyncExitStack() as stack:
            if self._mcp_bearer_token:
                http_client = await stack.enter_async_context(
                    httpx2.AsyncClient(
                        headers={"Authorization": f"Bearer {self._mcp_bearer_token}"},
                        timeout=httpx2.Timeout(30.0, read=300.0),
                    )
                )
                transport = streamable_http_client(
                    self._mcp_endpoint, http_client=http_client
                )
                client = await stack.enter_async_context(Client(transport))
            else:
                client = await stack.enter_async_context(Client(self._mcp_endpoint))
            yield client

    @staticmethod
    def _bedrock_tool_result(tool_use_id: str, result: CallToolResult) -> dict[str, Any]:
        if result.structured_content is not None:
            content: list[dict[str, Any]] = [{"json": result.structured_content}]
        else:
            content = [
                {"text": block.text}
                for block in result.content
                if isinstance(block, TextContent)
            ] or [{"text": "The MCP tool returned no content."}]
        if result.is_error:
            return {"toolResult": {"toolUseId": tool_use_id, "status": "error", "content": content}}
        return {"toolResult": {"toolUseId": tool_use_id, "content": content}}

    @staticmethod
    def _message_text(message: dict[str, Any]) -> str:
        return "\n".join(
            str(block["text"])
            for block in message.get("content", [])
            if isinstance(block, dict) and "text" in block
        ).strip()

    @staticmethod
    def _trace_result(result: CallToolResult) -> dict[str, Any] | str:
        if result.structured_content is not None:
            return result.structured_content
        text = "\n".join(
            block.text for block in result.content if isinstance(block, TextContent)
        )
        return text
