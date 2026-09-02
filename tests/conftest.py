"""Shared HTTP test fixtures."""

from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from app.main import create_app


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    application = create_app()
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
