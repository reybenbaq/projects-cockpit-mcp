"""Structured output shapes for the cockpit tools.

FastMCP derives each tool's ``outputSchema`` from these dataclasses and emits
both ``structuredContent`` and a text mirror. Container dataclasses (rather
than bare lists) give every tool a named, self-describing top-level object.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProjectInfo:
    name: str
    path: str  # relative path from PROJECTS_ROOT, e.g. "Automation/SalesBot"
    has_agent: bool
    has_git: bool
    plan_count: int
    is_dirty: bool | None  # None when the project is not a git repo


@dataclass
class ProjectsResult:
    projects: list[ProjectInfo] = field(default_factory=list)


@dataclass
class AgentInfo:
    name: str
    project: str
    description: str
    model: str


@dataclass
class AgentsResult:
    agents: list[AgentInfo] = field(default_factory=list)


@dataclass
class PlanInfo:
    title: str
    status: str
    project: str
    path: str
    modified: str  # ISO-8601 date (UTC)


@dataclass
class PlansResult:
    plans: list[PlanInfo] = field(default_factory=list)


@dataclass
class CommitInfo:
    sha: str
    subject: str
    author: str
    date: str  # ISO-8601 from git


@dataclass
class ProjectStatus:
    project: str
    branch: str
    is_dirty: bool
    uncommitted_count: int
    ahead: int
    behind: int
    recent_commits: list[CommitInfo] = field(default_factory=list)


@dataclass
class SearchHit:
    file: str
    line_number: int
    snippet: str


@dataclass
class SearchResult:
    query: str
    hits: list[SearchHit] = field(default_factory=list)
    truncated: bool = False
