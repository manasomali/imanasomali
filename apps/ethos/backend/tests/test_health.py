from fastapi.testclient import TestClient

from app.main import app

# Mesmo root_path que o uvicorn recebe em produção (--root-path /api/ethos)
client = TestClient(app, root_path="/api/ethos")


def test_health_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
