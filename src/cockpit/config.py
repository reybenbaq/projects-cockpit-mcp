"""Configuration loading — all environment reads happen here, once, at startup.

Per the universal core: collect every missing required variable before
failing, never read ``os.environ`` inside business logic, pass the frozen
``Config`` object by dependency injection.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .exceptions import ConfigError

# Protocol revision this server is built and tested against (MCP overlay §1).
# A smoke test asserts the pinned SDK's LATEST_PROTOCOL_VERSION equals this, so
# the constant is an enforced contract rather than documentation.
PROTOCOL_REVISION = "2025-11-25"

_REQUIRED = ("PROJECTS_ROOT", "COCKPIT_TOKEN")
_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


@dataclass(frozen=True)
class Config:
    """Immutable runtime configuration.

    Attributes:
        projects_root: Directory scanned for projects, agents, and plans.
        memory_root: Directory searched by ``memory_search`` (defaults to
            ``projects_root`` when ``MEMORY_ROOT`` is unset).
        token: Bearer token required on every HTTP request.
        host: Bind address. Local servers bind loopback only.
        port: Bind port (>= 1024 so the container can run non-root).
        allowed_origins: Browser ``Origin`` values permitted. A request
            carrying an ``Origin`` not in this set is rejected (403). A
            request with no ``Origin`` (a non-browser client) is allowed.
        max_search_hits: Hard ceiling on ``memory_search`` results.
        log_level: Root log level name.
    """

    projects_root: Path
    memory_root: Path
    token: str
    host: str = "127.0.0.1"
    port: int = 8848
    allowed_origins: frozenset[str] = field(default_factory=frozenset)
    max_search_hits: int = 50
    log_level: str = "INFO"


def _split_origins(raw: str) -> frozenset[str]:
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def load_config(environ: dict[str, str] | None = None) -> Config:
    """Build the ``Config`` from the environment, failing fast on bad input.

    Raises:
        ConfigError: if any required variable is missing, or if a directory
            does not exist, or if a numeric variable cannot be parsed. All
            problems are collected and reported together.
    """
    env = environ if environ is not None else dict(os.environ)
    problems: list[str] = []

    missing = [name for name in _REQUIRED if not env.get(name)]
    if missing:
        problems.append(f"missing required env vars: {', '.join(missing)}")

    projects_root = _resolve_dir(env.get("PROJECTS_ROOT"), "PROJECTS_ROOT", problems)
    memory_raw = env.get("MEMORY_ROOT") or env.get("PROJECTS_ROOT")
    memory_root = _resolve_dir(memory_raw, "MEMORY_ROOT", problems)

    port = _parse_int(
        env.get("PORT", "8848"), "PORT", problems, minimum=1024, maximum=65535
    )
    max_hits = _parse_int(
        env.get("MAX_SEARCH_HITS", "50"), "MAX_SEARCH_HITS", problems, minimum=1
    )

    log_level = env.get("LOG_LEVEL", "INFO").upper()
    if log_level not in _VALID_LOG_LEVELS:
        problems.append(
            f"LOG_LEVEL must be one of {sorted(_VALID_LOG_LEVELS)}, got: {log_level!r}"
        )

    if problems:
        raise ConfigError("Invalid configuration: " + "; ".join(problems))

    return Config(
        projects_root=projects_root,
        memory_root=memory_root,
        token=env["COCKPIT_TOKEN"],
        host=env.get("HOST", "127.0.0.1"),
        port=port,
        allowed_origins=_split_origins(env.get("ALLOWED_ORIGINS", "")),
        max_search_hits=max_hits,
        log_level=log_level,
    )


def _resolve_dir(raw: str | None, name: str, problems: list[str]) -> Path:
    if not raw:
        return Path()  # the missing-vars problem is already recorded
    path = Path(raw).expanduser()
    if not path.is_dir():
        problems.append(f"{name} is not an existing directory: {raw}")
        return path
    return path.resolve()


def _parse_int(
    raw: str,
    name: str,
    problems: list[str],
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    try:
        value = int(raw)
    except ValueError:
        problems.append(f"{name} must be an integer, got: {raw!r}")
        return 0
    if minimum is not None and value < minimum:
        problems.append(f"{name} must be >= {minimum}, got: {value}")
    if maximum is not None and value > maximum:
        problems.append(f"{name} must be <= {maximum}, got: {value}")
    return value
