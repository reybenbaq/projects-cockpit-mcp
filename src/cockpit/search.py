"""Pure-Python, read-only grep over memory-style markdown files.

Avoids a ``ripgrep`` dependency so the container needs no extra binary. Only
files whose names match the memory conventions are read, keeping the scan
scoped and fast even when ``memory_root`` is a large tree.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

from .models import SearchHit, SearchResult
from .security import is_within

logger = logging.getLogger(__name__)

# Memory-file name conventions: exact names and prefixes (all ``.md``).
_EXACT_NAMES = frozenset({"MEMORY.md", "MEMORY_ARCHIVE.md", "MEMORY_DOMAINS.md"})
_PREFIXES = ("feedback", "reference", "project", "user", "algorithm_decisions")
_SNIPPET_MAX = 200


def search_memory(
    memory_root: Path,
    query: str,
    max_hits: int,
    scope: str | None = None,
) -> SearchResult:
    """Return line-level matches for ``query`` (case-insensitive substring).

    ``scope`` optionally narrows the search to memory files whose name starts
    with that prefix (e.g. ``"feedback"``, ``"reference"``), case-insensitive.
    When unset, every memory-convention file under ``memory_root`` is searched.
    """
    needle = query.casefold()
    if not needle:
        return SearchResult(query=query, hits=[], truncated=False)

    hits: list[SearchHit] = []
    truncated = False
    for path in sorted(_iter_memory_files(memory_root, scope)):
        if truncated:
            break
        for line_number, snippet in _matches_in_file(path, needle):
            if len(hits) >= max_hits:
                truncated = True
                break
            hits.append(
                SearchHit(
                    file=str(path.relative_to(memory_root)),
                    line_number=line_number,
                    snippet=snippet,
                )
            )
    return SearchResult(query=query, hits=hits, truncated=truncated)


def _iter_memory_files(memory_root: Path, scope: str | None = None) -> Iterator[Path]:
    scope_lower = scope.lower() if scope else None
    for path in memory_root.rglob("*.md"):
        if path.is_symlink() or not path.is_file():
            continue
        if not is_within(memory_root, path):
            continue  # rglob may descend into a symlinked dir pointing outside
        name = path.name
        if not (name in _EXACT_NAMES or name.startswith(_PREFIXES)):
            continue
        if scope_lower and not name.lower().startswith(scope_lower):
            continue
        yield path


def _matches_in_file(path: Path, needle: str) -> Iterator[tuple[int, str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        logger.debug("Skipped unreadable file: %s", path)
        return
    for index, line in enumerate(text.splitlines(), start=1):
        if needle in line.casefold():
            yield index, line.strip()[:_SNIPPET_MAX]
