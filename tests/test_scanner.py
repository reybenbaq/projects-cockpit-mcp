"""Scanner tests: project inventory, agent frontmatter, plan headers.

Tests that need the old flat-all-dirs behaviour pass ``require_markers=False``
explicitly. New tests for nested discovery and the marker gate use the
``config_markers`` fixture or pass ``require_markers=True``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cockpit import scanner
from cockpit.config import Config
from cockpit.exceptions import PathContainmentError


# ---------------------------------------------------------------------------
# Flat / backwards-compatible tests (require_markers=False)
# ---------------------------------------------------------------------------


def test_list_projects_skips_hidden_and_flags_features(projects_root: Path) -> None:
    """Core feature flags work correctly on a known marker-bearing project."""
    projects = {
        p.name: p
        for p in scanner.list_projects(projects_root, require_markers=False)
        if p.path in ("Project Alpha", "Project Beta")
    }
    assert "Project Alpha" in projects
    assert "Project Beta" in projects

    alpha = projects["Project Alpha"]
    assert alpha.has_agent is True
    assert alpha.plan_count == 2
    assert alpha.has_git is False
    assert alpha.is_dirty is None  # not a git repo
    assert alpha.path == "Project Alpha"

    beta = projects["Project Beta"]
    assert beta.has_agent is False
    assert beta.plan_count == 0


def test_list_agents_parses_frontmatter(projects_root: Path) -> None:
    agents = {
        a.name: a
        for a in scanner.list_agents(projects_root, require_markers=False)
    }
    assert "Alpha Agent" in agents
    agent = agents["Alpha Agent"]
    assert agent.description == "Does alpha things."
    assert agent.model == "sonnet"
    assert agent.project == "Project Alpha"


def test_list_agents_scoped_to_project(projects_root: Path) -> None:
    assert scanner.list_agents(projects_root, project="Project Beta") == []


def test_list_plans_reads_status_and_title(projects_root: Path) -> None:
    # Filter to only Alpha's plans to avoid coupling to the nested fixture.
    plans = {
        p.title: p
        for p in scanner.list_plans(projects_root, require_markers=False)
        if p.project == "Project Alpha"
    }
    assert set(plans) == {"Big Plan", "Done Plan"}
    assert plans["Big Plan"].status == "DRAFT"
    assert plans["Done Plan"].status == "IMPLEMENTED"
    assert plans["Big Plan"].project == "Project Alpha"


def test_list_plans_status_filter(projects_root: Path) -> None:
    drafts = scanner.list_plans(
        projects_root, status="draft", require_markers=False
    )
    draft_titles = [p.title for p in drafts]
    assert "Big Plan" in draft_titles
    # "Done Plan" must not appear in DRAFT results.
    assert "Done Plan" not in draft_titles


def test_list_projects_skips_symlinked_dir(projects_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside_proj"
    outside.mkdir()
    (projects_root / "Project Gamma").symlink_to(outside)
    names = {p.name for p in scanner.list_projects(projects_root, require_markers=False)}
    assert "Project Gamma" not in names
    assert "Project Alpha" in names


def test_list_agents_skips_symlinked_agent_file(
    projects_root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside_agent"
    outside.mkdir()
    (outside / "secret_agent.md").write_text(
        "---\nname: Secret\ndescription: leak\n---\n", encoding="utf-8"
    )
    agents_dir = projects_root / "Project Alpha" / ".claude" / "agents"
    (agents_dir / "evil.md").symlink_to(outside / "secret_agent.md")
    names = {a.name for a in scanner.list_agents(projects_root, require_markers=False)}
    assert "Secret" not in names
    assert "Alpha Agent" in names


# ---------------------------------------------------------------------------
# Nested discovery tests (require_markers=True, the production default)
# ---------------------------------------------------------------------------


def test_nested_project_is_discovered(projects_root: Path) -> None:
    """A qualified directory nested under a category dir must be returned."""
    paths = {p.path for p in scanner.list_projects(projects_root)}
    assert "Category/Nested Project" in paths


def test_marker_less_dirs_are_dropped_by_default(projects_root: Path) -> None:
    """``Project Beta`` has no markers; it must not appear when require_markers=True."""
    paths = {p.path for p in scanner.list_projects(projects_root)}
    assert "Project Beta" not in paths


def test_category_dir_without_own_markers_not_surfaced(projects_root: Path) -> None:
    """The bare ``Category`` dir carries no markers; only its child is surfaced."""
    paths = {p.path for p in scanner.list_projects(projects_root)}
    assert "Category" not in paths
    assert "Category/Nested Project" in paths


def test_parent_and_child_both_surfaced_when_both_qualify(
    projects_root: Path, tmp_path: Path
) -> None:
    """D2: when both a parent and nested child qualify, both must be emitted (no suppression)."""
    # Give the Category dir its own agent marker so it qualifies as a project.
    cat_agents = projects_root / "Category" / ".claude" / "agents"
    cat_agents.mkdir(parents=True, exist_ok=True)
    (cat_agents / "cat-agent.md").write_text(
        "---\nname: Cat Agent\n---\n", encoding="utf-8"
    )
    paths = {p.path for p in scanner.list_projects(projects_root)}
    assert "Category" in paths
    assert "Category/Nested Project" in paths


def test_nested_agent_has_relative_path(projects_root: Path) -> None:
    """Agent from a nested project emits the relative path, not just the leaf name."""
    agents = {a.name: a for a in scanner.list_agents(projects_root)}
    assert "Nested Agent" in agents
    assert agents["Nested Agent"].project == "Category/Nested Project"


def test_nested_plan_has_relative_path(projects_root: Path) -> None:
    """Plan from a nested project emits the relative path in the project field."""
    plans = {p.title: p for p in scanner.list_plans(projects_root)}
    assert "Nested Plan" in plans
    assert plans["Nested Plan"].project == "Category/Nested Project"


def test_nested_plan_status_filter(projects_root: Path) -> None:
    """Status filter works across both flat and nested projects."""
    in_progress = scanner.list_plans(projects_root, status="in progress")
    titles = [p.title for p in in_progress]
    assert "Nested Plan" in titles
    assert "Big Plan" not in titles


def test_capital_p_plans_dir_is_recognised(projects_root: Path) -> None:
    """``Plans/`` (capital-P) variant must be counted and returned."""
    capital_plans = projects_root / "Project Alpha" / "Plans"
    capital_plans.mkdir()
    (capital_plans / "Legacy Plan.md").write_text(
        "# Legacy Plan\n\n**Status:** DRAFT\n", encoding="utf-8"
    )
    plans = {p.title: p for p in scanner.list_plans(projects_root)}
    assert "Legacy Plan" in plans
    assert plans["Legacy Plan"].project == "Project Alpha"


def test_exclusion_dirs_not_yielded_as_projects(projects_root: Path) -> None:
    """Directories in the exclusion set must never surface as projects."""
    # Plant agent markers inside excluded dirs to confirm they are still skipped.
    for excluded in ("node_modules", ".venv", "tools"):
        ex_agents = projects_root / excluded / ".claude" / "agents"
        ex_agents.mkdir(parents=True, exist_ok=True)
        (ex_agents / "should-not-appear.md").write_text(
            "---\nname: Leak\n---\n", encoding="utf-8"
        )
    paths = {p.path for p in scanner.list_projects(projects_root)}
    for excluded in ("node_modules", ".venv", "tools"):
        assert excluded not in paths


def test_max_depth_limits_discovery(projects_root: Path) -> None:
    """Discovery must not return anything beyond ``max_depth`` levels."""
    # Depth 1 from root: only direct children.
    paths = {p.path for p in scanner.list_projects(projects_root, max_depth=1)}
    # "Category/Nested Project" is at depth 2 and must not appear.
    assert all("/" not in p for p in paths)


def test_depth_2_includes_nested(projects_root: Path) -> None:
    """With max_depth=2, L2 projects (one level inside a category) are included."""
    paths = {p.path for p in scanner.list_projects(projects_root, max_depth=2)}
    assert "Category/Nested Project" in paths


def test_require_markers_false_restores_flat_all_dirs(projects_root: Path) -> None:
    """``require_markers=False`` surfaces all non-excluded dirs including marker-less ones."""
    paths = {p.path for p in scanner.list_projects(projects_root, require_markers=False)}
    assert "Project Beta" in paths
    assert "Project Alpha" in paths
    assert "Category" in paths
    assert "Category/Nested Project" in paths


def test_project_info_path_field(projects_root: Path) -> None:
    """``ProjectInfo.path`` holds the relative path from root, not just the leaf name."""
    projects = {
        p.path: p for p in scanner.list_projects(projects_root, require_markers=False)
    }
    assert "Project Alpha" in projects
    assert projects["Project Alpha"].name == "Project Alpha"
    assert projects["Project Alpha"].path == "Project Alpha"
    # Nested project has a multi-segment path.
    assert "Category/Nested Project" in projects
    assert projects["Category/Nested Project"].name == "Nested Project"
    assert projects["Category/Nested Project"].path == "Category/Nested Project"


def test_scoped_list_agents_accepts_relative_path(projects_root: Path) -> None:
    """``list_agents`` with a multi-segment relative path resolves correctly."""
    agents = scanner.list_agents(projects_root, project="Category/Nested Project")
    assert len(agents) == 1
    assert agents[0].name == "Nested Agent"


def test_scoped_list_plans_accepts_relative_path(projects_root: Path) -> None:
    """``list_plans`` with a multi-segment relative path resolves correctly."""
    plans = scanner.list_plans(projects_root, project="Category/Nested Project")
    assert len(plans) == 1
    assert plans[0].title == "Nested Plan"
