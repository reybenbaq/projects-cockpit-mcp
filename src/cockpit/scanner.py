"""Read-only filesystem scans over the projects tree.

Discovers projects, agent definitions, and plan documents. All git calls go
through :mod:`cockpit.gitinfo`; this module owns only directory/file walking
and the small amount of frontmatter / header parsing those artifacts need.

Discovery is marker-based and recursive (capped at ``max_depth``). A directory
qualifies as a project when it carries at least one of the following markers:

- ``.claude/agents/`` with ≥ 1 ``*.md`` file
- A valid ``.git`` repository (``.git/HEAD`` is a regular file)
- A ``plans and validations/`` subdirectory
- An ``implemented plans/`` subdirectory
- A ``Plans/`` subdirectory (legacy capital-P variant)

When ``require_markers`` is ``False``, every non-excluded, non-hidden
subdirectory is returned regardless of markers, restoring the old flat-all-dirs
behaviour (useful for demo / CI environments with minimal fixture trees).

Both a parent directory and a nested child may qualify simultaneously (D2): no
suppression is applied. Each is emitted as a distinct project with a
path-qualified name so callers can distinguish e.g. ``GCP/Reviews Bot`` from a
hypothetical ``Client/Reviews Bot``.
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
_PLAN_DIRS = ("plans and validations", "implemented plans", "Plans")

# Directories never yielded as projects and never descended into during
# discovery. Hidden dirs (leading ```.``) are also skipped implicitly.
_DISCOVERY_EXCLUDED: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".build",
        "secrets.local",
        "tools",
        "vendor-docs",
        "audit",
        "meta-architecture",
    }
)


# ---------------------------------------------------------------------------
# Public scan helpers
# ---------------------------------------------------------------------------


def list_projects(
    projects_root: Path,
    max_depth: int = 3,
    require_markers: bool = True,
) -> list[ProjectInfo]:
    """Return one ``ProjectInfo`` per discovered project directory.

    Projects are discovered by :func:`_iter_project_dirs`: marker-based,
    recursive up to ``max_depth``, with exclusions applied at every level.
    Both parent and nested child directories may appear simultaneously (D2).
    """
    projects: list[ProjectInfo] = []
    for entry, rel_path in sorted(
        _iter_project_dirs(projects_root, max_depth, require_markers),
        key=lambda t: t[1],
    ):
        has_git = gitinfo.is_git_repo(entry)
        projects.append(
            ProjectInfo(
                name=entry.name,
                path=rel_path,
                has_agent=_has_agent(entry),
                has_git=has_git,
                plan_count=_plan_count(entry),
                is_dirty=_safe_is_dirty(entry) if has_git else None,
            )
        )
    return projects


def list_agents(
    projects_root: Path,
    project: str | None = None,
    max_depth: int = 3,
    require_markers: bool = True,
) -> list[AgentInfo]:
    """Return agent definitions across all projects, or within one project."""
    if project:
        roots = [(resolve_within(projects_root, project), project)]
    else:
        roots = list(
            _iter_project_dirs(projects_root, max_depth, require_markers)
        )

    agents: list[AgentInfo] = []
    for proj_dir, rel_path in sorted(roots, key=lambda t: t[1]):
        for agent_file in sorted(proj_dir.glob(_AGENT_GLOB)):
            if not is_within(projects_root, agent_file):
                continue  # a symlink that escapes the root
            front = _read_frontmatter(agent_file)
            agents.append(
                AgentInfo(
                    name=front.get("name", agent_file.stem),
                    project=rel_path,
                    description=front.get("description", ""),
                    model=front.get("model", ""),
                )
            )
    return agents


def list_plans(
    projects_root: Path,
    status: str | None = None,
    project: str | None = None,
    max_depth: int = 3,
    require_markers: bool = True,
) -> list[PlanInfo]:
    """Return plan documents, optionally filtered by status and/or project."""
    if project:
        roots = [(resolve_within(projects_root, project), project)]
    else:
        roots = list(
            _iter_project_dirs(projects_root, max_depth, require_markers)
        )

    plans: list[PlanInfo] = []
    for proj_dir, rel_path in sorted(roots, key=lambda t: t[1]):
        for plan_dir_name in _PLAN_DIRS:
            plan_dir = proj_dir / plan_dir_name
            if not plan_dir.is_dir():
                continue
            for plan_file in sorted(plan_dir.glob("*.md")):
                if not is_within(projects_root, plan_file):
                    continue  # a symlink that escapes the root
                plans.append(_read_plan(plan_file, rel_path))
    if status:
        wanted = status.upper()
        plans = [p for p in plans if p.status.upper() == wanted]
    return plans


# ---------------------------------------------------------------------------
# Core discovery
# ---------------------------------------------------------------------------


def _qualifies_as_project(path: Path) -> bool:
    """Return True if ``path`` carries at least one project marker.

    Markers (checked in cheapest-first order):
    1. Any of the ``_PLAN_DIRS`` subdirectories exists.
    2. A valid ``.git`` repo (``.git/HEAD`` is a file).
    3. At least one ``*.md`` file under ``.claude/agents/``.
    """
    for plan_dir_name in _PLAN_DIRS:
        if (path / plan_dir_name).is_dir():
            return True
    if gitinfo.is_git_repo(path):
        return True
    if any(path.glob(_AGENT_GLOB)):
        return True
    return False


def _iter_project_dirs(
    root: Path,
    max_depth: int,
    require_markers: bool,
    _scan_root: Path | None = None,
    _current_depth: int = 0,
) -> Iterator[tuple[Path, str]]:
    """Recursively yield ``(absolute_path, relative_path_str)`` for project dirs.

    ``relative_path_str`` is always relative to the original ``root`` passed
    by the caller (the ``PROJECTS_ROOT``), not the current recursion directory.
    ``_scan_root`` tracks the original root across recursive calls.

    Rules applied at every depth level:
    - Hidden directories (name starts with ``"."``) are skipped and not
      descended into.
    - Symlinked directories are skipped and not descended into (prevents
      loops and escapes from ``root``).
    - Directories in ``_DISCOVERY_EXCLUDED``, names starting with ``_``, or
      matching the ``sba-corpus-research*`` prefix are skipped.
    - When ``require_markers`` is ``True``, a directory is only yielded if
      :func:`_qualifies_as_project` returns True; however, its children are
      still recursed (a non-qualifying parent may contain qualifying children).
    - When ``require_markers`` is ``False``, every non-excluded, non-hidden
      directory is yielded.
    - Recursion stops when ``_current_depth >= max_depth``.
    """
    if _current_depth >= max_depth:
        return

    # On the first call, record the original root so recursive calls can
    # compute paths relative to it.
    original_root = _scan_root if _scan_root is not None else root

    try:
        entries = sorted(root.iterdir())
    except PermissionError:
        logger.debug("Permission denied listing %s", root)
        return

    for entry in entries:
        name = entry.name

        # Skip hidden dirs, symlinks, and excluded names.
        if name.startswith("."):
            continue
        if entry.is_symlink():
            continue
        if not entry.is_dir():
            continue
        if (
            name in _DISCOVERY_EXCLUDED
            or name.startswith("_")
            or name.startswith("sba-corpus-research")
        ):
            continue

        # Compute the relative path from the original root for display + tool input.
        try:
            rel = str(entry.relative_to(original_root))
        except ValueError:
            continue

        if require_markers:
            if _qualifies_as_project(entry):
                yield entry, rel
            # Always recurse regardless of whether this dir qualifies,
            # so nested children are not missed.
            yield from _iter_project_dirs(
                entry, max_depth, require_markers, original_root, _current_depth + 1
            )
        else:
            yield entry, rel
            yield from _iter_project_dirs(
                entry, max_depth, require_markers, original_root, _current_depth + 1
            )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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


def _read_plan(path: Path, project_rel_path: str) -> PlanInfo:
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
        project=project_rel_path,
        path=str(path),
        modified=_mtime_iso(path),
    )


def _mtime_iso(path: Path) -> str:
    ts = path.stat().st_mtime
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date().isoformat()
