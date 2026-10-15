import re
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models.idea import Idea
from app.services import id_generator
from app.services.id_generator import generate_unique_year_id


def _db_with_exists(value):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = value
    return db


def test_generated_id_includes_prefix_and_year(monkeypatch):
    monkeypatch.setattr(id_generator, "_random_suffix", lambda length=6: "A7K92P")
    value = generate_unique_year_id(_db_with_exists(None), Idea, "application_id", "IDEA")
    assert value == f"IDEA-{datetime.utcnow().year}-A7K92P"
    assert re.match(r"^IDEA-\d{4}-[A-Z0-9]{6}$", value)


def test_generated_ids_are_not_equal():
    first = generate_unique_year_id(_db_with_exists(None), Idea, "application_id", "IDEA")
    second = generate_unique_year_id(_db_with_exists(None), Idea, "application_id", "IDEA")
    assert first != second


def test_generator_collision_retry_behavior(monkeypatch):
    suffixes = iter(["ABC123", "DEF456"])
    monkeypatch.setattr(id_generator, "_random_suffix", lambda length=6: next(suffixes))
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [object(), None]

    value = generate_unique_year_id(db, Idea, "application_id", "IDEA")

    assert value == f"IDEA-{datetime.utcnow().year}-DEF456"
    assert db.query.return_value.filter.return_value.first.call_count == 2


def test_generator_raises_after_max_collisions(monkeypatch):
    monkeypatch.setattr(id_generator, "_random_suffix", lambda length=6: "ABC123")
    with pytest.raises(HTTPException) as exc:
        generate_unique_year_id(
            _db_with_exists(object()),
            Idea,
            "application_id",
            "IDEA",
            max_attempts=2,
        )
    assert exc.value.status_code == 500
