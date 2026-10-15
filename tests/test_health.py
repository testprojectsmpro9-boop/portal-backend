from fastapi.testclient import TestClient
from app.config import settings
from app.main import app

client = TestClient(app)


def test_root_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "NMF-IFIA" in data["app"]


def test_api_v1_health():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_docs_accessible():
    # /docs is exposed only in non-production environments.
    response = client.get("/docs")
    expected = 404 if settings.is_production else 200
    assert response.status_code == expected


def test_openapi_schema():
    # /openapi.json is exposed only in non-production environments.
    response = client.get("/openapi.json")
    if settings.is_production:
        assert response.status_code == 404
        return
    assert response.status_code == 200
    schema = response.json()
    assert "NMF-IFIA" in schema["info"]["title"]
