"""HTTP-facing identity schemas (`05-API-CONTRACT.md` §8.2, S-03)."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MeUser(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    email: str
    full_name: str | None = None


class MeTenant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    slug: str
    name: str
    tier: str


class MeResponse(BaseModel):
    """The `GET /v1/me` payload — proves the full JWT -> tenant seam end-to-end."""

    model_config = ConfigDict(extra="forbid")

    user: MeUser
    tenant: MeTenant
    role: str
    location_scope: list[str] | None = None
    must_accept_invite: bool = False
