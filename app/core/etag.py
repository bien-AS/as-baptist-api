"""Tenant-scoped ETags for conditional GET (`05` §5, BE-09)."""

import hashlib

from app.db.rls import RequestContext


def compute_etag(ctx: RequestContext, payload: str) -> str:
    """A strong ETag scoped to one tenant.

    `tenant_id` is part of the hashed input, not just a display prefix, so
    two tenants can never collide on the same ETag for equal-looking content
    even if the digest itself happened to collide (BE-09's core requirement).
    """

    digest = hashlib.sha256(f"{ctx.tenant_id}:{payload}".encode()).hexdigest()
    return f'"{ctx.tenant_id}.{digest}"'


def matches(if_none_match: str | None, etag: str) -> bool:
    return if_none_match is not None and if_none_match == etag
