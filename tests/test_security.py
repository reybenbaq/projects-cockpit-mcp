"""Path-containment guard tests — the load-bearing traversal defense."""

from __future__ import annotations

from pathlib import Path

import pytest

from cockpit.exceptions import PathContainmentError
from cockpit.security import is_within, resolve_within


def test_resolves_valid_child(projects_root: Path) -> None:
    resolved = resolve_within(projects_root, "Project Alpha")
    assert resolved == (projects_root / "Project Alpha").resolve()


def test_rejects_parent_traversal(projects_root: Path) -> None:
    with pytest.raises(PathContainmentError):
        resolve_within(projects_root, "../secret")


def test_rejects_deep_traversal(projects_root: Path) -> None:
    with pytest.raises(PathContainmentError):
        resolve_within(projects_root, "Project Alpha/../../escape")


def test_rejects_absolute_path(projects_root: Path) -> None:
    with pytest.raises(PathContainmentError):
        resolve_within(projects_root, "/etc")


def test_rejects_symlink_escape(projects_root: Path, tmp_path: Path) -> None:
    # A symlink planted inside the root that points outside it must be rejected
    # once resolved — the subtlest traversal vector, not a string ``..``.
    outside = tmp_path / "outside_secret"
    outside.mkdir()
    (projects_root / "sneaky").symlink_to(outside)
    with pytest.raises(PathContainmentError):
        resolve_within(projects_root, "sneaky")


def test_rejects_empty_and_dot_names(projects_root: Path) -> None:
    for bad in ("", "   ", ".", ".."):
        with pytest.raises(PathContainmentError):
            resolve_within(projects_root, bad)


def test_is_within(projects_root: Path) -> None:
    assert is_within(projects_root, projects_root / "Project Alpha")
    assert not is_within(projects_root, projects_root.parent)
