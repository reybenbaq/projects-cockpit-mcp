"""Tests for server wiring: transport-security config and the bearer-only app."""

from __future__ import annotations

from mcp.server.transport_security import (
    TransportSecurityMiddleware,
    TransportSecuritySettings,
)
from starlette.requests import Request

from cockpit import server
from cockpit.config import (
    _DEFAULT_ALLOWED_HOSTS,
    _DEFAULT_ALLOWED_ORIGINS,
    Config,
)
from cockpit.middleware import SecurityMiddleware


def _config(tmp_path) -> Config:
    return Config(
        projects_root=tmp_path,
        memory_root=tmp_path,
        token="tok",
        allowed_hosts=frozenset({"127.0.0.1:*", "example.com:*"}),
        allowed_origins=frozenset({"http://127.0.0.1:*"}),
    )


def test_transport_security_configured_from_config(tmp_path) -> None:
    """Host/Origin DNS-rebinding defense is set explicitly from config, not left
    to FastMCP's implicit localhost auto-enable."""
    mcp = server.build_server(_config(tmp_path))
    ts = mcp.settings.transport_security
    assert ts is not None
    assert ts.enable_dns_rebinding_protection is True
    assert set(ts.allowed_hosts) == {"127.0.0.1:*", "example.com:*"}
    assert set(ts.allowed_origins) == {"http://127.0.0.1:*"}


def test_build_app_is_bearer_only(tmp_path) -> None:
    app = server.build_app(_config(tmp_path))
    assert isinstance(app, SecurityMiddleware)
    assert app._token == "tok"
    # Origin enforcement moved to the transport layer; the middleware holds none.
    assert not hasattr(app, "_allowed_origins")


def _request(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "GET", "headers": raw})


def _loopback_middleware() -> TransportSecurityMiddleware:
    """The SDK transport guard built from the package's default loopback sets,
    so these tests prove the *shipped defaults* enforce as the README documents."""
    settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=sorted(_DEFAULT_ALLOWED_HOSTS),
        allowed_origins=sorted(_DEFAULT_ALLOWED_ORIGINS),
    )
    return TransportSecurityMiddleware(settings)


async def test_default_sets_accept_loopback_host_and_origin() -> None:
    mw = _loopback_middleware()
    result = await mw.validate_request(
        _request({"host": "127.0.0.1:8848", "origin": "http://127.0.0.1:8848"})
    )
    assert result is None


async def test_default_sets_accept_missing_origin() -> None:
    # Non-browser clients (Claude Code) send no Origin; that must pass.
    mw = _loopback_middleware()
    result = await mw.validate_request(_request({"host": "localhost:8848"}))
    assert result is None


async def test_non_loopback_host_returns_421() -> None:
    mw = _loopback_middleware()
    result = await mw.validate_request(_request({"host": "evil.example.com"}))
    assert result is not None
    assert result.status_code == 421


async def test_foreign_origin_returns_403() -> None:
    mw = _loopback_middleware()
    result = await mw.validate_request(
        _request({"host": "127.0.0.1:8848", "origin": "http://evil.example.com"})
    )
    assert result is not None
    assert result.status_code == 403
