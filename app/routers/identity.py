"""Identity HTTP routes (`05` §6.1, §8.2 S-03) — the first proof of the full seam."""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.envelope import build_meta
from app.core.errors import ApiProblem
from app.core.etag import compute_etag, matches
from app.db.rls import RequestContext
from app.deps import get_scoped_db, tenant_context_dependency
from app.schemas import Envelope, ProblemCode
from app.schemas.identity import MeResponse, MeTenant, MeUser

router = APIRouter(prefix="/v1", tags=["identity"])

scoped_db_dependency = Depends(get_scoped_db)

ME_QUERY = text(
    "select u.id as user_id, u.email, u.full_name, "
    "       t.id as tenant_id, t.slug, t.name, t.tier, "
    "       m.status as membership_status "
    "from user_profile u "
    "join tenant t on t.id = :tenant_id "
    "left join membership m on m.tenant_id = t.id and m.user_id = u.id "
    "where u.id = :actor_id"
)


@router.get("/me", response_model=Envelope[MeResponse])
async def get_me(
    request: Request,
    response: Response,
    ctx: RequestContext = tenant_context_dependency,
    session: AsyncSession = scoped_db_dependency,
) -> Envelope[MeResponse] | Response:
    """`GET /v1/me` — JWT verify -> `tenant_context()` -> RLS-scoped read, in one call."""

    row = (
        await session.execute(
            ME_QUERY, {"tenant_id": ctx.tenant_id, "actor_id": ctx.actor_id}
        )
    ).one_or_none()
    if row is None:
        raise ApiProblem.from_code(ProblemCode.NOT_FOUND)

    data = MeResponse(
        user=MeUser(id=row.user_id, email=row.email, full_name=row.full_name),
        tenant=MeTenant(id=row.tenant_id, slug=row.slug, name=row.name, tier=row.tier),
        role=ctx.role,
        must_accept_invite=row.membership_status == "pending",
    )
    etag = compute_etag(ctx, data.model_dump_json())
    response.headers["ETag"] = etag
    if matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers={"ETag": etag})
    return Envelope(data=data, meta=build_meta(request, ctx, source="computed"))
