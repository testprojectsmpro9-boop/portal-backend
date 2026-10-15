import pytest
from fastapi import HTTPException

from app.routers.ideas import get_idea


def test_public_idea_detail_is_not_exposed():
    with pytest.raises(HTTPException) as exc:
        get_idea("IDEA-2026-ABC123")
    assert exc.value.status_code == 404
    assert "verified tracking" in exc.value.detail
