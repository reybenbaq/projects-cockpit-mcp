"""Tests for server wiring: transport-security config and the bearer-only app."""

from __future__ import annotations

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import (
    TransportSecurityMiddleware,
    TransportSecuritySettings,
)
from starlette.requests import Request

from cockpit import server
from cockpit.config import (
    _DEFAULT_ALLOWED_HOSTS,
    _DEFAULT_ALLOWED_ORIGINS,
    Config,
)
from cockpit.middleware import SecurityMiddleware


def _config(tmp_path) -> Config:
    return Config(
        projects_root=tmp_path,
        memory_root=tmp_path,
        token="tok",
        allowed_hosts=frozenset({"127.0.0.1:*", "example.com:*"}),
        allowed_origins=frozenset({"http://127.0.0.1:*"}),
    )


def test_transport_security_configured_from_config(tmp_path) -> None:
    """Host/Origin DNS-rebinding defense is set explicitly from config, not left
    to FastMCP's implicit localhost auto-enable."""
    mcp = server.build_server(_config(tmp_path))
    ts = mcp.settings.transport_security
    assert ts is not None
    assert ts.enable_dns_rebinding_protection is True
    assert set(ts.allowed_hosts) == {"127.0.0.1:*", "example.com:*"}
    assert set(ts.allowed_origins) == {"http://127.0.0.1:*"}


def test_build_app_is_bearer_only(tmp_path) -> None:
    app = server.build_app(_config(tmp_path))
    assert isinstance(app, SecurityMiddleware)
    assert app._token == "tok"
    # Origin enforcement moved to the transport layer; the middleware holds none.
    assert not hasattr(app, "_allowed_origins")


def _request(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "GET", "headers": raw})


def _loopback_middleware() -> TransportSecurityMiddleware:
    """The SDK transport guard built from the package's default loopback sets,
    so these tests prove the *shipped defaults* enforce as the README documents."""
    settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=sorted(_DEFAULT_ALLOWED_HOSTS),
        allowed_origins=sorted(_DEFAULT_ALLOWED_ORIGINS),
    )
    return TransportSecurityMiddleware(settings)


async def test_default_sets_accept_loopback_host_and_origin() -> None:
    mw = _loopback_middleware()
    result = await mw.validate_request(
        _request({"host": "127.0.0.1:8848", "origin": "http://127.0.0.1:8848"})
    )
    assert result is None


async def test_default_sets_accept_missing_origin() -> None:
    # Non-browser clients (Claude Code) send no Origin; that must pass.
    mw = _loopback_middleware()
    result = await mw.validate_request(_request({"host": "localhost:8848"}))
    assert result is None


async def test_non_loopback_host_returns_421() -> None:
    mw = _loopback_middleware()
    result = await mw.validate_request(_request({"host": "evil.example.com"}))
    assert result is not None
    assert result.status_code == 421


async def test_foreign_origin_returns_403() -> None:
    mw = _loopback_middleware()
    result = await mw.validate_request(
        _request({"host": "127.0.0.1:8848", "origin": "http://evil.example.com"})
    )
    assert result is not None
    assert result.status_code == 403


# ---------------------------------------------------------------------------
# Tool annotations — readOnlyHint and title
# ---------------------------------------------------------------------------

_READ_ONLY_TOOLS = {
    "list_projects",
    "list_agents",
    "list_plans",
    "project_status",
    "memory_search",
}


async def test_all_tools_have_readonly_hint(tmp_path) -> None:
    """Every tool must carry readOnlyHint=True so hosts can auto-allow reads."""
    mcp = server.build_server(_config(tmp_path))
    tools = await mcp.list_tools()
    for tool in tools:
        assert tool.annotations is not None, (
            f"Tool {tool.name!r} has no annotations"
        )
        assert tool.annotations.readOnlyHint is True, (
            f"Tool {tool.name!r} readOnlyHint is not True"
        )


async def test_all_tools_have_open_world_false(tmp_path) -> None:
    """All tools operate on the local workspace — openWorldHint must be False."""
    mcp = server.build_server(_config(tmp_path))
    tools = await mcp.list_tools()
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.openWorldHint is False, (
            f"Tool {tool.name!r} openWorldHint is not False"
        )


async def test_all_tools_have_title(tmp_path) -> None:
    """Every tool must have a human-readable title annotation."""
    mcp = server.build_server(_config(tmp_path))
    tools = await mcp.list_tools()
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.title, (
            f"Tool {tool.name!r} is missing a title annotation"
        )


# ---------------------------------------------------------------------------
# Input schema — Field descriptions at the schema boundary
# ---------------------------------------------------------------------------


async def test_project_status_schema_has_param_descriptions(tmp_path) -> None:
    """project and recent params must carry descriptions in the inputSchema."""
    mcp = server.build_server(_config(tmp_path))
    tools = await mcp.list_tools()
    tool = next(t for t in tools if t.name == "project_status")
    props = tool.inputSchema.get("properties", {})
    assert "description" in props.get("project", {}), "project param missing description"
    assert "description" in props.get("recent", {}), "recent param missing description"


async def test_memory_search_schema_has_param_descriptions(tmp_path) -> None:
    """query and scope params must carry descriptions in the inputSchema."""
    mcp = server.build_server(_config(tmp_path))
    tools = await mcp.list_tools()
    tool = next(t for t in tools if t.name == "memory_search")
    props = tool.inputSchema.get("properties", {})
    assert "description" in props.get("query", {}), "query param missing description"
    assert "description" in props.get("scope", {}), "scope param missing description"


async def test_list_agents_schema_has_param_descriptions(tmp_path) -> None:
    """project param must carry a description in the inputSchema."""
    mcp = server.build_server(_config(tmp_path))
    tools = await mcp.list_tools()
    tool = next(t for t in tools if t.name == "list_agents")
    props = tool.inputSchema.get("properties", {})
    assert "description" in props.get("project", {}), "project param missing description"


async def test_list_plans_schema_has_param_descriptions(tmp_path) -> None:
    """status and project params must carry descriptions in the inputSchema."""
    mcp = server.build_server(_config(tmp_path))
    tools = await mcp.list_tools()
    tool = next(t for t in tools if t.name == "list_plans")
    props = tool.inputSchema.get("properties", {})
    assert "description" in props.get("status", {}), "status param missing description"
    assert "description" in props.get("project", {}), "project param missing description"


# ---------------------------------------------------------------------------
# Schema-boundary validation — Pydantic rejects bad input before the handler
# ---------------------------------------------------------------------------


async def test_project_status_rejects_non_integer_recent(tmp_path) -> None:
    """Passing a non-integer for ``recent`` must fail at the schema boundary
    (Pydantic validation error surfaced as ToolError), not inside the handler.
    """
    mcp = server.build_server(_config(tmp_path))
    with pytest.raises(ToolError):
        await mcp.call_tool("project_status", {"project": "any", "recent": "bad"})


async def test_project_status_rejects_recent_below_minimum(tmp_path) -> None:
    """``recent`` has a ge=1 constraint; zero must be rejected at the schema boundary."""
    mcp = server.build_server(_config(tmp_path))
    with pytest.raises(ToolError):
        await mcp.call_tool("project_status", {"project": "any", "recent": 0})


async def test_project_status_rejects_recent_above_maximum(tmp_path) -> None:
    """``recent`` has a le=50 constraint; 51 must be rejected at the schema boundary."""
    mcp = server.build_server(_config(tmp_path))
    with pytest.raises(ToolError):
        await mcp.call_tool("project_status", {"project": "any", "recent": 51})
