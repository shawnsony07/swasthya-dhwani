"""Keycloak JWT auth for the dashboard API (docs/api_contract.md, "Auth").

Two dependencies are exposed:

- `get_current_roles`: any authenticated caller; returns the realm roles
  from the token's `realm_access.roles` claim.
- `require_role(*roles)`: 403s unless at least one of `roles` is present.
  The contract only ever needs a single required role (`approve` ->
  `doctor`) or an either-of pair (`reject` -> `doctor` or `nurse`), so one
  variadic factory covers both without a second dependency.

`AUTH_DISABLED=true` bypasses all JWT handling and treats every caller as
having every role (`admin`, `doctor`, `nurse`) -- an opt-in dev/offline
escape hatch, loudly logged at startup (see `app.py`'s lifespan), never
the default. It grants every role, not just `admin`, because the point of
disabling auth for local work is that nothing is gated -- a bypass that
still 403s a `doctor`-only route would defeat its own purpose.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx
import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

logger = structlog.get_logger(__name__)

_JWKS_CACHE_TTL_SECONDS = 300.0


def _keycloak_realm() -> str:
    return os.environ.get("KEYCLOAK_REALM", "swasthya")

# Simple timestamped cache rather than cachetools.TTLCache: there is
# exactly one cache entry (the JWKS document for one realm), so a TTLCache
# would add a dependency for no behavior a dict+timestamp doesn't already
# give us, keeping this easy to reason about.
_jwks_cache: dict[str, Any] | None = None
_jwks_cache_at: float = 0.0

_bearer_scheme = HTTPBearer(auto_error=False)


def _auth_disabled() -> bool:
    return os.environ.get("AUTH_DISABLED", "").strip().lower() == "true"


def _keycloak_base_url() -> str:
    return os.environ.get("KEYCLOAK_BASE_URL", "http://localhost:8081")


def _jwks_url() -> str:
    return f"{_keycloak_base_url()}/realms/{_keycloak_realm()}/protocol/openid-connect/certs"


async def _fetch_jwks() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(_jwks_url())
        response.raise_for_status()
        return response.json()


async def _get_jwks(*, force_refresh: bool = False) -> dict[str, Any]:
    """Cached JWKS fetch. `force_refresh=True` bypasses the cache -- used
    once after a signature-verification failure in case Keycloak rotated
    its signing keys since the last fetch."""
    global _jwks_cache, _jwks_cache_at
    now = time.monotonic()
    stale = _jwks_cache is None or (now - _jwks_cache_at) > _JWKS_CACHE_TTL_SECONDS
    if force_refresh or stale:
        _jwks_cache = await _fetch_jwks()
        _jwks_cache_at = now
    assert _jwks_cache is not None
    return _jwks_cache


def _find_key(jwks: dict[str, Any], kid: str | None) -> dict[str, Any] | None:
    for key in jwks.get("keys", []):
        if kid is None or key.get("kid") == kid:
            return key
    return None


async def _decode_token(token: str) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="malformed token"
        ) from exc

    kid = header.get("kid")
    jwks = await _get_jwks()
    key = _find_key(jwks, kid)

    # verify_aud=False: the contract names signature + exp as the checks
    # performed; it does not specify an expected audience, and Keycloak's
    # default `account` audience varies by client setup. A judgment call
    # -- see the report for this task.
    decode_options = {"verify_aud": False}
    try:
        if key is None:
            raise JWTError(f"no signing key found for kid={kid!r}")
        return jwt.decode(token, key, algorithms=["RS256"], options=decode_options)
    except JWTError:
        # Keys may have rotated since our cache was populated (or we never
        # had this kid at all): force one refresh and retry before giving
        # up, rather than hitting Keycloak on every request.
        jwks = await _get_jwks(force_refresh=True)
        key = _find_key(jwks, kid)
        if key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
            ) from None
        try:
            return jwt.decode(token, key, algorithms=["RS256"], options=decode_options)
        except JWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
            ) from exc


async def _roles_for_token(token: str) -> set[str]:
    try:
        claims = await _decode_token(token)
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        logger.error("auth.jwks_fetch_failed", detail=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unable to verify token"
        ) from exc

    roles = claims.get("realm_access", {}).get("roles", [])
    return set(roles)


async def get_current_roles(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> set[str]:
    """Any authenticated caller. Returns the realm roles from
    `realm_access.roles` (standard Keycloak claim shape)."""
    if _auth_disabled():
        return {"admin", "doctor", "nurse"}

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token"
        )

    return await _roles_for_token(credentials.credentials)


async def get_current_roles_sse(request: Request) -> set[str]:
    """Same as `get_current_roles`, but also accepts the token as a
    `?token=` query parameter.

    `GET /alerts/stream` is consumed by the browser's native `EventSource`,
    which cannot set an `Authorization` header — a query-param token is the
    documented workaround (docs/api_contract.md's own note on this), so
    this endpoint is the one place that fallback is honored. A header still
    takes priority if a non-browser client sends one."""
    if _auth_disabled():
        return {"admin", "doctor", "nurse"}

    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:]
    else:
        token = request.query_params.get("token", "")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token (header or ?token= query param)",
        )

    return await _roles_for_token(token)


def require_role(*roles: str) -> Any:
    """Dependency factory: 403s unless the caller has at least one of
    `roles`. `require_role("doctor")` for approve; `require_role("doctor",
    "nurse")` for reject."""
    required = set(roles)

    async def _check(
        current_roles: set[str] = Depends(get_current_roles),
    ) -> set[str]:
        if not (current_roles & required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires role: {' or '.join(sorted(required))}",
            )
        return current_roles

    return _check
