"""Shared-password access control: no accounts, just a long-lived signed
cookie.

`POST /api/login` with the password sets the cookie. Without one, a
request only gets through to the paths in PUBLIC_PATHS, and to reads
(GET/HEAD) under ANONYMOUS_READ_PREFIX -- the issues, where the routes
themselves hide what isn't openly licensed (app.py). Everything else
needs the login. It's an allowlist on purpose: a route added later is
protected without anyone remembering to register it, and anything that
costs money (asking for audio is a POST) can't be reached anonymously.

The middleware records the outcome as `request.state.logged_in`.

The cookie is `<issued_at>.<hmac>`, keyed by a hash of the password
itself -- changing ACCESS_PASSWORD invalidates every cookie, so revoking
access is that single change."""

import hashlib
import hmac
import time

from fastapi import Request, Response
from fastapi.responses import JSONResponse

COOKIE_NAME = "hoerbote_session"
MAX_AGE_SECONDS = 365 * 24 * 3600
# Sliding expiry: a cookie older than this gets re-issued on the next
# request, so anyone using the app at least once a year never re-logs in.
REFRESH_AFTER_SECONDS = 24 * 3600

# Exact paths, no prefixes. app.py adds the frontend's built files (the
# app shell: index.html + JS/CSS) at startup -- they hold no newspaper
# content. Same for the API docs: they describe the routes, nothing more.
PUBLIC_PATHS = {"/api/login", "/api/logout", "/api/session", "/robots.txt", "/api/docs", "/api/openapi.json"}
ANONYMOUS_READ_PREFIX = "/api/issues"
_READ_METHODS = {"GET", "HEAD"}


class Access:
    def __init__(self, password: str, public_paths: set[str] = PUBLIC_PATHS) -> None:
        if not password:
            raise ValueError("ACCESS_PASSWORD must be set (and non-empty).")
        self._public_paths = frozenset(public_paths)
        self._password = password.encode()
        self._key = hashlib.sha256(b"hoerbote-session-key:" + self._password).digest()

    def password_matches(self, candidate: str) -> bool:
        return hmac.compare_digest(candidate.encode(), self._password)

    def _sign(self, issued_at: int) -> str:
        return hmac.new(self._key, str(issued_at).encode(), hashlib.sha256).hexdigest()

    def issue(self, response: Response, now: int | None = None) -> None:
        issued_at = int(now if now is not None else time.time())
        response.set_cookie(
            COOKIE_NAME,
            f"{issued_at}.{self._sign(issued_at)}",
            max_age=MAX_AGE_SECONDS,
            httponly=True,
            secure=True,
            samesite="lax",
        )

    def issued_at(self, cookie: str | None, now: int | None = None) -> int | None:
        """The cookie's issue time if it's validly signed and not expired,
        else None."""
        if not cookie:
            return None
        issued, _, sig = cookie.partition(".")
        if not issued.isdigit() or not hmac.compare_digest(sig, self._sign(int(issued))):
            return None
        age = int(now if now is not None else time.time()) - int(issued)
        return int(issued) if 0 <= age < MAX_AGE_SECONDS else None

    def forget(self, response: Response) -> None:
        response.delete_cookie(COOKIE_NAME, httponly=True, secure=True, samesite="lax")

    def _anonymous_allowed(self, request: Request) -> bool:
        path = request.url.path
        if path in self._public_paths:
            return True
        under_prefix = path == ANONYMOUS_READ_PREFIX or path.startswith(ANONYMOUS_READ_PREFIX + "/")
        return under_prefix and request.method in _READ_METHODS

    async def middleware(self, request: Request, call_next) -> Response:
        issued_at = self.issued_at(request.cookies.get(COOKIE_NAME))
        request.state.logged_in = issued_at is not None
        if issued_at is None and not self._anonymous_allowed(request):
            return JSONResponse({"detail": "not logged in"}, status_code=401)

        response = await call_next(request)
        # Not on logout, which just deleted the cookie.
        if (
            issued_at is not None
            and time.time() - issued_at > REFRESH_AFTER_SECONDS
            and "set-cookie" not in response.headers
        ):
            self.issue(response)
        return response
