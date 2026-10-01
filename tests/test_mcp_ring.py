"""Contract tests for the real MCP action surface."""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp import Client
from app.adapters.ring_mcp import RingMcpServer


@pytest.mark.asyncio
async def test_server_exposes_only_declarative_ring_actions() -> None:
    ring_server = RingMcpServer()
    async with Client(ring_server.server) as client:
        listed = await client.list_tools()
        tools = {tool.name: tool for tool in listed.tools}

        assert set(tools) == {"unlockDoor", "disarmSystem", "viewStream"}
        unlock_schema = tools["unlockDoor"].input_schema
        assert {"target", "purpose", "context_signals"}.issubset(
            set(unlock_schema["required"])
        )
        assert unlock_schema["properties"]["target"]["type"] == "string"


@pytest.mark.asyncio
async def test_tool_fails_closed_when_governance_is_unavailable() -> None:
    ring_server = RingMcpServer()
    async with Client(ring_server.server) as client:
        result = await client.call_tool(
            "unlockDoor",
            {
                "target": "side_gate",
                "purpose": "delivery",
                "context_signals": {"delivery_expected": True},
            },
        )

    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["decision"] == "BLOCK"
    assert result.structured_content["execution"] == "NOT_PERFORMED"
    assert "No Ring action was executed" in result.structured_content["message"]


def test_ring_tools_do_not_import_or_construct_a_ring_client() -> None:
    source = (Path(__file__).parents[1] / "app/adapters/ring_mcp.py").read_text(
        encoding="utf-8"
    )
    assert "RingExecutionPort" not in source
    assert "ring_sdk" not in source.lower()
