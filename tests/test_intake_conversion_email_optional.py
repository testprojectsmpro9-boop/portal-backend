"""
Final blocker check — POST /admin/intake/{intake_id}/convert-to-idea must
NOT require a non-empty/valid email or a non-blank team_name. Admin intake
email/team_name are optional business data; ideas.email is NOT NULL at the
DB level so a blank intake email is stored as "" rather than raising.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.idea import Idea
from app.models.idea_file import IdeaFile
from app.models.intake import IntakeSubmission
from app.models.intake_file import IntakeFile
from app.models.user import User, UserRole
from app.utils.security import create_access_token


def _session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__, Idea.__table__, IntakeSubmission.__table__,
            IdeaFile.__table__, IntakeFile.__table__, AuditLog.__table__,
        ],
    )

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestingSessionLocal


def _clear_overrides():
    app.dependency_overrides.clear()


def _headers_for_role(db_session_factory, email, role):
    db = db_session_factory()
    try:
        user = User(full_name=email.split("@")[0], email=email, password_hash="not-used", role=role, is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token({"user_id": user.id, "email": user.email, "role": user.role.value})
        return {"Authorization": f"Bearer {token}"}
    finally:
        db.close()


def _intake_payload(**overrides):
    data = {
        "source_type": "OFFLINE_FORM",
        "source_program": "NMF_NATIONAL",
        "applicant_type": "INDIVIDUAL",
        "applicant_name": "Conversion Test",
        "phone": "9999999999",
        "location": "Mysuru",
        "raw_title": "Conversion email-optional regression",
        "raw_description": "Offline entry",
        "problem_statement": "Problem",
        "solution_description": "Solution",
        "category": "Water",
        "target_users": "Residents",
        "prototype_status": "Only an idea / concept",
        "support_needed": "Mentorship",
        "consent_data": True,
        "consent_original": True,
        "consent_contact": True,
    }
    data.update(overrides)
    return data


def _create_and_convert(client, headers, **overrides):
    created = client.post("/api/v1/admin/intake", json=_intake_payload(**overrides), headers=headers)
    assert created.status_code == 201, created.text
    intake_id = created.json()["intake_id"]

    complete = client.post(f"/api/v1/admin/intake/{intake_id}/mark-complete", headers=headers)
    assert complete.status_code == 200, complete.text

    return client.post(f"/api/v1/admin/intake/{intake_id}/convert-to-idea", headers=headers)


def test_blank_email_converts_successfully(client):
    db_session_factory = _session_factory()
    try:
        headers = _headers_for_role(db_session_factory, "admin-conv-blank@example.com", UserRole.SUPER_ADMIN)
        resp = _create_and_convert(client, headers, email=None)
        assert resp.status_code == 200, resp.text
        idea_id = resp.json()["standardized_idea_id"]
        detail = client.get(f"/api/v1/admin/ideas/{idea_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["email"] == ""
    finally:
        _clear_overrides()


def test_at_at_email_does_not_produce_500(client):
    db_session_factory = _session_factory()
    try:
        headers = _headers_for_role(db_session_factory, "admin-conv-atat@example.com", UserRole.SUPER_ADMIN)
        resp = _create_and_convert(client, headers, email="@@")
        assert resp.status_code == 200, resp.text
        idea_id = resp.json()["standardized_idea_id"]
        detail = client.get(f"/api/v1/admin/ideas/{idea_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["email"] == "@@"
    finally:
        _clear_overrides()


def test_malformed_ampersand_email_does_not_produce_500(client):
    db_session_factory = _session_factory()
    try:
        headers = _headers_for_role(db_session_factory, "admin-conv-amp@example.com", UserRole.SUPER_ADMIN)
        resp = _create_and_convert(client, headers, email="abc&gmail.com")
        assert resp.status_code == 200, resp.text
        idea_id = resp.json()["standardized_idea_id"]
        detail = client.get(f"/api/v1/admin/ideas/{idea_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["email"] == "abc&gmail.com"
    finally:
        _clear_overrides()


def test_blank_team_name_converts_successfully_for_team_submission(client):
    db_session_factory = _session_factory()
    try:
        headers = _headers_for_role(db_session_factory, "admin-conv-team@example.com", UserRole.SUPER_ADMIN)
        resp = _create_and_convert(
            client,
            headers,
            applicant_type="TEAM",
            team_name="",
            team_member_count=2,
            team_member_names=["A", "B"],
            email="team-conv@example.com",
        )
        assert resp.status_code == 200, resp.text
        idea_id = resp.json()["standardized_idea_id"]
        detail = client.get(f"/api/v1/admin/ideas/{idea_id}", headers=headers)
        assert detail.status_code == 200
        assert not detail.json()["team_name"]
    finally:
        _clear_overrides()
