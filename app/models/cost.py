"""Cost ledger and cost budget models (`03` §5, `04` §5.4)."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TenantMixin, TimestampMixin

data_source_type = ENUM(
    "searchatlas",
    "dataforseo",
    "serper",
    "brightlocal",
    "synthetic",
    "computed",
    "client_verified",
    name="data_source",
    create_type=False,
    validate_strings=True,
)


class CostLedger(TenantMixin, Base):
    """One row per billable provider unit group."""

    __tablename__ = "cost_ledger"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    location_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("location.id")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    billing_date: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=text("current_date")
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    units: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    billing: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True))
    approval_id: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True))
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(data_source_type, nullable=False)

    __table_args__ = (
        CheckConstraint("units >= 0", name="cost_ledger_units_check"),
        CheckConstraint(
            "billing in ('billed','plan_credits','projected')",
            name="cost_ledger_billing_check",
        ),
        CheckConstraint(
            "round(units * unit_cost_usd, 4) = cost_usd or billing = 'plan_credits'",
            name="cost_ledger_math",
        ),
        Index("ix_cost_ledger__tenant_period", "tenant_id", "billing_date"),
        Index("ix_cost_ledger__provider", "tenant_id", "provider", "billing_date"),
    )


class CostBudget(TenantMixin, TimestampMixin, Base):
    """The monthly spend ceiling enforced by `cost.assert_budget()`."""

    __tablename__ = "cost_budget"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    monthly_cap_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    per_run_cap_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    balance_floor_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="100.00"
    )
    hard_stop: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    __table_args__ = (UniqueConstraint("tenant_id", "period_month"),)
