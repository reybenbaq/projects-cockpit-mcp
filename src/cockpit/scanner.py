"""Read-only filesystem scans over the projects tree.

Discovers projects, agent definitions, and plan documents. All git calls go
through :mod:`cockpit.gitinfo`; this module owns only directory/file walking
and the small amount of frontmatter / header parsing those artifacts need.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterator
from pathlib import Path

from . import gitinfo
from .exceptions import GitError
from .models import AgentInfo, PlanInfo, ProjectInfo
from .security import is_within, resolve_within

logger = logging.getLogger(__name__)

_AGENT_GLOB = ".claude/agents/*.md"
_PLAN_DIRS = ("plans and validations", "implemented plans")


def list_projects(projects_root: Path) -> list[ProjectInfo]:
    """Return one ``ProjectInfo`` per top-level directory under the root."""
    projects: list[ProjectInfo] = []
    for entry in sorted(_iter_dirs(projects_root)):
        has_git = gitinfo.is_git_repo(entry)
        projects.append(
            ProjectInfo(
                name=entry.name,
                has_agent=_has_agent(entry),
                has_git=has_git,
                plan_count=_plan_count(entry),
                is_dirty=_safe_is_dirty(entry) if has_git else None,
            )
        )
    return projects


def list_agents(projects_root: Path, project: str | None = None) -> list[AgentInfo]:
    """Return agent definitions across all projects, or within one project."""
    roots = (
        [resolve_within(projects_root, project)]
        if project
        else list(_iter_dirs(projects_root))
    )
    agents: list[AgentInfo] = []
    for proj_dir in sorted(roots):
        for agent_file in sorted(proj_dir.glob(_AGENT_GLOB)):
            if not is_within(projects_root, agent_file):
                continue  # a symlink that escapes the root
            front = _read_frontmatter(agent_file)
            agents.append(
                AgentInfo(
                    name=front.get("name", agent_file.stem),
                    project=proj_dir.name,
                    description=front.get("description", ""),
                    model=front.get("model", ""),
                )
            )
    return agents


def list_plans(
    projects_root: Path,
    status: str | None = None,
    project: str | None = None,
) -> list[PlanInfo]:
    """Return plan documents, optionally filtered by status and/or project."""
    roots = (
        [resolve_within(projects_root, project)]
        if project
        else list(_iter_dirs(projects_root))
    )
    plans: list[PlanInfo] = []
    for proj_dir in sorted(roots):
        for plan_dir_name in _PLAN_DIRS:
            plan_dir = proj_dir / plan_dir_name
            if not plan_dir.is_dir():
                continue
            for plan_file in sorted(plan_dir.glob("*.md")):
                if not is_within(projects_root, plan_file):
                    continue  # a symlink that escapes the root
                plans.append(_read_plan(plan_file, proj_dir.name))
    if status:
        wanted = status.upper()
        plans = [p for p in plans if p.status.upper() == wanted]
    return plans


# --- internals ---------------------------------------------------------------


def _iter_dirs(root: Path) -> Iterator[Path]:
    """Yield real (non-symlink) top-level directories, skipping hidden ones.

    Symlinks are skipped so a link planted inside the tree cannot redirect a
    scan outside ``root`` — the containment guarantee ``resolve_within`` gives
    explicit project arguments must also hold for discovery.
    """
    for p in root.iterdir():
        if p.is_dir() and not p.is_symlink() and not p.name.startswith("."):
            yield p


def _has_agent(project_dir: Path) -> bool:
    return any(project_dir.glob(_AGENT_GLOB))


def _plan_count(project_dir: Path) -> int:
    total = 0
    for plan_dir_name in _PLAN_DIRS:
        plan_dir = project_dir / plan_dir_name
        if plan_dir.is_dir():
            total += sum(1 for _ in plan_dir.glob("*.md"))
    return total


def _safe_is_dirty(repo: Path) -> bool | None:
    try:
        return gitinfo.is_dirty(repo)
    except GitError:
        logger.warning("git status failed for %s", repo.name)
        return None


def _read_frontmatter(path: Path) -> dict[str, str]:
    """Parse simple ``key: value`` pairs from YAML frontmatter.

    Only the leading ``---`` fenced block is read, and only flat scalar keys
    are captured (the three keys this server needs). Deliberately not a full
    YAML parser — frontmatter is trusted local content, and a flat scan avoids
    a dependency and the ``yaml.load`` deserialization risk.
    """
    front: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return front
    if not lines or lines[0].strip() != "---":
        return front
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith((" ", "\t")) or ":" not in line:
            continue  # skip nested keys and non-key lines
        key, _, value = line.partition(":")
        value = value.strip().strip("'\"")
        # A bare block-scalar indicator (``>`` / ``|``) means the real value
        # spans indented lines this flat parser does not read; don't surface
        # the indicator as if it were the value.
        if value in (">", "|", ">-", "|-", ">+", "|+"):
            value = ""
        front[key.strip()] = value
    return front


def _read_plan(path: Path, project_name: str) -> PlanInfo:
    status = ""
    title = path.stem
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        lines = []
    for line in lines:
        stripped = line.strip()
        if title == path.stem and stripped.startswith("# "):
            title = stripped[2:].strip()
        if stripped.startswith("**Status:**"):
            status = stripped.split("**Status:**", 1)[1].strip()
            break
    return PlanInfo(
        title=title,
        status=status,
        project=project_name,
        path=str(path),
        modified=_mtime_iso(path),
    )


def _mtime_iso(path: Path) -> str:
    ts = path.stat().st_mtime
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date().isoformat()
