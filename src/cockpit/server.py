"""FastMCP server wiring: tool registration, ASGI app assembly, entry point.

Tools are registered inside :func:`build_server` so they close over an
injected :class:`~cockpit.config.Config` — no environment is read on import,
which keeps the module importable in tests without a populated environment.
"""

from __future__ import annotations

import logging
import sys

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

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
    mcp = FastMCP(name="projects-cockpit", instructions=_INSTRUCTIONS)

    @mcp.tool()
    def list_projects() -> ProjectsResult:
        """List every project, flagging whether each has an agent, a git repo, plans, and uncommitted changes."""
        return ProjectsResult(projects=scanner.list_projects(config.projects_root))

    @mcp.tool()
    def list_agents(project: str | None = None) -> AgentsResult:
        """List Claude subagent definitions across all projects, or within one named project."""
        try:
            return AgentsResult(
                agents=scanner.list_agents(config.projects_root, project)
            )
        except CockpitError as e:
            raise ToolError(str(e)) from e

    @mcp.tool()
    def list_plans(
        status: str | None = None, project: str | None = None
    ) -> PlansResult:
        """List plan documents and their lifecycle status (DRAFT, APPROVED, IN PROGRESS, IMPLEMENTED, BLOCKED). Optionally filter by status and/or project."""
        try:
            return PlansResult(
                plans=scanner.list_plans(config.projects_root, status, project)
            )
        except CockpitError as e:
            raise ToolError(str(e)) from e

    @mcp.tool()
    def project_status(project: str, recent: int = 5) -> ProjectStatus:
        """Report git status for one project: current branch, dirty state, ahead/behind vs upstream, and the most recent commits."""
        try:
            repo = resolve_within(config.projects_root, project)
            return gitinfo.get_status(repo, recent=recent)
        except CockpitError as e:
            raise ToolError(str(e)) from e

    @mcp.tool()
    def memory_search(query: str, scope: str | None = None) -> SearchResult:
        """Search memory markdown files (MEMORY.md, feedback_*, reference_*, project_*, user_*) for a case-insensitive substring. Pass scope (e.g. "feedback", "reference") to search only files whose name starts with that prefix."""
        return search.search_memory(
            config.memory_root, query, config.max_search_hits, scope
        )

    return mcp


def build_app(config: Config) -> SecurityMiddleware:
    """Build the streamable-HTTP ASGI app wrapped with Origin + bearer auth."""
    mcp = build_server(config)
    app = mcp.streamable_http_app()
    return SecurityMiddleware(
        app, token=config.token, allowed_origins=config.allowed_origins
    )


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
