"""FastAPI dependency boundaries for configuration and authentication."""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings
from app.core.errors import ApiProblem
from app.core.security import AuthenticatedUser, TokenVerifier, get_token_verifier
from app.schemas import ProblemCode

bearer_scheme = HTTPBearer(auto_error=False)
bearer_credentials = Depends(bearer_scheme)
token_verifier = Depends(get_token_verifier)


def settings_dependency() -> Settings:
    """Return the cached process configuration."""

    return get_settings()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = bearer_credentials,
    verifier: TokenVerifier = token_verifier,
) -> AuthenticatedUser:
    """Authenticate a request at the API boundary."""

    if credentials is None:
        raise ApiProblem.from_code(ProblemCode.UNAUTHENTICATED)
    return await verifier.verify(credentials.credentials)
