"""ASGI security middleware for the streamable-HTTP transport.

Enforces the two MCP local-HTTP requirements (overlay §6, §11.1) that the
FastMCP app does not impose on its own:

* ``Origin`` validation — a request carrying a browser ``Origin`` not in the
  allowlist is rejected with 403 (DNS-rebinding defense). A request with no
  ``Origin`` header (a non-browser client such as Claude Code) is allowed.
* Bearer token — every request must carry ``Authorization: Bearer <token>``
  matching the configured token, compared in constant time.

``/healthz`` is exempt so container orchestrators can probe liveness without
the token. Implemented as raw ASGI (not ``BaseHTTPMiddleware``) so streamed
SSE responses and the ``lifespan`` scope pass through untouched.
"""

from __future__ import annotations

import hmac
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

Scope = dict
Receive = Callable[[], Awaitable[dict]]
Send = Callable[[dict], Awaitable[None]]

HEALTH_PATH = "/healthz"


class SecurityMiddleware:
    """Wraps an ASGI app with Origin + bearer-token enforcement."""

    def __init__(self, app, *, token: str, allowed_origins: frozenset[str]) -> None:
        self.app = app
        self._token = token
        self._allowed_origins = allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # lifespan / websocket pass straight through to the inner app.
            await self.app(scope, receive, send)
            return

        if scope.get("path") == HEALTH_PATH:
            await _send_text(send, 200, "ok")
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}

        origin = headers.get(b"origin")
        if origin is not None and origin.decode("latin-1") not in self._allowed_origins:
            logger.warning("Rejected request: disallowed Origin")
            await _send_text(send, 403, "forbidden origin")
            return

        if not self._authorized(headers.get(b"authorization")):
            await _send_text(
                send,
                401,
                "unauthorized",
                extra_headers=[(b"www-authenticate", b"Bearer")],
            )
            return

        await self.app(scope, receive, send)

    def _authorized(self, auth_header: bytes | None) -> bool:
        if auth_header is None:
            return False
        try:
            scheme, _, value = auth_header.decode("latin-1").partition(" ")
        except UnicodeDecodeError:
            return False
        if scheme.lower() != "bearer" or not value:
            return False
        return hmac.compare_digest(value, self._token)


async def _send_text(
    send: Send,
    status: int,
    body: str,
    *,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    payload = body.encode("utf-8")
    headers = [
        (b"content-type", b"text/plain; charset=utf-8"),
        (b"content-length", str(len(payload)).encode("ascii")),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": payload})
