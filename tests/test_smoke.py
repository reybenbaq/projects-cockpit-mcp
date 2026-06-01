"""Smoke tests: the server builds and registers exactly the expected tools."""

from __future__ import annotations

import mcp.types
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from cockpit.config import PROTOCOL_REVISION, Config
from cockpit.server import build_app, build_server

EXPECTED_TOOLS = {
    "list_projects",
    "list_agents",
    "list_plans",
    "project_status",
    "memory_search",
}


async def test_all_tools_registered(config: Config) -> None:
    server = build_server(config)
    tools = await server.list_tools()
    assert {tool.name for tool in tools} == EXPECTED_TOOLS


def test_build_app_is_callable(config: Config) -> None:
    app = build_app(config)
    assert callable(app)


def test_sdk_supports_declared_protocol() -> None:
    # The pinned SDK must actually negotiate the revision the README advertises;
    # this turns PROTOCOL_REVISION from documentation into an enforced contract.
    assert mcp.types.LATEST_PROTOCOL_VERSION == PROTOCOL_REVISION


async def test_traversal_project_arg_surfaces_as_tool_error(config: Config) -> None:
    server = build_server(config)
    with pytest.raises(ToolError):
        await server.call_tool("project_status", {"project": "../escape"})
