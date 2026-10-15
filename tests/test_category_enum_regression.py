"""
Regression coverage for the Idea.category <-> PostgreSQL `ideacategory` enum
mapping (see the INTENTIONAL comment on app/models/idea.py's category
column).

A previous `values_callable=lambda enum_cls: [item.value for item in
enum_cls]` mapping caused every category read/write to raise
`DataError: invalid input value for enum ideacategory` because the live
Postgres enum type stores member NAMES ('WATER'), not .value strings
('Water'). These tests round-trip through the REAL configured database
(not SQLite) via a flush + rollback, because SQLite has no native enum
type and would silently pass even with the broken mapping — the bug only
reproduces against actual PostgreSQL.
"""
import pytest

from app.database import SessionLocal
from app.models.idea import Idea, IdeaCategory
from app.models.user import ProgramTrack
from app.models.idea import SourceType
from app.schemas.idea import IdeaOut


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()  # never persists test rows
        session.close()


@pytest.mark.parametrize("index,category", list(enumerate(IdeaCategory)))
def test_every_category_round_trips_through_real_postgres_enum(db, index, category):
    # application_id is varchar(20) — keep this well under the limit
    # regardless of how long a given IdeaCategory member's name is.
    idea = Idea(
        application_id=f"ENUMTST-{index:03d}",
        applicant_name="Enum Regression",
        email="enum-regression@example.com",
        program_track=ProgramTrack.NATIONAL_INTERNATIONAL,
        source_type=SourceType.ONLINE_FORM,
        idea_title="Category enum regression",
        category=category,
        is_public_tracking_enabled=True,
    )
    db.add(idea)
    # flush (not commit) actually sends the INSERT to PostgreSQL — this is
    # the step that raised DataError under the broken values_callable config.
    db.flush()
    db.refresh(idea)
    assert idea.category == category

    # Read back with a fresh query — proves PostgreSQL accepted and can
    # return this enum value, not just that the in-memory object looks right.
    db.expire(idea)
    fetched = db.query(Idea).filter(Idea.id == idea.id).first()
    assert fetched.category == category
    assert fetched.category.name == category.name

    # Serialize through the real API schema — must not raise.
    out = IdeaOut.model_validate(fetched)
    assert out.category == category.name


def test_null_category_is_accepted(db):
    idea = Idea(
        application_id="IDEA-ENUMTEST-NULL",
        applicant_name="Enum Regression Null",
        email="enum-regression-null@example.com",
        program_track=ProgramTrack.NATIONAL_INTERNATIONAL,
        source_type=SourceType.ONLINE_FORM,
        idea_title="Null category regression",
        category=None,
        is_public_tracking_enabled=True,
    )
    db.add(idea)
    db.flush()
    db.refresh(idea)
    assert idea.category is None
    out = IdeaOut.model_validate(idea)
    assert out.category is None
