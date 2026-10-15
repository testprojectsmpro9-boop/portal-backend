import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


LIVE_PORTAL_ORIGIN = "https://portal.sirmv-idea.org"


def _sample_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def _cors_route_cases() -> list[tuple[str, str]]:
    cases: list[tuple[str, str]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods or []):
            if method in {"HEAD", "OPTIONS"}:
                continue
            cases.append((method, _sample_path(route.path)))
    return cases


def test_production_portal_origin_is_allowed_by_default():
    assert LIVE_PORTAL_ORIGIN in settings.allowed_origins_list


def test_convert_to_idea_preflight_allows_portal_origin(client):
    response = client.options(
        "/api/v1/admin/intake/INTAKE-0001/convert-to-idea",
        headers={
            "Origin": LIVE_PORTAL_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == LIVE_PORTAL_ORIGIN


@pytest.mark.parametrize(("method", "path"), _cors_route_cases())
def test_all_backend_endpoints_allow_live_portal_origin(client, method, path):
    response = client.options(
        path,
        headers={
            "Origin": LIVE_PORTAL_ORIGIN,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == LIVE_PORTAL_ORIGIN


def test_unhandled_api_errors_still_allow_live_portal_origin():
    test_path = "/__test/cors-unhandled-error"

    if not any(getattr(route, "path", None) == test_path for route in app.routes):
        @app.get(test_path)
        def crash_for_cors_test():
            raise RuntimeError("simulated crash")

    browser_like_client = TestClient(app, raise_server_exceptions=False)
    response = browser_like_client.get(test_path, headers={"Origin": LIVE_PORTAL_ORIGIN})

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == LIVE_PORTAL_ORIGIN
    assert response.json() == {"detail": "Internal server error"}
