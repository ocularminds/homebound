"""Amazon Bedrock Converse orchestration over the real HomeBound MCP server."""

from __future__ import annotations

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
            tool_config = {
                "tools": [
                    {
                        "toolSpec": {
                            "name": tool.name,
                            "description": tool.description or tool.name,
                            "inputSchema": {"json": tool.input_schema},
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
            inferenceConfig={"maxTokens": 500, "temperature": 0.2},
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
