"""Projects Cockpit MCP — read-only awareness of a multi-project workspace."""

from .config import Config, load_config
from .server import build_app, build_server, main

__all__ = ["Config", "load_config", "build_app", "build_server", "main"]
