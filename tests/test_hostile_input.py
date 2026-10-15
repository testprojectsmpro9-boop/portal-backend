"""
Phase 14 — hostile-input testing.

Fires malformed/adversarial values at the two business-facing entry points
(public idea submission, admin intake desk) and asserts the only acceptable
outcomes are: intentional success (2xx) or a controlled 4xx response.
An uncontrolled 500, an unhandled traceback, or anything that would leave
the process/DB in a broken state is a failure.

Covers: "@@", "@@test.com", empty string, whitespace-only, very long
strings, emoji, Kannada, Arabic, quotes/apostrophes, HTML/script-looking
text, malformed numbers, unexpected JSON types, weird filenames.
"""
import io

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.idea import Idea
from app.models.idea_file import IdeaFile
from app.models.intake import IntakeSubmission
from app.models.user import ProgramTrack, User, UserRole
from app.utils.security import create_access_token, hash_password

HOSTILE_STRINGS = [
    "",
    "   ",
    "@@",
    "@@test.com",
    "a" * 10000,
    "😀🔥💥🚀" * 50,
    "ಕನ್ನಡ ಪರೀಕ್ಷೆ ವಿಷಯ",
    "اختبار باللغة العربية",
    "O'Brien \"quoted\" text with 'apostrophes'",
    "<script>alert(1)</script>",
    "'; DROP TABLE ideas; --",
    "\x00\x01\x02 control chars",
]


@pytest.fixture
def db_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(
        bind=engine,
        tables=[User.__table__, Idea.__table__, IdeaFile.__table__, IntakeSubmission.__table__],
    )

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestingSessionLocal
    app.dependency_overrides.clear()


def _admin_headers(db_session_factory):
    db = db_session_factory()
    try:
        user = User(
            full_name="Admin",
            email="hostile-admin@example.com",
            phone="1234567890",
            password_hash=hash_password("TestPass123!"),
            role=UserRole.SUPER_ADMIN,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token({"user_id": user.id, "email": user.email, "role": user.role.value})
        return {"Authorization": f"Bearer {token}"}
    finally:
        db.close()


def _base_idea_payload(**overrides):
    payload = {
        "applicant_name": "Test Applicant",
        "email": "valid@example.com",
        "program_track": "NATIONAL_INTERNATIONAL",
        "idea_title": "A Test Idea",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Public idea submission — email IS strictly validated (EmailStr); every
# other free-text field must tolerate hostile input without a 500.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_email", ["@@", "@@test.com", "", "   ", "not-an-email", "a" * 300 + "@example.com"])
def test_public_idea_submission_malformed_email_is_controlled_4xx(client, db_session_factory, bad_email):
    resp = client.post("/api/v1/ideas", json=_base_idea_payload(email=bad_email))
    assert resp.status_code in (400, 422, 429), f"email={bad_email!r} -> {resp.status_code}: {resp.text}"


@pytest.mark.parametrize("hostile", HOSTILE_STRINGS)
def test_public_idea_submission_hostile_free_text_never_crashes(client, db_session_factory, hostile):
    resp = client.post(
        "/api/v1/ideas",
        json=_base_idea_payload(
            applicant_name=hostile or "Applicant",  # required field: keep non-empty when hostile is blank
            idea_title=hostile or "Title",
            problem_statement=hostile,
            solution_description=hostile,
            organization=hostile,
            location=hostile,
        ),
    )
    assert resp.status_code in (200, 201, 400, 422, 429), f"hostile={hostile!r} -> {resp.status_code}: {resp.text}"


def test_public_idea_submission_malformed_age_is_controlled_4xx(client, db_session_factory):
    for bad_age in [-5, "not-a-number", 99999999999999, 3.5, None]:
        resp = client.post("/api/v1/ideas", json=_base_idea_payload(age=bad_age))
        assert resp.status_code in (200, 201, 400, 422, 429), f"age={bad_age!r} -> {resp.status_code}: {resp.text}"


def test_public_idea_submission_garbage_program_track_is_controlled_400(client, db_session_factory):
    resp = client.post("/api/v1/ideas", json=_base_idea_payload(program_track="NOT_A_REAL_TRACK"))
    assert resp.status_code == 400


def test_public_idea_submission_garbage_category_never_crashes(client, db_session_factory):
    for hostile in HOSTILE_STRINGS:
        resp = client.post("/api/v1/ideas", json=_base_idea_payload(category=hostile))
        assert resp.status_code in (200, 201, 400, 422, 429), f"category={hostile!r} -> {resp.status_code}: {resp.text}"


def test_public_idea_submission_unexpected_json_types_are_controlled_422(client, db_session_factory):
    # wrong types entirely for structured fields — pydantic must 422, not 500.
    resp = client.post("/api/v1/ideas", json=_base_idea_payload(team_member_names="not-a-list", age={"nested": "object"}))
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Admin intake desk — email and team_name are intentionally permissive
# (Phase 2). Hostile values there must be accepted or 4xx, never 500.
# ---------------------------------------------------------------------------

def _base_intake_payload(**overrides):
    payload = {
        "source_type": "OFFLINE_FORM",
        "applicant_name": "Intake Applicant",
        "raw_title": "Intake Idea",
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("hostile", HOSTILE_STRINGS)
def test_admin_intake_hostile_email_is_accepted_or_controlled(client, db_session_factory, hostile):
    headers = _admin_headers(db_session_factory)
    resp = client.post("/api/v1/admin/intake", json=_base_intake_payload(email=hostile), headers=headers)
    assert resp.status_code in (200, 201, 400, 422), f"email={hostile!r} -> {resp.status_code}: {resp.text}"


def test_admin_intake_team_submission_with_blank_team_name_is_accepted(client, db_session_factory):
    headers = _admin_headers(db_session_factory)
    resp = client.post(
        "/api/v1/admin/intake",
        json=_base_intake_payload(
            applicant_type="TEAM",
            team_name="",
            team_member_count=2,
            team_member_names=["A", "B"],
        ),
        headers=headers,
    )
    assert resp.status_code in (200, 201), f"-> {resp.status_code}: {resp.text}"


@pytest.mark.parametrize("hostile", HOSTILE_STRINGS)
def test_admin_intake_hostile_free_text_never_crashes(client, db_session_factory, hostile):
    headers = _admin_headers(db_session_factory)
    resp = client.post(
        "/api/v1/admin/intake",
        json=_base_intake_payload(
            applicant_name=hostile or "Applicant",
            raw_title=hostile or "Title",
            raw_description=hostile,
            organization=hostile,
        ),
        headers=headers,
    )
    assert resp.status_code in (200, 201, 400, 422), f"hostile={hostile!r} -> {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# File upload — weird filenames must never crash the upload pipeline.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", [
    "",
    "no_extension",
    "a" * 300 + ".pdf",
    "../../../etc/passwd.pdf",
    "😀emoji_name.pdf",
    "file with spaces.pdf",
    "file.PDF",
    "file.tar.gz.pdf",
])
def test_idea_file_upload_weird_filenames_never_crash(client, db_session_factory, filename):
    headers = _admin_headers(db_session_factory)
    idea_resp = client.post("/api/v1/ideas", json=_base_idea_payload())
    assert idea_resp.status_code == 201
    idea_id = idea_resp.json()["id"]

    resp = client.post(
        f"/api/v1/ideas/{idea_id}/files",
        files={"file": (filename, b"content", "application/pdf")},
        data={"file_type": "DOCUMENT"},
        headers=headers,
    )
    assert resp.status_code in (200, 201, 400, 403, 422), f"filename={filename!r} -> {resp.status_code}: {resp.text}"
