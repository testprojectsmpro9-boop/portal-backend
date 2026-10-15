import importlib.util
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.idea import Idea, IdeaStatus, SourceType
from app.models.idea_file import IdeaFile
from app.models.user import ProgramTrack, User, UserRole
from app.services.audit_log_service import sanitize_audit_values
from app.utils.security import create_access_token, hash_password


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(
        bind=engine,
        tables=[User.__table__, Idea.__table__, IdeaFile.__table__, AuditLog.__table__],
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


def _seed_user(db_session_factory, email, role, program_track=None, password="TestPass123!"):
    db = db_session_factory()
    try:
        user = User(
            full_name=email.split("@")[0],
            email=email,
            password_hash=hash_password(password),
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


def _seed_idea(db_session_factory):
    db = db_session_factory()
    try:
        idea = Idea(
            application_id="IDEA-2026-AUDIT1",
            applicant_name="Audit Applicant",
            email="applicant@example.com",
            phone="1234567890",
            program_track=ProgramTrack.NATIONAL_INTERNATIONAL,
            source_type=SourceType.ONLINE_FORM,
            idea_title="Audited Idea",
            current_status=IdeaStatus.SUBMITTED,
            is_public_tracking_enabled=True,
        )
        db.add(idea)
        db.commit()
        db.refresh(idea)
        return idea.id, idea.application_id
    finally:
        db.close()


def _audit_logs(db_session_factory):
    db = db_session_factory()
    try:
        return db.query(AuditLog).order_by(AuditLog.id.asc()).all()
    finally:
        db.close()


def test_admin_create_user_creates_audit_log(client):
    db_session_factory = _session_factory()
    try:
        _, headers = _seed_user(db_session_factory, "super-audit@example.com", UserRole.SUPER_ADMIN)

        response = client.post(
            "/api/v1/admin/users",
            json={
                "full_name": "Created Audit User",
                "email": "created-audit@example.com",
                "phone": "1234567890",
                "password": "CreatedPass123!",
                "role": "INVENTOR",
                "program_track": "NATIONAL_INTERNATIONAL",
            },
            headers=headers,
        )

        assert response.status_code == 201
        logs = _audit_logs(db_session_factory)
        assert len(logs) == 1
        assert logs[0].action == "admin_user_created"
        assert logs[0].entity_type == "user"
        assert logs[0].entity_display_id == "created-audit@example.com"
        assert "password" not in logs[0].new_values
        assert "password_hash" not in logs[0].new_values
    finally:
        _clear_overrides()


def test_admin_deactivate_user_creates_audit_log(client):
    db_session_factory = _session_factory()
    try:
        _, headers = _seed_user(db_session_factory, "super-status-audit@example.com", UserRole.SUPER_ADMIN)
        target_id, _ = _seed_user(
            db_session_factory,
            "target-status-audit@example.com",
            UserRole.INVENTOR,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )

        response = client.patch(
            f"/api/v1/admin/users/{target_id}/status",
            json={"is_active": False},
            headers=headers,
        )

        assert response.status_code == 200
        log = _audit_logs(db_session_factory)[0]
        assert log.action == "admin_user_status_updated"
        assert log.old_values == {"is_active": True}
        assert log.new_values == {"is_active": False}
    finally:
        _clear_overrides()


def test_admin_idea_status_update_creates_audit_log(client):
    db_session_factory = _session_factory()
    try:
        _, headers = _seed_user(db_session_factory, "super-idea-audit@example.com", UserRole.SUPER_ADMIN)
        idea_id, application_id = _seed_idea(db_session_factory)

        response = client.patch(
            f"/api/v1/admin/ideas/{idea_id}/status",
            json={"current_status": "UNDER_VERIFICATION"},
            headers=headers,
        )

        assert response.status_code == 200
        log = _audit_logs(db_session_factory)[0]
        assert log.action == "admin_idea_status_updated"
        assert log.entity_display_id == application_id
        assert log.old_values["current_status"] == "SUBMITTED"
        assert log.new_values["current_status"] == "UNDER_VERIFICATION"
    finally:
        _clear_overrides()


def test_admin_file_upload_creates_audit_log(client, monkeypatch, tmp_path):
    db_session_factory = _session_factory()
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    try:
        _, headers = _seed_user(db_session_factory, "super-file-audit@example.com", UserRole.SUPER_ADMIN)
        idea_id, application_id = _seed_idea(db_session_factory)

        response = client.post(
            f"/api/v1/admin/ideas/{idea_id}/files",
            data={"file_type": "DOCUMENT", "description": "Offline proof"},
            files={"file": ("proof.pdf", b"%PDF-1.4\ncontent", "application/pdf")},
            headers=headers,
        )

        assert response.status_code == 201
        log = _audit_logs(db_session_factory)[0]
        assert log.action == "admin_idea_file_uploaded"
        assert log.entity_display_id == application_id
        assert log.new_values["file_name"] == "proof.pdf"
        assert "file_path" not in log.new_values
        assert "stored_file_name" not in log.new_values
    finally:
        _clear_overrides()


def test_audit_log_sanitizer_strips_sensitive_fields():
    sanitized = sanitize_audit_values({
        "email": "user@example.com",
        "password": "secret",
        "password_hash": "hash",
        "nested": {
            "reset_token": "token",
            "file_path": "/srv/uploads/a.pdf",
            "safe": "value",
        },
    })

    assert sanitized == {"email": "user@example.com", "nested": {"safe": "value"}}


def test_super_admin_can_list_audit_logs_with_filters_and_pagination(client):
    db_session_factory = _session_factory()
    try:
        _, headers = _seed_user(db_session_factory, "super-list-audit@example.com", UserRole.SUPER_ADMIN)
        db = db_session_factory()
        try:
            db.add_all([
                AuditLog(action="alpha", entity_type="user", entity_display_id="A"),
                AuditLog(action="beta", entity_type="idea", entity_display_id="B"),
                AuditLog(action="alpha", entity_type="idea", entity_display_id="C"),
            ])
            db.commit()
        finally:
            db.close()

        response = client.get(
            "/api/v1/admin/audit-logs?action=alpha&entity_type=idea&limit=1&offset=0",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["action"] == "alpha"
        assert data[0]["entity_type"] == "idea"
        assert "user_agent" not in data[0]
    finally:
        _clear_overrides()


def test_non_super_admins_cannot_list_audit_logs(client):
    db_session_factory = _session_factory()
    try:
        _, team_headers = _seed_user(
            db_session_factory,
            "team-audit@example.com",
            UserRole.TEAM_ADMIN_GLOBAL,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        _, jury_headers = _seed_user(db_session_factory, "jury-audit@example.com", UserRole.JURY)
        _, inventor_headers = _seed_user(db_session_factory, "inventor-audit@example.com", UserRole.INVENTOR)

        assert client.get("/api/v1/admin/audit-logs", headers=team_headers).status_code == 403
        assert client.get("/api/v1/admin/audit-logs", headers=jury_headers).status_code == 403
        assert client.get("/api/v1/admin/audit-logs", headers=inventor_headers).status_code == 403
    finally:
        _clear_overrides()


def test_audit_log_model_and_migrations_import_safely():
    assert AuditLog.__tablename__ == "audit_logs"
    columns = {column.name for column in AuditLog.__table__.columns}
    assert {"actor_user_id", "action", "entity_type", "old_values", "new_values", "created_at"} <= columns
    for path in (
        Path("alembic/versions/0017_add_audit_logs.py"),
        Path("alembic/versions/0018_add_operational_indexes.py"),
    ):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
