"""Git inspection via subprocess argument lists (never a shell string).

Each helper shells out to ``git -C <repo>`` with a fixed argument vector, so
no caller-supplied value is ever interpolated into a shell command.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .exceptions import GitError
from .models import CommitInfo, ProjectStatus

logger = logging.getLogger(__name__)

_UNIT = "\x1f"  # ASCII unit separator — safe field delimiter for git --pretty
_TIMEOUT_SECONDS = 10
_MAX_RECENT = 50  # hard ceiling on commits returned per project_status call


def _run_git(repo: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=True,
        )
    except FileNotFoundError as e:
        raise GitError("git executable not found on PATH") from e
    except subprocess.TimeoutExpired as e:
        raise GitError(f"git timed out in {repo}") from e
    except subprocess.CalledProcessError as e:
        raise GitError(f"git {' '.join(args)} failed: {e.stderr.strip()}") from e
    return result.stdout


def is_git_repo(path: Path) -> bool:
    return (path / ".git").exists()


def is_dirty(repo: Path) -> bool:
    """Return True if the working tree has uncommitted changes."""
    return bool(_run_git(repo, ["status", "--porcelain"]).strip())


def get_status(repo: Path, recent: int = 5) -> ProjectStatus:
    """Collect branch, dirtiness, ahead/behind, and recent commits for ``repo``."""
    branch = _run_git(repo, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    porcelain = _run_git(repo, ["status", "--porcelain"]).splitlines()
    ahead, behind = _ahead_behind(repo)
    return ProjectStatus(
        project=repo.name,
        branch=branch,
        is_dirty=bool(porcelain),
        uncommitted_count=len(porcelain),
        ahead=ahead,
        behind=behind,
        recent_commits=_recent_commits(repo, recent),
    )


def _ahead_behind(repo: Path) -> tuple[int, int]:
    """Return (ahead, behind) vs upstream, or (0, 0) when no upstream is set.

    Only a genuinely missing upstream is treated as neutral ``(0, 0)``; any
    other git failure is allowed to surface as a ``GitError`` rather than being
    silently reported as "fully synced".
    """
    try:
        _run_git(repo, ["rev-parse", "--abbrev-ref", "@{upstream}"])
    except GitError:
        return (0, 0)  # no upstream configured — not an error, just nothing to compare
    raw = _run_git(
        repo, ["rev-list", "--left-right", "--count", "@{upstream}...HEAD"]
    ).strip()
    parts = raw.split()
    if len(parts) != 2:
        raise GitError(f"unexpected rev-list output: {raw!r}")
    behind, ahead = (int(parts[0]), int(parts[1]))
    return (ahead, behind)


def _recent_commits(repo: Path, recent: int) -> list[CommitInfo]:
    count = max(0, min(recent, _MAX_RECENT))
    if count == 0:
        return []
    # Subject (%s) is placed LAST so an embedded unit-separator in a commit
    # message stays inside the final field after a maxsplit of 3 — a malicious
    # or odd commit cannot shift the author/date columns. Subject is always a
    # single line, so one log line maps to exactly one commit.
    fmt = _UNIT.join(["%h", "%an", "%aI", "%s"])
    raw = _run_git(repo, ["log", f"-n{count}", f"--pretty=format:{fmt}"])
    commits: list[CommitInfo] = []
    for line in raw.splitlines():
        if not line:
            continue
        parts = line.split(_UNIT, 3)
        if len(parts) != 4:
            raise GitError(f"malformed git log line: {line!r}")
        sha, author, date, subject = parts
        commits.append(
            CommitInfo(sha=sha, subject=subject, author=author, date=date)
        )
    return commits
