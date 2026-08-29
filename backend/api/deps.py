"""Shared API-layer guards and dependencies."""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request

from backend.config import settings


def require_local_or_key(request: Request) -> None:
    """Allow loopback requests, or remote requests carrying a valid API key.

    Used for mutating endpoints (config writes, backups, maintenance) that
    should not be reachable from other machines unless auth is configured.
    """
    client_host = request.client.host if request.client else ""
    if client_host in ("127.0.0.1", "::1", "localhost"):
        return
    api_key = request.headers.get("X-API-Key") or ""
    if settings.api_key and secrets.compare_digest(api_key, settings.api_key):
        return
    raise HTTPException(
        status_code=403,
        detail="该接口仅允许本机访问，或需配置 TOKEN_STAT_API_KEY 并携带 X-API-Key 请求头",
    )
