"""Tenant-spine metadata contracts."""

from app.models import Base


def test_tenant_spine_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "tenant",
        "user_profile",
        "membership",
        "membership_location",
        "tenant_credential",
        "location",
        "location_alias",
        "audit_card",
        "cost_ledger",
        "cost_budget",
        "cost_preview",
        "approval",
    }


def test_external_auth_id_is_required_and_not_generated() -> None:
    column = Base.metadata.tables["user_profile"].c.id

    assert column.primary_key
    assert column.default is None
    assert column.server_default is None


def test_tenant_spine_constraints_and_secret_reference() -> None:
    membership = Base.metadata.tables["membership"]
    credentials = Base.metadata.tables["tenant_credential"]

    unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in membership.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("tenant_id", "user_id") in unique_columns
    assert "secret_ref" in credentials.c
    assert "secret" not in credentials.c
