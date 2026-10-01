"""Amazon Bedrock Converse orchestration over the real HomeBound MCP server."""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, AsyncIterator, Protocol

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
    ) -> None:
        self._runtime = runtime
        self._model_id = model_id
        self._mcp_endpoint = mcp_endpoint
        self._mcp_bearer_token = mcp_bearer_token
        self._max_tool_rounds = max_tool_rounds

    async def respond(self, prompt: str) -> str:
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
                    result = await client.call_tool(use["name"], use.get("input", {}))
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
