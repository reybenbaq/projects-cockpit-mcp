"""Filesystem path-containment guard.

Every caller-supplied name (a project folder, a relative file path) is
resolved and checked against an allowed root before any read. This is the
single load-bearing defense against path traversal — without it a parameter
like ``../../etc`` or an absolute path would escape the configured tree.
"""

from __future__ import annotations

from pathlib import Path

from .exceptions import PathContainmentError


def resolve_within(root: Path, name: str) -> Path:
    """Resolve ``name`` under ``root`` and confirm it stays inside ``root``.

    ``name`` may be a single path segment (``"My Project"``) or a relative
    path. Absolute paths and any result that escapes ``root`` after symlink
    and ``..`` resolution are rejected.

    Raises:
        PathContainmentError: if the resolved path is not within ``root``.
    """
    name = name.strip()
    if not name or name in (".", ".."):
        raise PathContainmentError(f"invalid path name: {name!r}")
    if Path(name).is_absolute():
        raise PathContainmentError(
            f"path {name!r} resolves outside the allowed root"
        )
    root_resolved = root.resolve()
    candidate = (root_resolved / name).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise PathContainmentError(
            f"path {name!r} resolves outside the allowed root"
        )
    return candidate


def is_within(root: Path, path: Path) -> bool:
    """Return True if an already-resolved ``path`` sits inside ``root``."""
    root_resolved = root.resolve()
    resolved = path.resolve()
    return resolved == root_resolved or root_resolved in resolved.parents
