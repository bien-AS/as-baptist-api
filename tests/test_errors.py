"""Problem response behavior at the HTTP boundary."""

import httpx
from app.main import create_app


async def test_unhandled_exception_is_safe_problem_response(
    client: httpx.AsyncClient,
) -> None:
    application = create_app()

    async def explode() -> None:
        raise RuntimeError("database password should not be returned")

    application.add_api_route("/v1/test-explode", explode, methods=["GET"])
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        response = await test_client.get(
            "/v1/test-explode",
            headers={"X-Request-ID": "test-request"},
        )

    body = response.json()
    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert body["code"] == "INTERNAL_ERROR"
    assert body["request_id"] == "test-request"
    assert "database password" not in response.text
    assert "traceback" not in response.text.lower()
