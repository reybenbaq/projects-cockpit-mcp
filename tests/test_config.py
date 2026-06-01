"""Tests for load_config: the fail-fast configuration boundary."""

from __future__ import annotations

import pytest

from cockpit.config import (
    _DEFAULT_ALLOWED_HOSTS,
    _DEFAULT_ALLOWED_ORIGINS,
    Config,
    load_config,
)
from cockpit.exceptions import ConfigError


def _env(tmp_path, **overrides) -> dict[str, str]:
    base = {"PROJECTS_ROOT": str(tmp_path), "COCKPIT_TOKEN": "tok"}
    base.update(overrides)
    return base


def test_minimal_config_uses_defaults(tmp_path) -> None:
    cfg = load_config(_env(tmp_path))
    assert isinstance(cfg, Config)
    assert cfg.token == "tok"
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8848
    assert cfg.max_search_hits == 50
    assert cfg.log_level == "INFO"
    assert cfg.projects_root == tmp_path.resolve()
    # memory_root defaults to projects_root when MEMORY_ROOT is unset.
    assert cfg.memory_root == tmp_path.resolve()


def test_missing_required_vars_raise() -> None:
    with pytest.raises(ConfigError) as exc:
        load_config({})
    msg = str(exc.value)
    assert "missing required env vars" in msg
    assert "PROJECTS_ROOT" in msg
    assert "COCKPIT_TOKEN" in msg


def test_nonexistent_projects_root_raises(tmp_path) -> None:
    env = _env(tmp_path, PROJECTS_ROOT=str(tmp_path / "nope"))
    with pytest.raises(ConfigError) as exc:
        load_config(env)
    assert "not an existing directory" in str(exc.value)


def test_port_below_minimum_raises(tmp_path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(_env(tmp_path, PORT="80"))
    assert "PORT" in str(exc.value)


def test_port_above_maximum_raises(tmp_path) -> None:
    with pytest.raises(ConfigError):
        load_config(_env(tmp_path, PORT="70000"))


def test_non_integer_port_raises(tmp_path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(_env(tmp_path, PORT="abc"))
    assert "must be an integer" in str(exc.value)


def test_max_search_hits_below_one_raises(tmp_path) -> None:
    with pytest.raises(ConfigError):
        load_config(_env(tmp_path, MAX_SEARCH_HITS="0"))


def test_invalid_log_level_raises(tmp_path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(_env(tmp_path, LOG_LEVEL="LOUD"))
    assert "LOG_LEVEL" in str(exc.value)


def test_log_level_is_uppercased(tmp_path) -> None:
    cfg = load_config(_env(tmp_path, LOG_LEVEL="debug"))
    assert cfg.log_level == "DEBUG"


def test_memory_root_override(tmp_path) -> None:
    other = tmp_path / "mem"
    other.mkdir()
    cfg = load_config(_env(tmp_path, MEMORY_ROOT=str(other)))
    assert cfg.memory_root == other.resolve()


def test_allowed_origins_default_when_unset(tmp_path) -> None:
    cfg = load_config(_env(tmp_path))
    assert cfg.allowed_origins == frozenset(_DEFAULT_ALLOWED_ORIGINS)


def test_allowed_origins_explicit_value(tmp_path) -> None:
    cfg = load_config(
        _env(tmp_path, ALLOWED_ORIGINS="https://a.example, https://b.example")
    )
    assert cfg.allowed_origins == frozenset({"https://a.example", "https://b.example"})


def test_allowed_origins_explicit_empty_rejects_all(tmp_path) -> None:
    cfg = load_config(_env(tmp_path, ALLOWED_ORIGINS=""))
    assert cfg.allowed_origins == frozenset()


def test_allowed_hosts_default_when_unset(tmp_path) -> None:
    cfg = load_config(_env(tmp_path))
    assert cfg.allowed_hosts == frozenset(_DEFAULT_ALLOWED_HOSTS)


def test_allowed_hosts_explicit_value(tmp_path) -> None:
    cfg = load_config(_env(tmp_path, ALLOWED_HOSTS="example.com:*, app.example.com:8443"))
    assert cfg.allowed_hosts == frozenset({"example.com:*", "app.example.com:8443"})


def test_multiple_problems_aggregated() -> None:
    with pytest.raises(ConfigError) as exc:
        load_config({"PORT": "10", "LOG_LEVEL": "NOPE"})
    msg = str(exc.value)
    assert "missing required env vars" in msg
    assert "PORT" in msg
    assert "LOG_LEVEL" in msg
