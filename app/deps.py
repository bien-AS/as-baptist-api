"""FastAPI dependency boundaries for configuration, auth, and tenant scoping."""

from collections.abc import AsyncIterator

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.errors import ApiProblem
from app.core.security import AuthenticatedUser, TokenVerifier, get_token_verifier
from app.db.rls import RequestContext, tenant_context
from app.db.session import get_db_session
from app.schemas import ProblemCode

bearer_scheme = HTTPBearer(auto_error=False)
bearer_credentials = Depends(bearer_scheme)
token_verifier = Depends(get_token_verifier)

OPERATOR_ROLES = frozenset({"as_admin", "as_staff", "system"})


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


current_user = Depends(get_current_user)


def get_tenant_context(user: AuthenticatedUser = current_user) -> RequestContext:
    """Bridge a verified token's claims to the RLS tenant-context contract."""

    if user.tenant_id is None:
        raise ApiProblem.from_code(ProblemCode.TENANT_SCOPE_MISSING)
    return RequestContext(tenant_id=user.tenant_id, actor_id=user.id, role=user.role)


tenant_context_dependency = Depends(get_tenant_context)
db_session_dependency = Depends(get_db_session)


async def get_scoped_db(
    session: AsyncSession = db_session_dependency,
    ctx: RequestContext = tenant_context_dependency,
) -> AsyncIterator[AsyncSession]:
    """Yield a session bound to one RLS-scoped transaction for the request's lifetime."""

    async with tenant_context(session, ctx):
        yield session


def require_operator(ctx: RequestContext = tenant_context_dependency) -> RequestContext:
    """Gate a route to operator roles; a client role gets `403 FORBIDDEN_ROLE`."""

    if ctx.role not in OPERATOR_ROLES:
        raise ApiProblem.from_code(ProblemCode.FORBIDDEN_ROLE)
    return ctx
