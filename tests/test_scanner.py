"""Scanner tests: project inventory, agent frontmatter, plan headers."""

from __future__ import annotations

from pathlib import Path

from cockpit import scanner


def test_list_projects_skips_hidden_and_flags_features(projects_root: Path) -> None:
    projects = {p.name: p for p in scanner.list_projects(projects_root)}
    assert set(projects) == {"Project Alpha", "Project Beta"}

    alpha = projects["Project Alpha"]
    assert alpha.has_agent is True
    assert alpha.plan_count == 2
    assert alpha.has_git is False
    assert alpha.is_dirty is None  # not a git repo

    beta = projects["Project Beta"]
    assert beta.has_agent is False
    assert beta.plan_count == 0


def test_list_agents_parses_frontmatter(projects_root: Path) -> None:
    agents = scanner.list_agents(projects_root)
    assert len(agents) == 1
    agent = agents[0]
    assert agent.name == "Alpha Agent"
    assert agent.description == "Does alpha things."
    assert agent.model == "sonnet"
    assert agent.project == "Project Alpha"


def test_list_agents_scoped_to_project(projects_root: Path) -> None:
    assert scanner.list_agents(projects_root, project="Project Beta") == []


def test_list_plans_reads_status_and_title(projects_root: Path) -> None:
    plans = {p.title: p for p in scanner.list_plans(projects_root)}
    assert set(plans) == {"Big Plan", "Done Plan"}
    assert plans["Big Plan"].status == "DRAFT"
    assert plans["Done Plan"].status == "IMPLEMENTED"
    assert plans["Big Plan"].project == "Project Alpha"


def test_list_plans_status_filter(projects_root: Path) -> None:
    drafts = scanner.list_plans(projects_root, status="draft")
    assert [p.title for p in drafts] == ["Big Plan"]


def test_list_projects_skips_symlinked_dir(projects_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside_proj"
    outside.mkdir()
    (projects_root / "Project Gamma").symlink_to(outside)
    names = {p.name for p in scanner.list_projects(projects_root)}
    assert "Project Gamma" not in names
    assert names == {"Project Alpha", "Project Beta"}


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
    names = {a.name for a in scanner.list_agents(projects_root)}
    assert "Secret" not in names
    assert names == {"Alpha Agent"}
