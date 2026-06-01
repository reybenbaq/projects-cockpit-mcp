"""Smoke tests: the server builds and registers exactly the expected tools."""

from __future__ import annotations

import subprocess
from pathlib import Path

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


async def test_project_status_non_git_dir_returns_tool_error(config: Config) -> None:
    """``project_status`` on a dir without a valid ``.git`` must raise ToolError,
    not propagate an uncaught git subprocess failure (no 500).
    """
    server = build_server(config)
    # "Project Beta" exists in the fixture but has no git repo.
    with pytest.raises(ToolError, match="does not contain a valid git repository"):
        await server.call_tool("project_status", {"project": "Project Beta"})


async def test_project_status_empty_git_dir_returns_tool_error(
    config: Config, projects_root
) -> None:
    """A directory with an empty (invalid) ``.git`` subdir must raise ToolError."""
    # Create a dir with only an empty .git — no HEAD file.
    broken = projects_root / "Broken Git"
    broken.mkdir()
    (broken / ".git").mkdir()
    server = build_server(config)
    with pytest.raises(ToolError, match="does not contain a valid git repository"):
        await server.call_tool("project_status", {"project": "Broken Git"})


def _init_git_repo(path: Path) -> None:
    """Initialise a minimal git repo with one commit at ``path``."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init", "-b", "main"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "T"], check=True, capture_output=True)
    (path / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "init"], check=True, capture_output=True)


async def test_project_status_echoes_relative_path_for_nested_project(
    config: Config, projects_root: Path
) -> None:
    """``project_status`` must echo the caller's relative path in the returned
    ``project`` field, not the bare leaf directory name.

    For a nested project at ``Category/Nested Repo``, the returned
    ``project`` must equal ``"Category/Nested Repo"``, not ``"Nested Repo"``.
    """
    nested = projects_root / "Category" / "Nested Repo"
    _init_git_repo(nested)
    srv = build_server(config)
    # call_tool returns (list[TextContent], structured_dict).
    _, structured = await srv.call_tool("project_status", {"project": "Category/Nested Repo"})
    assert structured["project"] == "Category/Nested Repo", (
        f"Expected 'Category/Nested Repo', got {structured['project']!r}"
    )


async def test_project_status_echoes_bare_name_for_l1_project(
    config: Config, projects_root: Path
) -> None:
    """For a top-level (L1) project, the echoed ``project`` equals the bare name."""
    flat = projects_root / "Flat Repo"
    _init_git_repo(flat)
    srv = build_server(config)
    _, structured = await srv.call_tool("project_status", {"project": "Flat Repo"})
    assert structured["project"] == "Flat Repo"
