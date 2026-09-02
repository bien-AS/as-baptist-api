"""Public health and readiness behavior."""

import httpx


async def test_health_is_unauthenticated_and_alive(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


async def test_ready_returns_503_when_database_probe_is_unavailable(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/v1/ready")

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "INTERNAL_ERROR"


async def test_ready_returns_200_when_database_probe_is_healthy(
    client: httpx.AsyncClient,
) -> None:
    from app.main import create_app

    application = create_app()

    async def healthy_probe() -> bool:
        return True

    application.state.readiness_probe = healthy_probe
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        response = await test_client.get("/v1/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
