from fastapi.testclient import TestClient

from api.main import app


def test_app_starts_and_responds() -> None:
    client = TestClient(app)
    response = client.get("/")

    # No routes exist yet (Brick 4 adds GET / and GET /health) — a 404
    # still proves the ASGI app booted and is routing requests correctly,
    # as opposed to raising on import or on startup.
    assert response.status_code == 404
