"""HTTP-facing Location schemas (`05-API-CONTRACT.md` §6.2)."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.location import Location
from app.schemas.common import DataSource


class LocationSummary(BaseModel):
    """The row shape returned by `GET /v1/locations`."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    display_name: str | None = None
    fleet: str | None = None
    listing_type: str
    status: str
    city: str
    state: str

    @classmethod
    def from_model(cls, location: Location) -> "LocationSummary":
        return cls(
            slug=location.slug,
            name=location.name,
            display_name=location.display_name,
            fleet=location.fleet,
            listing_type=location.listing_type,
            status=location.status,
            city=location.city,
            state=location.state,
        )


class LocationRating(BaseModel):
    """Aggregate rating, nested to mirror `05` §8.2's S-12 shape."""

    model_config = ConfigDict(extra="forbid")

    value: Decimal | None = None
    votes: int | None = None


class LocationDetail(BaseModel):
    """The row shape returned by `GET /v1/locations/{slug}`."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    display_name: str | None = None
    listing_type: str
    fleet: str | None = None
    address: str
    city: str
    state: str
    zip: str
    lat: Decimal | None = None
    lng: Decimal | None = None
    cid: str | None = None
    domain: str | None = None
    is_claimed: bool | None = None
    is_verified: bool | None = None
    rating: LocationRating
    status: str
    source: DataSource
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, location: Location) -> "LocationDetail":
        return cls(
            slug=location.slug,
            name=location.name,
            display_name=location.display_name,
            listing_type=location.listing_type,
            fleet=location.fleet,
            address=location.address,
            city=location.city,
            state=location.state,
            zip=location.zip,
            lat=location.lat,
            lng=location.lng,
            cid=location.cid,
            domain=location.domain,
            is_claimed=location.is_claimed,
            is_verified=location.is_verified,
            rating=LocationRating(value=location.rating_value, votes=location.rating_votes),
            status=location.status,
            source=DataSource(location.source),
            created_at=location.created_at,
            updated_at=location.updated_at,
        )


class LocationCreate(BaseModel):
    """The add-location request body (`05` §6.2, operator-only)."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    listing_type: str
    facility_type: str
    address: str
    city: str
    state: str = Field(min_length=2, max_length=2)
    zip: str
    fleet: str | None = None
    lat: Decimal | None = None
    lng: Decimal | None = None
    source: DataSource


class LocationUpdate(BaseModel):
    """A partial update — only supplied fields change."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    status: str | None = None
    lat: Decimal | None = None
    lng: Decimal | None = None
