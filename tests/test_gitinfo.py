"""Git-inspection tests against real temporary repositories.

These exercise the behavior smoke tests cannot: ahead/behind ordering, the
no-upstream neutral case, the unit-separator-in-subject parse, and the recent
clamp. Each test builds a throwaway repo with a local identity so it never
touches the developer's global git config.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cockpit import gitinfo


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A repo on branch ``main`` with one commit and a local identity."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "first commit")
    return repo


def test_is_git_repo(git_repo: Path) -> None:
    assert gitinfo.is_git_repo(git_repo) is True
    assert gitinfo.is_git_repo(git_repo.parent) is False


def test_empty_dot_git_dir_is_rejected(tmp_path: Path) -> None:
    """An empty ``.git`` directory must not be treated as a valid repo.

    The old ``.exists()`` check returned True for empty dirs, causing
    ``git rev-parse`` to fail with an uncaught error. The new check requires
    ``.git/HEAD`` to be a regular file.
    """
    fake = tmp_path / "fake_repo"
    fake.mkdir()
    (fake / ".git").mkdir()  # empty .git dir — no HEAD file
    assert gitinfo.is_git_repo(fake) is False


def test_clean_repo_status(git_repo: Path) -> None:
    status = gitinfo.get_status(git_repo)
    assert status.branch == "main"
    assert status.is_dirty is False
    assert status.uncommitted_count == 0
    assert (status.ahead, status.behind) == (0, 0)
    assert len(status.recent_commits) == 1
    commit = status.recent_commits[0]
    assert commit.subject == "first commit"
    assert commit.author == "Test User"
    assert commit.sha  # short hash present


def test_dirty_repo_is_flagged(git_repo: Path) -> None:
    (git_repo / "untracked.txt").write_text("x", encoding="utf-8")
    assert gitinfo.is_dirty(git_repo) is True
    status = gitinfo.get_status(git_repo)
    assert status.is_dirty is True
    assert status.uncommitted_count >= 1


def test_no_upstream_is_neutral(git_repo: Path) -> None:
    # No remote/upstream is configured — this is neutral, not an error.
    assert gitinfo._ahead_behind(git_repo) == (0, 0)


def test_subject_with_unit_separator_is_preserved(git_repo: Path) -> None:
    # A commit subject containing the field delimiter must not corrupt parsing
    # or shift the author/date columns — the regression the format reorder fixes.
    weird = "fix\x1fweird subject"
    _git(git_repo, "commit", "--allow-empty", "-m", weird)
    status = gitinfo.get_status(git_repo, recent=1)
    assert len(status.recent_commits) == 1
    assert status.recent_commits[0].subject == weird
    assert status.recent_commits[0].author == "Test User"


def test_recent_is_clamped_and_zero_yields_empty(git_repo: Path) -> None:
    for i in range(3):
        _git(git_repo, "commit", "--allow-empty", "-m", f"extra {i}")
    assert len(gitinfo._recent_commits(git_repo, 10_000)) <= gitinfo._MAX_RECENT
    assert gitinfo._recent_commits(git_repo, 0) == []
