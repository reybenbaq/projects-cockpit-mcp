"""Shared fixtures: a synthetic projects tree and a matching Config."""

from __future__ import annotations

from pathlib import Path

import pytest

from cockpit.config import Config


@pytest.fixture
def projects_root(tmp_path: Path) -> Path:
    """Build a small workspace: one rich project, one bare project, one hidden dir."""
    root = tmp_path / "projects"

    alpha = root / "Project Alpha"
    agents = alpha / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "alpha-agent.md").write_text(
        "---\n"
        "name: Alpha Agent\n"
        "description: Does alpha things.\n"
        "model: sonnet\n"
        "---\n"
        "Agent body.\n",
        encoding="utf-8",
    )

    plans = alpha / "plans and validations"
    plans.mkdir(parents=True)
    (plans / "Big Plan.md").write_text(
        "# Big Plan\n\n**Status:** DRAFT\n\nbody\n", encoding="utf-8"
    )
    (plans / "Done Plan.md").write_text(
        "# Done Plan\n\n**Status:** IMPLEMENTED\n", encoding="utf-8"
    )

    memory = alpha / "memory"
    memory.mkdir()
    (memory / "MEMORY.md").write_text(
        "# Memory\n- alpha note about widgets\n", encoding="utf-8"
    )
    (memory / "feedback_widgets.md").write_text(
        "Widgets should be blue.\nAnother line.\n", encoding="utf-8"
    )

    beta = root / "Project Beta"
    beta.mkdir()
    (beta / "README.md").write_text("plain", encoding="utf-8")

    (root / ".hidden").mkdir()
    return root


@pytest.fixture
def config(projects_root: Path) -> Config:
    return Config(
        projects_root=projects_root,
        memory_root=projects_root,
        token="secret-token",
        allowed_origins=frozenset({"https://ok.example"}),
    )
