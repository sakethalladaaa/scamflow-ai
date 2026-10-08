import asyncio

import httpx

from backend.scamflow.app import create_app
from backend.scamflow.settings import Environment, Settings


def test_health_returns_exact_liveness_contract() -> None:
    app = create_app(Settings(environment=Environment.TEST))

    async def request_health() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get("/health")

    response = asyncio.run(request_health())

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert set(response.json()) == {"status"}
