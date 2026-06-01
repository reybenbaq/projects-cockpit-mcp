"""Custom exception hierarchy for the Projects Cockpit MCP server."""


class CockpitError(Exception):
    """Base class for all Projects Cockpit errors."""


class ConfigError(CockpitError):
    """Raised when required configuration is missing or invalid."""


class PathContainmentError(CockpitError):
    """Raised when a requested path resolves outside an allowed root.

    This is the load-bearing guard against path traversal: every
    caller-supplied project or file name is resolved and checked
    against its root before any filesystem read.
    """


class GitError(CockpitError):
    """Raised when a git invocation fails or git is unavailable."""
