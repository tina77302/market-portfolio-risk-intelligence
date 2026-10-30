from fastapi.testclient import TestClient

from src.portfolio.server import app

client = TestClient(app)


def test_health_reports_snapshot_date():
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["as_of"] == "2026-10-23"


def test_frontend_origin_is_allowed():
    response = client.options(
        "/api/portfolio/analyze",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_unknown_origin_is_not_allowed():
    response = client.get(
        "/api/portfolio/universe", headers={"Origin": "http://evil.example"}
    )

    assert "access-control-allow-origin" not in response.headers


def test_router_endpoints_are_mounted():
    paths = set(client.get("/openapi.json").json()["paths"])

    assert {
        "/api/portfolio/universe", "/api/portfolio/scenarios",
        "/api/portfolio/analyze", "/api/portfolio/compare",
    } <= paths
