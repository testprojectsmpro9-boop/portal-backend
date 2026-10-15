from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.idea import Idea, IdeaStatus, SourceType
from app.models.idea_file import IdeaFile
from app.models.user import ProgramTrack, User, UserRole
from app.services.password_reset_service import _portal_reset_url
from app.services.user_notification_service import _user_created_body
from app.utils.security import create_access_token, hash_password


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine, tables=[User.__table__, Idea.__table__, IdeaFile.__table__])

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


def _seed_user(db_session_factory, email, role, program_track=None):
    db = db_session_factory()
    try:
        user = User(
            full_name=email.split("@")[0],
            email=email,
            password_hash=hash_password("TestPass123!"),
            role=role,
            program_track=program_track,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token({"user_id": user.id, "email": user.email, "role": user.role.value})
        return user.id, {"Authorization": f"Bearer {token}"}
    finally:
        db.close()


def _seed_idea(db_session_factory, application_id, program_track):
    db = db_session_factory()
    try:
        idea = Idea(
            application_id=application_id,
            applicant_name="Applicant",
            email="applicant@example.com",
            phone="9999999999",
            program_track=program_track,
            source_type=SourceType.ONLINE_FORM,
            idea_title="Protected Detail Idea",
            current_status=IdeaStatus.SUBMITTED,
            is_public_tracking_enabled=True,
        )
        db.add(idea)
        db.commit()
        db.refresh(idea)
        return idea.id
    finally:
        db.close()


def test_portal_email_links_use_configured_portal_url(monkeypatch):
    monkeypatch.setattr(settings, "PORTAL_URL", "https://portal.ingeniouspark.in/")

    assert _portal_reset_url("abc token") == "https://portal.ingeniouspark.in/reset-password?token=abc%20token"

    user = User(
        full_name="Created User",
        email="created@example.com",
        password_hash="hash",
        role=UserRole.INVENTOR,
    )
    html, text = _user_created_body(user, "TempPass123!")

    assert "https://portal.ingeniouspark.in/login" in html
    assert "https://portal.ingeniouspark.in/login" in text


def test_admin_single_idea_detail_accepts_internal_id_and_application_id(client):
    db_session_factory = _session_factory()
    try:
        _, headers = _seed_user(db_session_factory, "super-detail@example.com", UserRole.SUPER_ADMIN)
        idea_id = _seed_idea(db_session_factory, "IDEA-2026-DETAIL1", ProgramTrack.NATIONAL_INTERNATIONAL)

        by_id = client.get(f"/api/v1/admin/ideas/{idea_id}", headers=headers)
        by_application_id = client.get("/api/v1/admin/ideas/IDEA-2026-DETAIL1", headers=headers)

        assert by_id.status_code == 200
        assert by_id.json()["id"] == idea_id
        assert by_id.json()["application_id"] == "IDEA-2026-DETAIL1"
        assert by_application_id.status_code == 200
        assert by_application_id.json()["id"] == idea_id
    finally:
        _clear_overrides()


def test_scoped_admin_cannot_fetch_out_of_scope_single_idea_detail(client):
    db_session_factory = _session_factory()
    try:
        _, headers = _seed_user(
            db_session_factory,
            "local-detail@example.com",
            UserRole.TEAM_ADMIN_LOCAL,
            ProgramTrack.LOCAL_REGIONAL,
        )
        idea_id = _seed_idea(db_session_factory, "IDEA-2026-GLOBAL1", ProgramTrack.NATIONAL_INTERNATIONAL)

        response = client.get(f"/api/v1/admin/ideas/{idea_id}", headers=headers)

        assert response.status_code == 403
    finally:
        _clear_overrides()


def test_public_idea_detail_remains_blocked(client):
    response = client.get("/api/v1/ideas/IDEA-2026-DETAIL1")

    assert response.status_code == 404
    assert "verified tracking" in response.json()["detail"]
