"""JWT boundary behavior without cloud credentials."""

from app.config import Settings
from app.core.errors import ApiProblem
from app.core.security import TokenVerifier
from app.schemas import ProblemCode


async def test_local_mock_auth_verifies_without_network() -> None:
    verifier = TokenVerifier(Settings())

    user = await verifier.verify("dev-token")

    assert user.role == "as_admin"
    assert user.tenant_id is not None


async def test_invalid_local_mock_token_is_unauthenticated() -> None:
    verifier = TokenVerifier(Settings())

    try:
        await verifier.verify("wrong-token")
    except ApiProblem as exc:
        assert exc.code is ProblemCode.UNAUTHENTICATED
    else:
        raise AssertionError("invalid mock token was accepted")


async def test_jwks_cache_fetches_once() -> None:
    calls = 0

    async def fetcher(_: str) -> dict[str, dict[str, str]]:
        nonlocal calls
        calls += 1
        return {"key-1": {"kid": "key-1", "kty": "RSA"}}

    from app.core.security import JwksCache

    cache = JwksCache(fetcher=fetcher)
    await cache.get("https://example.test/.well-known/jwks.json")
    await cache.get("https://example.test/.well-known/jwks.json")

    assert calls == 1
