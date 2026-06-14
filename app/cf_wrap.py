"""Cloudflare Access sidecar entry point.

Run the app behind Cloudflare Zero Trust by pointing uvicorn at this module
instead of ``app.main``::

    uvicorn app.cf_wrap:app --host 0.0.0.0 --port 8765

How it works (and why it survives upstream rebases):
- ``from app.main import app`` runs the upstream module in full, registering
  all its ``@app.middleware`` handlers.
- We then call ``app.add_middleware(...)``. Starlette prepends added
  middleware, so OURS becomes the OUTERMOST layer and runs FIRST — before the
  upstream ``_auth_gate``.
- We verify the Cloudflare Access JWT, provision the user, and set
  ``request.state.user``. The upstream ``_auth_gate`` then sees a populated
  ``request.state.user`` and skips its cookie check (its existing
  ``bearer_user = getattr(request.state, "user", None)`` short-circuit).

This file is sidecar-only; it never edits the upstream tree. The single
"watch point" across upstream changes is that short-circuit in
``app/main.py``. See ``docs/CF_SIDECAR_PLAN.md``.
"""
from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from app.main import app  # noqa: E402  — importing runs main.py's middleware setup
from app.core import auth_cf

logger = logging.getLogger(__name__)

# Paths that bypass CF identity:
# - assets / health / favicon / branding: needed for the login + health probe,
#   and harmless to expose.
# - /api/: external API callers carry a Bearer API token, not a CF JWT. Let the
#   upstream _api_token_gate handle them. (If you also want these behind CF Access,
#   use a CF *service token* instead and remove "/api/" here.)
_PUBLIC_PREFIXES = ("/static/", "/healthz", "/favicon", "/branding/", "/api/")

# Where CF Access logs a user out at the edge. Hitting the app's own /logout is
# pointless under trusted-proxy auth — CF would just re-authenticate on the next
# request. Redirect to CF's logout endpoint instead.
_CF_LOGOUT = "/cdn-cgi/access/logout"


def _client_ip(request: Request) -> str:
    xff = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",", 1)[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]


async def _cf_access_dispatch(request: Request, call_next):
    path = request.url.path

    if any(path.startswith(p) for p in _PUBLIC_PREFIXES):
        return await call_next(request)

    if path == "/logout":
        return RedirectResponse(_CF_LOGOUT, status_code=302)

    token = (request.headers.get("Cf-Access-Jwt-Assertion")
             or request.cookies.get("CF_Authorization", ""))
    try:
        user = auth_cf.authenticate(token, ip=_client_ip(request))
    except auth_cf.CFAuthError as exc:
        logger.warning("CF Access denied for %s: %s", path, exc)
        # Fail closed: no valid CF JWT means the request did not come through
        # Cloudflare Access (or the token is bad). Never fall through to the
        # app unauthenticated.
        accept = (request.headers.get("Accept") or "").lower()
        if "text/html" in accept:
            return RedirectResponse(_CF_LOGOUT, status_code=302)
        return JSONResponse(
            {"error": "forbidden", "detail": "Cloudflare Access 驗證失敗"},
            status_code=403,
        )

    # Hand identity to the upstream auth gate via its existing short-circuit.
    request.state.user = user
    return await call_next(request)


# Added last → outermost → runs before upstream middleware. Safe to call at
# import time because the app's middleware stack is built lazily on first request.
app.add_middleware(BaseHTTPMiddleware, dispatch=_cf_access_dispatch)

if not auth_cf.is_configured():
    logger.warning(
        "cf_wrap loaded but CF Access is not configured — set CF_TEAM_DOMAIN "
        "and CF_ACCESS_AUD. Every request will be denied until then.")
else:
    logger.info("cf_wrap active: Cloudflare Access enforced for all non-public paths")

# Re-export so `uvicorn app.cf_wrap:app` works.
__all__ = ["app"]
