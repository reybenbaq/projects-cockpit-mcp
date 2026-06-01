"""FastMCP server wiring: tool registration, ASGI app assembly, entry point.

Tools are registered inside :func:`build_server` so they close over an
injected :class:`~cockpit.config.Config` — no environment is read on import,
which keeps the module importable in tests without a populated environment.
"""

from __future__ import annotations

import logging
import sys

import anyio.to_thread
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from . import gitinfo, scanner, search
from .config import Config, load_config
from .exceptions import CockpitError, ConfigError
from .middleware import SecurityMiddleware
from .models import (
    AgentsResult,
    PlansResult,
    ProjectsResult,
    ProjectStatus,
    SearchResult,
)
from .security import resolve_within

logger = logging.getLogger(__name__)

_INSTRUCTIONS = (
    "Read-only cockpit over a multi-project Claude Code workspace. Lists "
    "projects, subagent definitions, and plan documents; reports git status "
    "per project; and searches memory markdown. Every tool is read-only."
)


def build_server(config: Config) -> FastMCP:
    """Create the FastMCP server with all tools bound to ``config``."""
    # Configure the transport-layer DNS-rebinding guard (Host + Origin
    # validation, MCP overlay §6/§11.1) explicitly rather than leaning on
    # FastMCP's implicit localhost auto-enable. The implicit path keys off the
    # FastMCP constructor's host, which never sees the container's 0.0.0.0
    # bind, so it would silently pin the allow-list to loopback and 421 any
    # other access path. Setting it from config makes the posture visible,
    # intentional, and stable regardless of the bind interface.
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=sorted(config.allowed_hosts),
        allowed_origins=sorted(config.allowed_origins),
    )
    mcp = FastMCP(
        name="projects-cockpit",
        instructions=_INSTRUCTIONS,
        transport_security=transport_security,
    )

    # Every tool does blocking I/O: filesystem walks and git subprocesses. The
    # SDK invokes a sync tool directly on the event loop (no worker offload), so
    # a slow scan would starve every other in-flight request. Each tool is async
    # and pushes its blocking work to a thread via anyio.to_thread.run_sync
    # (mcp_standards.md §15 Common Pitfalls).

    @mcp.tool()
    async def list_projects() -> ProjectsResult:
        """List every project, flagging whether each has an agent, a git repo, plans, and uncommitted changes."""

        def _list() -> list:
            return scanner.list_projects(
                config.projects_root,
                max_depth=config.max_discovery_depth,
                require_markers=config.require_markers,
            )

        projects = await anyio.to_thread.run_sync(_list)
        return ProjectsResult(projects=projects)

    @mcp.tool()
    async def list_agents(project: str | None = None) -> AgentsResult:
        """List Claude subagent definitions across all projects, or within one named project.

        ``project`` accepts either a leaf name (``"My Project"``) or a
        relative path from ``PROJECTS_ROOT`` (``"GCP/Reviews Bot"``).
        """
        try:

            def _list() -> list:
                return scanner.list_agents(
                    config.projects_root,
                    project=project,
                    max_depth=config.max_discovery_depth,
                    require_markers=config.require_markers,
                )

            agents = await anyio.to_thread.run_sync(_list)
            return AgentsResult(agents=agents)
        except CockpitError as e:
            raise ToolError(str(e)) from e

    @mcp.tool()
    async def list_plans(
        status: str | None = None, project: str | None = None
    ) -> PlansResult:
        """List plan documents and their lifecycle status (DRAFT, APPROVED, IN PROGRESS, IMPLEMENTED, BLOCKED). Optionally filter by status and/or project.

        ``project`` accepts either a leaf name or a relative path from
        ``PROJECTS_ROOT`` (e.g. ``"GCP/Reviews Bot"``).
        """
        try:

            def _list() -> list:
                return scanner.list_plans(
                    config.projects_root,
                    status=status,
                    project=project,
                    max_depth=config.max_discovery_depth,
                    require_markers=config.require_markers,
                )

            plans = await anyio.to_thread.run_sync(_list)
            return PlansResult(plans=plans)
        except CockpitError as e:
            raise ToolError(str(e)) from e

    @mcp.tool()
    async def project_status(project: str, recent: int = 5) -> ProjectStatus:
        """Report git status for one project: current branch, dirty state, ahead/behind vs upstream, and the most recent commits.

        ``project`` accepts either a leaf name or a relative path from
        ``PROJECTS_ROOT`` (e.g. ``"GCP/Reviews Bot"``).
        """

        def _status() -> ProjectStatus:
            repo = resolve_within(config.projects_root, project)
            if not gitinfo.is_git_repo(repo):
                raise CockpitError(
                    f"project {project!r} does not contain a valid git repository"
                )
            status = gitinfo.get_status(repo, recent=recent)
            # Echo the caller's normalized input, not the leaf directory name.
            # For nested projects (e.g. "GCP/Reviews Bot") this ensures the
            # returned `project` field matches the path the caller passed rather
            # than surfacing only the leaf ("Reviews Bot").  For L1 projects the
            # leaf name and the input are the same, so this is a no-op in that
            # case.
            status.project = project.strip()
            return status

        try:
            return await anyio.to_thread.run_sync(_status)
        except CockpitError as e:
            raise ToolError(str(e)) from e

    @mcp.tool()
    async def memory_search(query: str, scope: str | None = None) -> SearchResult:
        """Search memory markdown files (MEMORY.md, feedback_*, reference_*, project_*, user_*) for a case-insensitive substring. Pass scope (e.g. "feedback", "reference") to search only files whose name starts with that prefix."""
        return await anyio.to_thread.run_sync(
            search.search_memory,
            config.memory_root,
            query,
            config.max_search_hits,
            scope,
        )

    return mcp


def build_app(config: Config) -> SecurityMiddleware:
    """Build the streamable-HTTP ASGI app wrapped with bearer-token auth.

    Host and Origin validation (DNS-rebinding defense) is owned by the FastMCP
    transport layer, configured in :func:`build_server`. This wrapper adds the
    one control the transport layer does not provide: a static bearer token.
    """
    mcp = build_server(config)
    app = mcp.streamable_http_app()
    return SecurityMiddleware(app, token=config.token)


def main() -> None:
    try:
        config = load_config()
    except ConfigError as e:
        print(f"projects-cockpit: {e}", file=sys.stderr)
        raise SystemExit(1) from e
    logging.basicConfig(
        stream=sys.stderr,
        level=config.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info(
        "Starting projects-cockpit on %s:%s (projects_root=%s)",
        config.host,
        config.port,
        config.projects_root,
    )
    uvicorn.run(
        build_app(config),
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
    )


if __name__ == "__main__":
    main()
