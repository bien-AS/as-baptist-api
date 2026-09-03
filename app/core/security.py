"""JWT/JWKS verification boundary with a credential-free local mode."""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast
from uuid import UUID

import httpx
import jwt
from fastapi import Request
from jwt.algorithms import RSAAlgorithm
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from pydantic import BaseModel, ConfigDict, Field

from app.config import AuthMode, Settings
from app.core.errors import ApiProblem
from app.schemas import ProblemCode

JsonObject = dict[str, Any]
JwksFetcher = Callable[[str], Awaitable[Mapping[str, JsonObject]]]


class AuthenticatedUser(BaseModel):
    """Claims consumed by API dependencies and the database context seam."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID | None = None
    role: str
    claims: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_claims(cls, claims: Mapping[str, Any]) -> "AuthenticatedUser":
        subject = claims.get("sub")
        if not isinstance(subject, str):
            raise ValueError("JWT subject is missing")
        tenant_claim = claims.get("tenant_id")
        tenant_id = UUID(tenant_claim) if isinstance(tenant_claim, str) else None
        role = claims.get("role", "client_user")
        if not isinstance(role, str):
            raise ValueError("JWT role is invalid")
        return cls(id=UUID(subject), tenant_id=tenant_id, role=role, claims=dict(claims))


class JwksCache:
    """Concurrency-safe ten-minute cache for a JWKS document."""

    def __init__(self, fetcher: JwksFetcher | None = None, ttl_seconds: int = 600) -> None:
        self._fetcher = fetcher or self._fetch
        self._ttl_seconds = ttl_seconds
        self._expires_at = 0.0
        self._keys: Mapping[str, JsonObject] = {}
        self._lock = asyncio.Lock()

    async def get(self, url: str) -> Mapping[str, JsonObject]:
        now = time.monotonic()
        if now < self._expires_at and self._keys:
            return self._keys
        async with self._lock:
            now = time.monotonic()
            if now < self._expires_at and self._keys:
                return self._keys
            keys = await self._fetcher(url)
            if not keys:
                raise ValueError("JWKS response contains no usable keys")
            self._keys = keys
            self._expires_at = time.monotonic() + self._ttl_seconds
            return self._keys

    @staticmethod
    async def _fetch(url: str) -> Mapping[str, JsonObject]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
            raise ValueError("JWKS response has an invalid shape")
        result: dict[str, JsonObject] = {}
        for raw_key in payload["keys"]:
            if isinstance(raw_key, dict) and isinstance(raw_key.get("kid"), str):
                result[raw_key["kid"]] = cast(JsonObject, raw_key)
        return result


class TokenVerifier:
    """Verify local mock tokens or RS256 Supabase JWTs."""

    def __init__(self, settings: Settings, jwks_cache: JwksCache | None = None) -> None:
        self._settings = settings
        self._jwks_cache = jwks_cache or JwksCache()

    async def verify(self, token: str) -> AuthenticatedUser:
        if self._settings.auth_mode is AuthMode.mock:
            return self._verify_mock(token)
        return await self._verify_supabase(token)

    def _verify_mock(self, token: str) -> AuthenticatedUser:
        if token != self._settings.mock_auth_token:
            raise ApiProblem.from_code(ProblemCode.UNAUTHENTICATED)
        return AuthenticatedUser(
            id=self._settings.mock_auth_user_id,
            tenant_id=self._settings.mock_auth_tenant_id,
            role=self._settings.mock_auth_role,
            claims={"sub": str(self._settings.mock_auth_user_id), "mock": True},
        )

    async def _verify_supabase(self, token: str) -> AuthenticatedUser:
        jwks_url = self._settings.supabase_jwks_url
        if not jwks_url:
            raise ApiProblem.from_code(ProblemCode.UNAUTHENTICATED)
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if header.get("alg") != "RS256" or not isinstance(kid, str):
                raise InvalidTokenError("unsupported JWT header")
            keys = await self._jwks_cache.get(jwks_url)
            jwk = keys.get(kid)
            if jwk is None:
                raise InvalidTokenError("unknown JWT key")
            public_key = cast(Any, RSAAlgorithm.from_jwk(json.dumps(jwk)))
            decode_options: dict[str, Any] = {
                "require": ["exp", "sub"],
                "verify_aud": self._settings.supabase_jwt_audience is not None,
                "verify_iss": self._settings.supabase_jwt_issuer is not None,
            }
            decode_kwargs: dict[str, Any] = {
                "algorithms": ["RS256"],
                "options": decode_options,
            }
            if self._settings.supabase_jwt_audience:
                decode_kwargs["audience"] = self._settings.supabase_jwt_audience
            if self._settings.supabase_jwt_issuer:
                decode_kwargs["issuer"] = self._settings.supabase_jwt_issuer
            claims = jwt.decode(token, public_key, **decode_kwargs)
            if not isinstance(claims, dict):
                raise InvalidTokenError("JWT claims are not an object")
            return AuthenticatedUser.from_claims(claims)
        except ExpiredSignatureError as exc:
            raise ApiProblem.from_code(ProblemCode.TOKEN_EXPIRED) from exc
        except (InvalidTokenError, TypeError, ValueError, KeyError, httpx.HTTPError) as exc:
            raise ApiProblem.from_code(ProblemCode.UNAUTHENTICATED) from exc


def get_token_verifier(request: Request) -> TokenVerifier:
    """Resolve the verifier created once during application construction."""

    verifier = getattr(request.app.state, "token_verifier", None)
    if not isinstance(verifier, TokenVerifier):
        raise RuntimeError("token verifier is not configured")
    return verifier
