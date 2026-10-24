import logging

from app.main import create_app


def test_health_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_returns_503_when_database_is_unavailable(
    make_settings, make_client, tmp_path, caplog
):
    # Pasta que não existe: o sqlite não consegue abrir o arquivo
    missing = tmp_path / "nao-existe"
    client = make_client(create_app(make_settings(database_path=missing / "app.db")))

    with caplog.at_level(logging.WARNING):
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"error": "database_unavailable", "field": None}
    assert "banco indisponível (OperationalError)" in caplog.text
    assert str(missing) not in caplog.text
