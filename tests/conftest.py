import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.rate_limit import reset_rate_limits


@pytest.fixture(autouse=True)
def clear_rate_limits():
    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture
def client():
    return TestClient(app)
