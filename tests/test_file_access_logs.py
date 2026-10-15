from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.file_access_log import FileAccessLog
from app.models.idea import Idea, IdeaStatus, SourceType
from app.models.idea_file import FileType, IdeaFile
from app.models.user import ProgramTrack, User, UserRole
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
        tables=[User.__table__, Idea.__table__, IdeaFile.__table__, FileAccessLog.__table__],
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


def _seed_idea_file(db_session_factory, tmp_path: Path, *, program_track=ProgramTrack.NATIONAL_INTERNATIONAL):
    db = db_session_factory()
    try:
        idea = Idea(
            application_id="IDEA-2026-FILE01",
            applicant_name="File Applicant",
            email="file-applicant@example.com",
            phone="9999999999",
            program_track=program_track,
            source_type=SourceType.ONLINE_FORM,
            idea_title="File Audit Idea",
            current_status=IdeaStatus.SUBMITTED,
            is_public_tracking_enabled=True,
        )
        db.add(idea)
        db.flush()

        rel_path = Path("ideas") / idea.application_id / "documents" / "proof.pdf"
        abs_path = tmp_path / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(b"%PDF-1.4 file audit")

        file_record = IdeaFile(
            idea_id=idea.id,
            uploaded_by_user_id=None,
            file_type=FileType.DOCUMENT,
            file_name="proof.pdf",
            stored_file_name="proof.pdf",
            file_path=rel_path.as_posix(),
            mime_type="application/pdf",
            file_size=abs_path.stat().st_size,
            description="Proof",
        )
        db.add(file_record)
        db.commit()
        db.refresh(idea)
        db.refresh(file_record)
        return idea.id, idea.application_id, file_record.id
    finally:
        db.close()


def _access_logs(db_session_factory):
    db = db_session_factory()
    try:
        return db.query(FileAccessLog).order_by(FileAccessLog.id.asc()).all()
    finally:
        db.close()


def test_view_file_uses_inline_disposition_and_logs_view(client, monkeypatch, tmp_path):
    db_session_factory = _session_factory()
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    try:
        _, headers = _seed_user(db_session_factory, "super-view-file@example.com", UserRole.SUPER_ADMIN)
        idea_id, application_id, file_id = _seed_idea_file(db_session_factory, tmp_path)

        response = client.get(f"/api/v1/files/{file_id}/view", headers=headers)

        assert response.status_code == 200
        assert response.content == b"%PDF-1.4 file audit"
        assert "inline" in response.headers["content-disposition"].lower()

        logs = _access_logs(db_session_factory)
        assert len(logs) == 1
        assert logs[0].action == "VIEW"
        assert logs[0].file_id == file_id
        assert logs[0].idea_id == idea_id
        assert logs[0].application_id == application_id
        assert logs[0].original_filename == "proof.pdf"
        assert logs[0].user_email == "super-view-file@example.com"
    finally:
        _clear_overrides()


def test_download_file_uses_attachment_disposition_and_logs_download(client, monkeypatch, tmp_path):
    db_session_factory = _session_factory()
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    try:
        _, headers = _seed_user(db_session_factory, "super-download-file@example.com", UserRole.SUPER_ADMIN)
        _, _, file_id = _seed_idea_file(db_session_factory, tmp_path)

        response = client.get(f"/api/v1/files/{file_id}", headers=headers)

        assert response.status_code == 200
        assert response.content == b"%PDF-1.4 file audit"
        assert "attachment" in response.headers["content-disposition"].lower()

        logs = _access_logs(db_session_factory)
        assert len(logs) == 1
        assert logs[0].action == "DOWNLOAD"
        assert logs[0].original_filename == "proof.pdf"
    finally:
        _clear_overrides()


def test_unauthorized_file_access_does_not_log_successful_activity(client, monkeypatch, tmp_path):
    db_session_factory = _session_factory()
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    try:
        _, headers = _seed_user(
            db_session_factory,
            "local-denied-file@example.com",
            UserRole.TEAM_ADMIN_LOCAL,
            ProgramTrack.LOCAL_REGIONAL,
        )
        _, _, file_id = _seed_idea_file(
            db_session_factory,
            tmp_path,
            program_track=ProgramTrack.NATIONAL_INTERNATIONAL,
        )

        response = client.get(f"/api/v1/files/{file_id}", headers=headers)

        assert response.status_code == 403
        assert _access_logs(db_session_factory) == []
    finally:
        _clear_overrides()


def test_scoped_admin_can_see_activity_for_scoped_idea(client, monkeypatch, tmp_path):
    db_session_factory = _session_factory()
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    try:
        _, headers = _seed_user(
            db_session_factory,
            "global-file-activity@example.com",
            UserRole.TEAM_ADMIN_GLOBAL,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        idea_id, _, file_id = _seed_idea_file(db_session_factory, tmp_path)

        assert client.get(f"/api/v1/files/{file_id}/view", headers=headers).status_code == 200
        response = client.get(f"/api/v1/admin/ideas/{idea_id}/file-activity", headers=headers)

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["action"] == "VIEW"
        assert body[0]["original_filename"] == "proof.pdf"
        assert "user_agent" not in body[0]
    finally:
        _clear_overrides()


def test_out_of_scope_admin_cannot_see_file_activity(client, monkeypatch, tmp_path):
    db_session_factory = _session_factory()
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    try:
        _, super_headers = _seed_user(db_session_factory, "super-activity-seed@example.com", UserRole.SUPER_ADMIN)
        _, local_headers = _seed_user(
            db_session_factory,
            "local-file-activity@example.com",
            UserRole.TEAM_ADMIN_LOCAL,
            ProgramTrack.LOCAL_REGIONAL,
        )
        idea_id, _, file_id = _seed_idea_file(
            db_session_factory,
            tmp_path,
            program_track=ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        assert client.get(f"/api/v1/files/{file_id}", headers=super_headers).status_code == 200

        response = client.get(f"/api/v1/admin/ideas/{idea_id}/file-activity", headers=local_headers)

        assert response.status_code == 403
    finally:
        _clear_overrides()


def test_file_access_log_model_and_migration_import_safely():
    assert FileAccessLog.__tablename__ == "file_access_logs"
    columns = {column.name for column in FileAccessLog.__table__.columns}
    assert {
        "file_id", "idea_id", "application_id", "user_id", "user_email",
        "user_role", "action", "original_filename", "ip_address", "created_at",
    } <= columns
