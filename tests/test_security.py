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


def test_resolves_multi_segment_relative_path(projects_root: Path) -> None:
    """A two-segment path ``"Automation/SalesBot"`` must resolve to a child of root."""
    # Create the two-level path so resolve() finds a real dir.
    nested = projects_root / "Automation" / "SalesBot"
    nested.mkdir(parents=True)
    resolved = resolve_within(projects_root, "Automation/SalesBot")
    assert resolved == nested.resolve()


def test_multi_segment_traversal_is_rejected(projects_root: Path) -> None:
    """A path with ``..`` in a multi-segment input must be rejected."""
    with pytest.raises(PathContainmentError):
        resolve_within(projects_root, "GCP/../../../etc/passwd")


def test_multi_segment_absolute_is_rejected(projects_root: Path) -> None:
    """An absolute path embedded in a multi-segment input must be rejected."""
    with pytest.raises(PathContainmentError):
        resolve_within(projects_root, "/etc/passwd")


def test_absolute_path_inside_root_is_rejected(projects_root: Path) -> None:
    """An absolute path that points INSIDE ``projects_root`` must still be rejected.

    The relative-only contract forbids absolute inputs regardless of where they
    land after resolution — even a path that resolves to a child of the allowed
    root is not permitted if it is expressed as an absolute path.
    """
    # Construct an absolute path that resolves inside projects_root.
    inside = str((projects_root / "GCP").resolve())
    with pytest.raises(PathContainmentError):
        resolve_within(projects_root, inside)


def test_absolute_path_to_root_itself_is_rejected(projects_root: Path) -> None:
    """An absolute path equal to ``projects_root`` itself must be rejected."""
    with pytest.raises(PathContainmentError):
        resolve_within(projects_root, str(projects_root.resolve()))
