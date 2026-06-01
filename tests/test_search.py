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


def test_dot_claude_agent_memory_is_searched(projects_root: Path) -> None:
    """Memory files under .claude/agent-memory/ paths MUST be found.

    .claude is a hidden (dot-prefixed) directory. The walk must NOT prune it
    by the hidden-dir convention — agent memory lives exclusively under these
    paths and pruning them yields 0 hits for every real workspace query.
    """
    mem_dir = projects_root / "SomeProject" / ".claude" / "agent-memory" / "x"
    mem_dir.mkdir(parents=True)
    (mem_dir / "project_context.md").write_text(
        "unique_token_zq7x99 lives here\n", encoding="utf-8"
    )
    result = search.search_memory(projects_root, "unique_token_zq7x99", max_hits=50)
    found = [h.file for h in result.hits]
    assert found, (
        ".claude/agent-memory paths are being pruned — memory search returns 0 hits "
        "for the entire real agent memory corpus"
    )
    assert any(".claude" in f for f in found)


def test_excluded_dirs_are_not_descended(projects_root: Path) -> None:
    """Excluded directories (``.venv``, ``node_modules``, etc.) must not be
    descended into, so files inside them are never matched even when their
    names match the memory conventions.
    """
    # Plant a feedback file inside an excluded dir — it must not surface.
    venv_mem = projects_root / "Project Alpha" / ".venv" / "lib"
    venv_mem.mkdir(parents=True)
    (venv_mem / "feedback_venv_leak.md").write_text(
        "widgets inside venv\n", encoding="utf-8"
    )
    node_mem = projects_root / "Project Beta" / "node_modules" / "some-pkg"
    node_mem.mkdir(parents=True)
    (node_mem / "feedback_node_leak.md").write_text(
        "widgets inside node_modules\n", encoding="utf-8"
    )
    files = {h.file for h in search.search_memory(projects_root, "widgets", 50).hits}
    assert not any("feedback_venv_leak" in f for f in files)
    assert not any("feedback_node_leak" in f for f in files)
    # Normal memory files should still be found.
    assert any("feedback_widgets.md" in f for f in files)
