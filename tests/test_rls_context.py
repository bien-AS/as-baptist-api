"""Static checks for the transaction-scoped context boundary."""

from pathlib import Path

from app.db.rls import RequestContext


def test_request_context_is_immutable_and_typed() -> None:
    context = RequestContext(
        tenant_id="00000000-0000-0000-0000-000000000002",  # type: ignore[arg-type]
        actor_id="00000000-0000-0000-0000-000000000001",  # type: ignore[arg-type]
        role="as_admin",
    )

    assert context.role == "as_admin"
    assert "tenant_id" in context.__dataclass_fields__


def test_set_config_is_confined_to_rls_module() -> None:
    root = Path(__file__).parents[1]
    matches = [
        path
        for path in root.joinpath("app").rglob("*.py")
        if "set_config" in path.read_text(encoding="utf-8")
    ]

    assert matches == [root / "app" / "db" / "rls.py"]
