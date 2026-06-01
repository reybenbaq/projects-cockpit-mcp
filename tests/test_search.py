"""Memory-search tests: matching, file scoping, truncation."""

from __future__ import annotations

from pathlib import Path

from cockpit import search


def test_finds_matches_across_memory_files(projects_root: Path) -> None:
    result = search.search_memory(projects_root, "widgets", max_hits=50)
    files = {hit.file for hit in result.hits}
    # MEMORY.md and feedback_widgets.md both mention widgets; README.md does not.
    assert any("MEMORY.md" in f for f in files)
    assert any("feedback_widgets.md" in f for f in files)
    assert result.truncated is False


def test_case_insensitive(projects_root: Path) -> None:
    assert search.search_memory(projects_root, "WIDGETS", max_hits=50).hits


def test_truncates_at_max_hits(projects_root: Path) -> None:
    result = search.search_memory(projects_root, "widgets", max_hits=1)
    assert len(result.hits) == 1
    assert result.truncated is True


def test_empty_query_returns_nothing(projects_root: Path) -> None:
    assert search.search_memory(projects_root, "", max_hits=50).hits == []


def test_scope_narrows_to_prefix(projects_root: Path) -> None:
    result = search.search_memory(projects_root, "widgets", max_hits=50, scope="feedback")
    files = {hit.file for hit in result.hits}
    assert files  # feedback_widgets.md matches
    assert all(Path(f).name.startswith("feedback") for f in files)
    assert not any("MEMORY.md" in f for f in files)


def test_skips_symlinked_memory_file(projects_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside_mem"
    outside.mkdir()
    (outside / "feedback_secret.md").write_text("widgets leak\n", encoding="utf-8")
    link = projects_root / "Project Alpha" / "memory" / "feedback_leak.md"
    link.symlink_to(outside / "feedback_secret.md")
    files = {h.file for h in search.search_memory(projects_root, "widgets", 50).hits}
    assert not any("feedback_leak.md" in f for f in files)
