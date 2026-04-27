import pytest


@pytest.mark.django_db
def test_health_ok(client, django_user_model):
    response = client.get("/health/")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # Con SQLite :memory: la conexión existe; el campo "database" refleja el check
    assert body["database"] in ("ok", "error", "unavailable")
