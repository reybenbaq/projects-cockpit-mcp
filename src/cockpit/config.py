"""Configuration loading — all environment reads happen here, once, at startup.

Collects every missing required variable before failing so all errors surface
at once. Never reads ``os.environ`` inside business logic; passes the frozen
``Config`` object by dependency injection instead.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .exceptions import ConfigError

# Protocol revision this server is built and tested against.
# A smoke test asserts the pinned SDK's LATEST_PROTOCOL_VERSION equals this, so
# the constant is an enforced contract rather than documentation.
PROTOCOL_REVISION = "2025-11-25"

_REQUIRED = ("PROJECTS_ROOT", "COCKPIT_TOKEN")
_DEFAULT_MAX_DISCOVERY_DEPTH = 3
_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

# Loopback defaults for the transport-layer DNS-rebinding guard. These mirror
# what FastMCP would auto-enable for a localhost bind, but we set them
# explicitly (see server.build_server) so the posture is visible, intentional,
# and stable regardless of the bind interface (the container binds 0.0.0.0).
_DEFAULT_ALLOWED_HOSTS = ("127.0.0.1:*", "localhost:*", "[::1]:*")
_DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:*",
    "http://localhost:*",
    "http://[::1]:*",
)


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
        allowed_origins: Browser ``Origin`` values the transport accepts
            (DNS-rebinding defense). A request whose
            ``Origin`` is not in this set is rejected (403); a request with
            no ``Origin`` (a non-browser client like Claude Code) is allowed.
            Defaults to loopback origins; an explicit empty value rejects all
            browser Origins.
        allowed_hosts: ``Host`` header values the transport accepts. A
            request whose ``Host`` is not in this set is rejected (421).
            Defaults to loopback hosts. Widen this only to expose the server
            beyond loopback, and adopt the OAuth path (see README) when you do.
        max_search_hits: Hard ceiling on ``memory_search`` results.
        log_level: Root log level name.
        max_discovery_depth: How many directory levels below ``projects_root``
            to recurse when discovering projects (env: ``MAX_DISCOVERY_DEPTH``,
            default 3). Covers L1/L2/L3 layouts; raising above 3 risks
            descending into vendored subtrees.
        require_markers: When ``True`` (default) only directories that carry a
            qualifying marker (``.claude/agents/*.md``, valid ``.git``,
            ``plans and validations/``, or ``implemented plans/``) are returned
            as projects. Set ``REQUIRE_MARKERS=false`` to restore the old
            flat-all-dirs behaviour (useful for demo / CI environments with
            unmarked fixture trees).
    """

    projects_root: Path
    memory_root: Path
    token: str
    host: str = "127.0.0.1"
    port: int = 8848
    allowed_origins: frozenset[str] = field(
        default_factory=lambda: frozenset(_DEFAULT_ALLOWED_ORIGINS)
    )
    allowed_hosts: frozenset[str] = field(
        default_factory=lambda: frozenset(_DEFAULT_ALLOWED_HOSTS)
    )
    max_search_hits: int = 50
    log_level: str = "INFO"
    max_discovery_depth: int = _DEFAULT_MAX_DISCOVERY_DEPTH
    require_markers: bool = True


def _split_set(raw: str | None, default: tuple[str, ...]) -> frozenset[str]:
    """Parse a comma-separated env value, or fall back to ``default`` when unset.

    An explicitly empty value ("") yields an empty set — a deliberate
    "reject all" override, distinct from leaving the variable unset.
    """
    if raw is None:
        return frozenset(default)
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
    max_depth = _parse_int(
        env.get("MAX_DISCOVERY_DEPTH", str(_DEFAULT_MAX_DISCOVERY_DEPTH)),
        "MAX_DISCOVERY_DEPTH",
        problems,
        minimum=1,
        maximum=10,
    )

    log_level = env.get("LOG_LEVEL", "INFO").upper()
    if log_level not in _VALID_LOG_LEVELS:
        problems.append(
            f"LOG_LEVEL must be one of {sorted(_VALID_LOG_LEVELS)}, got: {log_level!r}"
        )

    require_markers = _parse_bool(env.get("REQUIRE_MARKERS", "true"))

    if problems:
        raise ConfigError("Invalid configuration: " + "; ".join(problems))

    return Config(
        projects_root=projects_root,
        memory_root=memory_root,
        token=env["COCKPIT_TOKEN"],
        host=env.get("HOST", "127.0.0.1"),
        port=port,
        allowed_origins=_split_set(env.get("ALLOWED_ORIGINS"), _DEFAULT_ALLOWED_ORIGINS),
        allowed_hosts=_split_set(env.get("ALLOWED_HOSTS"), _DEFAULT_ALLOWED_HOSTS),
        max_search_hits=max_hits,
        log_level=log_level,
        max_discovery_depth=max_depth,
        require_markers=require_markers,
    )


def _resolve_dir(raw: str | None, name: str, problems: list[str]) -> Path:
    if not raw:
        return Path()  # the missing-vars problem is already recorded
    path = Path(raw).expanduser()
    if not path.is_dir():
        problems.append(f"{name} is not an existing directory: {raw}")
        return path
    return path.resolve()


def _parse_bool(raw: str) -> bool:
    """Interpret a string env value as a boolean.

    ``"true"`` / ``"1"`` / ``"yes"`` (case-insensitive) → ``True``.
    Anything else → ``False``.
    """
    return raw.strip().lower() in ("true", "1", "yes")


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
