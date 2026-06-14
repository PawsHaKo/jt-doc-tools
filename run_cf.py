"""Local launcher for the Cloudflare Access sidecar.

Equivalent to ``run.py`` but serves ``app.cf_wrap:app`` (the CF-wrapped app)
instead of ``app.main:app``. Use this (or point your systemd unit at
``app.cf_wrap:app``) when running behind Cloudflare Zero Trust.

Required environment variables (see docs/CF_SIDECAR_PLAN.md):
    CF_TEAM_DOMAIN   e.g. mycompany   (→ mycompany.cloudflareaccess.com)
    CF_ACCESS_AUD    the Access Application Audience (AUD) tag
    CF_ADMIN_EMAILS  optional, comma-separated e-mails granted admin on first login
"""
from __future__ import annotations


def run() -> None:
    import uvicorn

    from app.config import settings

    uvicorn.run(
        "app.cf_wrap:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    run()
