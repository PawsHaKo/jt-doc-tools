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

import html as _html
import logging
import re as _re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

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


_AUTH_SETTINGS_PATH = "/admin/auth-settings"
_MAIN_TAG_RE = _re.compile(r"<main[^>]*>", _re.IGNORECASE)


def _cf_status_banner() -> str:
    """Build the non-sensitive 'Cloudflare Access is active' notice injected
    into /admin/auth-settings. Only shows what auth_cf.public_status() deems
    safe (masked AUD, e-mail count — never the full AUD or the addresses)."""
    st = auth_cf.public_status()
    issuer = _html.escape(st["issuer"] or "(未設定)")
    aud = _html.escape(st["aud_masked"])
    n = st["admin_email_count"]
    return f"""
<div class="panel" style="border-left:4px solid #2563eb;background:#eff6ff;">
  <h2 style="margin-top:0;">🛡 此站目前由 Cloudflare Access（Zero Trust）驗證身分</h2>
  <p class="muted" style="margin-top:-4px;">
    實際登入由 Cloudflare 邊緣處理(可能再轉企業 IdP)。下方的本機認證設定
    僅作為<b>權限 / 角色基礎</b>與<b>緊急救援</b>之用,日常登入不會用到密碼表單。
  </p>
  <table class="kv">
    <tr><th>認證模式</th><td><b>Cloudflare Access (Zero Trust)</b></td></tr>
    <tr><th>登入網域</th><td>{issuer}</td></tr>
    <tr><th>Application AUD</th><td>{aud}<span class="muted"> (已遮蔽)</span></td></tr>
    <tr><th>預設管理員 email</th><td>{n} 個<span class="muted"> (由 CF_ADMIN_EMAILS 指定,不顯示內容)</span></td></tr>
  </table>
  <p class="muted" style="font-size:12px;margin-bottom:0;">
    這些值由伺服器環境變數設定,需在主機上調整;此頁唯讀顯示。
  </p>
</div>
"""


async def _inject_cf_banner(response):
    """Read an HTML response body and inject the CF status banner just after
    the opening <main> tag (top of the content area). Returns a new response.
    On any failure, the caller falls back to the original response."""
    body = b""
    async for chunk in response.body_iterator:
        body += chunk
    text = body.decode("utf-8", "replace")
    banner = _cf_status_banner()
    new_text, n_sub = _MAIN_TAG_RE.subn(lambda m: m.group(0) + banner, text, count=1)
    if n_sub == 0:  # <main> not found (upstream restructured) → fall back to </body>
        if "</body>" in new_text:
            new_text = new_text.replace("</body>", banner + "</body>", 1)
        else:
            new_text += banner
    headers = {k: v for k, v in response.headers.items()
               if k.lower() not in ("content-length", "content-type")}
    return HTMLResponse(new_text, status_code=200, headers=headers)


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
    response = await call_next(request)

    # On the admin auth-settings page, inject a read-only banner noting that
    # Cloudflare Access is in charge (the upstream page only knows backend=local
    # and has no idea CF sits in front). Sidecar-only — never edits the template.
    if (request.method == "GET"
            and path == _AUTH_SETTINGS_PATH
            and getattr(response, "status_code", 0) == 200
            and response.headers.get("content-type", "").lower().startswith("text/html")
            and auth_cf.is_configured()):
        try:
            return await _inject_cf_banner(response)
        except Exception:
            logger.exception("CF banner injection failed; serving original page")
    return response


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
