"""Cloudflare Access (Zero Trust) authentication backend — sidecar.

Trusted-proxy model: Cloudflare Access verifies the user's identity at the
edge (optionally federating to Microsoft Entra ID / Google / etc.) and signs
a JWT that it injects into every request as the ``Cf-Access-Jwt-Assertion``
header (also mirrored in the ``CF_Authorization`` cookie). The origin trusts
that JWT *after verifying its signature against Cloudflare's team JWKS* — the
raw e-mail header alone is NOT trusted (it can be spoofed if the origin is
reachable without going through Cloudflare).

This module is **sidecar code**: it is only imported by ``app/cf_wrap.py``,
never by the upstream tree, so it can be kept across upstream rebases without
conflicts. See ``docs/CF_SIDECAR_PLAN.md``.

Design notes:
- CF users are provisioned into the existing ``users`` table as
  ``source='local'`` with ``password_hash=NULL``. This passes the existing
  ``CHECK (source IN ('local','ldap','ad'))`` constraint so NO schema
  migration is needed, and the NULL hash means nobody can log in as them via
  the password form (``verify_password(pw, None)`` is always False).
- First admin is bootstrapped from the ``CF_ADMIN_EMAILS`` env var; everyone
  else gets ``default-user`` on first login (admin re-assigns in
  ``/admin/permissions`` afterwards).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

from . import auth_db, audit_db, db, permissions

logger = logging.getLogger(__name__)


class CFAuthError(Exception):
    """CF Access verification / provisioning failure (fail closed)."""


# ---------- configuration (env-driven; does not touch config.py) ----------

def _team_domain() -> str:
    """e.g. 'mycompany' → mycompany.cloudflareaccess.com. Accepts either the
    bare team name or a full domain."""
    raw = (os.environ.get("CF_TEAM_DOMAIN") or "").strip().rstrip("/")
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        raw = raw.split("://", 1)[1]
    # strip a trailing .cloudflareaccess.com if the admin pasted the full host
    if raw.endswith(".cloudflareaccess.com"):
        raw = raw[: -len(".cloudflareaccess.com")]
    return raw


def _issuer() -> str:
    team = _team_domain()
    return f"https://{team}.cloudflareaccess.com" if team else ""


def _certs_url() -> str:
    return f"{_issuer()}/cdn-cgi/access/certs" if _issuer() else ""


def _aud() -> str:
    return (os.environ.get("CF_ACCESS_AUD") or "").strip()


def _admin_emails() -> set[str]:
    raw = os.environ.get("CF_ADMIN_EMAILS") or ""
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_configured() -> bool:
    return bool(_team_domain() and _aud())


def _mask_aud(aud: str) -> str:
    """Mask the AUD for display — never show the full value on a web page."""
    if not aud:
        return "未設定"
    return ("••••" + aud[-4:]) if len(aud) >= 4 else "已設定"


def public_status() -> dict:
    """Non-sensitive CF status for display on the admin auth-settings page.

    Intentionally returns only what is safe to show an admin: the login
    domain (which users hit anyway), a masked AUD, and the COUNT of admin
    e-mails (not the addresses themselves). The full AUD and the actual
    admin e-mail list are deliberately omitted.
    """
    return {
        "active": is_configured(),
        "team_domain": _team_domain(),
        "issuer": _issuer(),
        "aud_masked": _mask_aud(_aud()),
        "admin_email_count": len(_admin_emails()),
    }


# ---------- JWKS client (lazy, cached by PyJWT's PyJWKClient) ----------

_jwks_client = None  # type: ignore[var-annotated]


def _get_jwks_client():
    """Return a cached PyJWKClient for the configured team. PyJWKClient caches
    signing keys in-process and re-fetches on unknown kid, so this is cheap on
    the hot path."""
    global _jwks_client
    if _jwks_client is None:
        try:
            from jwt import PyJWKClient
        except ImportError as exc:
            raise CFAuthError(
                "PyJWT 未安裝;請先 pip install -r requirements-cf.txt") from exc
        url = _certs_url()
        if not url:
            raise CFAuthError("CF_TEAM_DOMAIN 未設定")
        # lifespan=3600: re-fetch the cert set at most hourly; PyJWKClient also
        # re-fetches automatically when it sees a kid it doesn't know.
        _jwks_client = PyJWKClient(url, cache_keys=True, lifespan=3600)
    return _jwks_client


def verify(token: str) -> dict:
    """Verify a Cloudflare Access JWT and return its claims.

    Raises CFAuthError on any failure (missing/expired/bad-signature/wrong
    audience). The caller MUST treat any exception as "not authenticated"
    and fail closed.
    """
    if not token:
        raise CFAuthError("缺少 Cloudflare Access JWT")
    if not is_configured():
        raise CFAuthError("CF Access 尚未設定(CF_TEAM_DOMAIN / CF_ACCESS_AUD)")
    try:
        import jwt
    except ImportError as exc:
        raise CFAuthError(
            "PyJWT 未安裝;請先 pip install -r requirements-cf.txt") from exc
    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=_aud(),
            issuer=_issuer(),
            options={"require": ["exp", "iat", "aud"]},
        )
    except CFAuthError:
        raise
    except Exception as exc:  # jwt.* errors + JWKS fetch errors
        # Don't leak token contents; class name is enough to diagnose.
        raise CFAuthError(f"JWT 驗證失敗:{type(exc).__name__}") from exc

    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise CFAuthError("JWT 內沒有 email claim")
    return claims


# ---------- provisioning ----------

def provision(email: str, display_name: str = "", *, ip: str = "") -> dict:
    """Look up (or create) the local user row for a CF-verified e-mail.

    Returns the session-user dict shape that ``request.state.user`` expects:
    ``{user_id, username, display_name, source}``.

    Raises CFAuthError if the account exists but is disabled.
    """
    email = (email or "").strip().lower()
    if not email:
        raise CFAuthError("email 不能空白")
    display_name = (display_name or "").strip() or email

    conn = auth_db.conn()
    now = time.time()
    row = conn.execute(
        "SELECT id, display_name, enabled FROM users "
        "WHERE username=? AND source='local'",
        (email,),
    ).fetchone()

    if row:
        if not row["enabled"]:
            audit_db.log_event(
                "login_fail", username=email, ip=ip,
                details={"reason": "disabled", "source": "cfaccess"})
            raise CFAuthError("帳號已停用,請聯絡管理員")
        # Refresh last_login + display name (cheap; keeps name fresh from IdP).
        with db.tx(conn):
            conn.execute(
                "UPDATE users SET last_login_at=?, display_name=? WHERE id=?",
                (now, display_name, row["id"]),
            )
        return {"user_id": row["id"], "username": email,
                "display_name": display_name, "source": "local"}

    # First login for this e-mail → create the row.
    with db.tx(conn):
        cur = conn.execute(
            "INSERT INTO users(username, display_name, password_hash, source, "
            " enabled, is_admin_seed, created_at, last_login_at) "
            "VALUES (?, ?, NULL, 'local', 1, 0, ?, ?)",
            (email, display_name, now, now),
        )
        uid = cur.lastrowid
    role = "admin" if email in _admin_emails() else "default-user"
    permissions.set_subject_roles("user", str(uid), [role])
    audit_db.log_event(
        "login_success", username=email, ip=ip,
        details={"source": "cfaccess", "provisioned": True, "role": role})
    logger.info("CF Access provisioned new user '%s' as %s", email, role)
    return {"user_id": uid, "username": email,
            "display_name": display_name, "source": "local"}


def authenticate(token: str, *, ip: str = "") -> dict:
    """Convenience: verify JWT + provision in one call. Returns the
    session-user dict. Raises CFAuthError on any failure."""
    claims = verify(token)
    return provision(claims["email"], claims.get("name", ""), ip=ip)
