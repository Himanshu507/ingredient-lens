from fastapi.testclient import TestClient

from api.main import app


def test_root_returns_name() -> None:
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"name": "Regulatory Intelligence Engine"}


def test_health_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_route_still_404s() -> None:
    client = TestClient(app)
    response = client.get("/does-not-exist")

    assert response.status_code == 404
