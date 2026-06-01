"""ASGI security-middleware tests: bearer auth, healthz, passthrough.

Host and Origin validation lives in the SDK transport layer (configured in
build_server), so it is exercised in test_server.py, not here.
"""

from __future__ import annotations

from cockpit.middleware import SecurityMiddleware

TOKEN = "secret-token"


class DummyApp:
    """Records whether it was reached and emits a trivial 200 response."""

    def __init__(self) -> None:
        self.called = False

    async def __call__(self, scope, receive, send) -> None:
        self.called = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"inner"})


async def _drive(mw, scope) -> int:
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await mw(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"]


def _http(path="/mcp", headers=None):
    return {"type": "http", "path": path, "headers": headers or []}


def _mw(inner):
    return SecurityMiddleware(inner, token=TOKEN)


async def test_missing_token_is_401() -> None:
    inner = DummyApp()
    status = await _drive(_mw(inner), _http())
    assert status == 401
    assert inner.called is False


async def test_valid_token_reaches_app() -> None:
    inner = DummyApp()
    scope = _http(headers=[(b"authorization", b"Bearer secret-token")])
    status = await _drive(_mw(inner), scope)
    assert status == 200
    assert inner.called is True


async def test_wrong_token_is_401() -> None:
    inner = DummyApp()
    scope = _http(headers=[(b"authorization", b"Bearer nope")])
    status = await _drive(_mw(inner), scope)
    assert status == 401
    assert inner.called is False


async def test_healthz_bypasses_auth() -> None:
    inner = DummyApp()
    status = await _drive(_mw(inner), _http(path="/healthz"))
    assert status == 200
    assert inner.called is False  # served by the middleware, not the app


async def test_lifespan_passes_through() -> None:
    inner = DummyApp()
    sent: list[dict] = []

    async def receive():
        return {"type": "lifespan.startup"}

    async def send(message):
        sent.append(message)

    await _mw(inner)({"type": "lifespan"}, receive, send)
    assert inner.called is True
