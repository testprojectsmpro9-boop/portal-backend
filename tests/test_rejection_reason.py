"""
Phase 8 regression — `Idea.rejection_reason` (see app/models/idea.py's
`rejection_reason` property) actually shows up correctly through the real
API for both:
  1. new records with a proper IdeaDecision row (REJECTED decision), and
  2. historical records that predate decision-tracking (falls back to the
     idea's own admin_message field).
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.decision import IdeaDecision
from app.models.idea import Idea, IdeaStatus, SourceType
from app.models.idea_file import IdeaFile
from app.models.message import Message
from app.models.status_history import StatusHistory
from app.models.user import ProgramTrack, User, UserRole
from app.utils.security import create_access_token


def _session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__, Idea.__table__, IdeaDecision.__table__,
            StatusHistory.__table__, Message.__table__, IdeaFile.__table__,
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


def _headers_for_role(db_session_factory, email, role, program_track=None):
    db = db_session_factory()
    try:
        user = User(
            full_name=email.split("@")[0], email=email, password_hash="not-used",
            role=role, program_track=program_track, is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token({"user_id": user.id, "email": user.email, "role": user.role.value})
        return {"Authorization": f"Bearer {token}"}, user.id
    finally:
        db.close()


def _seed_idea(db_session_factory, application_id, current_status=IdeaStatus.SUBMITTED, admin_message=None):
    db = db_session_factory()
    try:
        idea = Idea(
            application_id=application_id,
            applicant_name="Rejection Reason Test",
            email=f"{application_id.lower()}@example.com",
            program_track=ProgramTrack.NATIONAL_INTERNATIONAL,
            source_type=SourceType.ONLINE_FORM,
            idea_title="Rejection reason regression",
            current_status=current_status,
            admin_message=admin_message,
            is_public_tracking_enabled=True,
        )
        db.add(idea)
        db.commit()
        db.refresh(idea)
        return idea.id
    finally:
        db.close()


def test_new_record_uses_decision_public_message_as_rejection_reason(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, "admin-rr1@example.com", UserRole.SUPER_ADMIN)
        idea_id = _seed_idea(db_session_factory, "RR-NEW-001")

        decision_resp = client.post(
            f"/api/v1/admin/ideas/{idea_id}/decision",
            json={
                "decision": "REJECTED",
                "admin_note": "internal only, never shown to inventor",
                "public_message": "Feasibility score below threshold for this cycle.",
            },
            headers=headers,
        )
        assert decision_resp.status_code == 201, decision_resp.text

        detail = client.get(f"/api/v1/admin/ideas/{idea_id}", headers=headers)
        assert detail.status_code == 200
        body = detail.json()
        assert body["current_status"] == "REJECTED_BY_JURY"
        assert body["rejection_reason"] == "Feasibility score below threshold for this cycle."

        # Must also show up in the plain ideas list, not just idea detail.
        listing = client.get("/api/v1/admin/ideas", headers=headers)
        assert listing.status_code == 200
        row = next(r for r in listing.json() if r["id"] == idea_id)
        assert row["rejection_reason"] == "Feasibility score below threshold for this cycle."
    finally:
        _clear_overrides()


def test_historical_record_falls_back_to_admin_message(client):
    """Records rejected before idea_decisions existed have no IdeaDecision
    row — rejection_reason must fall back to the plain admin_message field
    rather than come back null/blank."""
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, "admin-rr2@example.com", UserRole.SUPER_ADMIN)
        idea_id = _seed_idea(
            db_session_factory,
            "RR-HIST-001",
            current_status=IdeaStatus.PUBLIC_DOMAIN_REJECTED,
            admin_message="Rejected during public domain review (legacy record).",
        )

        detail = client.get(f"/api/v1/admin/ideas/{idea_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["rejection_reason"] == "Rejected during public domain review (legacy record)."
    finally:
        _clear_overrides()


def test_non_rejected_idea_has_no_rejection_reason(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, "admin-rr3@example.com", UserRole.SUPER_ADMIN)
        idea_id = _seed_idea(db_session_factory, "RR-OK-001", current_status=IdeaStatus.SUBMITTED, admin_message="unrelated note")

        detail = client.get(f"/api/v1/admin/ideas/{idea_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["rejection_reason"] is None
    finally:
        _clear_overrides()
