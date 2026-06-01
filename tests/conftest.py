"""Shared fixtures: a synthetic projects tree and a matching Config.

The ``projects_root`` fixture builds a **hybrid** workspace:

- A flat L1 project (``Project Alpha``) with a full set of markers.
- A flat L1 project (``Project Beta``) with no markers.
- A category directory (``Category``) containing a nested L2 project
  (``Category/Nested Project``) with agent and plan markers.
- A hidden directory that must always be skipped.

Existing tests (written against the old flat-all-dirs scanner) use the
``config`` fixture which sets ``require_markers=False``, so they continue to
see both ``Project Alpha`` and ``Project Beta`` without changes.

New tests that exercise nested discovery or the marker gate use the
``config_markers`` fixture (``require_markers=True``, the production default).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cockpit.config import Config


@pytest.fixture
def projects_root(tmp_path: Path) -> Path:
    """Build a small workspace: one rich project, one bare project, one hidden dir,
    and a category dir with a nested child project.
    """
    root = tmp_path / "projects"

    # --- Project Alpha (L1, fully-featured) ----------------------------------
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

    # --- Project Beta (L1, marker-less) --------------------------------------
    beta = root / "Project Beta"
    beta.mkdir()
    (beta / "README.md").write_text("plain", encoding="utf-8")

    # --- Category / Nested Project (L2, marker-bearing child) ----------------
    category = root / "Category"
    category.mkdir()

    nested = category / "Nested Project"
    nested_agents = nested / ".claude" / "agents"
    nested_agents.mkdir(parents=True)
    (nested_agents / "nested-agent.md").write_text(
        "---\n"
        "name: Nested Agent\n"
        "description: Does nested things.\n"
        "model: haiku\n"
        "---\n"
        "Nested agent body.\n",
        encoding="utf-8",
    )
    nested_plans = nested / "plans and validations"
    nested_plans.mkdir(parents=True)
    (nested_plans / "Nested Plan.md").write_text(
        "# Nested Plan\n\n**Status:** IN PROGRESS\n", encoding="utf-8"
    )

    # --- Hidden dir (must be skipped) ----------------------------------------
    (root / ".hidden").mkdir()

    return root


@pytest.fixture
def config(projects_root: Path) -> Config:
    """Config with ``require_markers=False`` so existing flat tests are unaffected."""
    return Config(
        projects_root=projects_root,
        memory_root=projects_root,
        token="secret-token",
        allowed_origins=frozenset({"https://ok.example"}),
        require_markers=False,
    )


@pytest.fixture
def config_markers(projects_root: Path) -> Config:
    """Config with ``require_markers=True`` (production default) for marker-gate tests."""
    return Config(
        projects_root=projects_root,
        memory_root=projects_root,
        token="secret-token",
        allowed_origins=frozenset({"https://ok.example"}),
        require_markers=True,
    )
