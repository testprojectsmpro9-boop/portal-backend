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
from app.models.user import ProgramTrack, User, UserRole
from app.utils.security import create_access_token


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            Idea.__table__,
            IntakeSubmission.__table__,
            IdeaFile.__table__,
            IntakeFile.__table__,
            AuditLog.__table__,
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
            full_name=email.split("@")[0],
            email=email,
            password_hash="not-used",
            role=role,
            program_track=program_track,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token({"user_id": user.id, "email": user.email, "role": user.role.value})
        return {"Authorization": f"Bearer {token}"}, user.id
    finally:
        db.close()


def _intake_payload(**overrides):
    data = {
        "source_type": "OFFLINE_FORM",
        "source_program": "NMF_NATIONAL",
        "applicant_type": "INDIVIDUAL",
        "applicant_name": "Intake Applicant",
        "phone": "9999999999",
        "email": "intake-applicant@example.com",
        "age": 24,
        "location": "Mysuru",
        "raw_title": "Intake File Idea",
        "raw_description": "Offline file-backed idea",
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


def _create_intake(client, headers, **overrides):
    response = client.post("/api/v1/admin/intake", json=_intake_payload(**overrides), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _mark_complete(client, headers, intake_id):
    response = client.post(f"/api/v1/admin/intake/{intake_id}/mark-complete", headers=headers)
    assert response.status_code == 200, response.text


def test_admin_can_upload_list_and_download_intake_file(client, monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.file_service.settings.UPLOAD_DIR", str(tmp_path))
    db_session_factory = _session_factory()
    try:
        headers, _user_id = _headers_for_role(
            db_session_factory,
            "super-intake-file@example.com",
            UserRole.SUPER_ADMIN,
        )
        intake = _create_intake(client, headers)

        upload = client.post(
            f"/api/v1/admin/intake/{intake['intake_id']}/files",
            headers=headers,
            data={"file_type": "OTHER", "description": "Offline form"},
            files=[("files", ("offline.pdf", b"%PDF-1.4 smoke", "application/pdf"))],
        )
        assert upload.status_code == 201, upload.text
        files = upload.json()
        assert len(files) == 1
        assert files[0]["file_name"] == "offline.pdf"
        assert "file_path" not in files[0]

        listed = client.get(f"/api/v1/admin/intake/{intake['intake_id']}/files", headers=headers)
        assert listed.status_code == 200
        assert listed.json()[0]["file_name"] == "offline.pdf"

        downloaded = client.get(f"/api/v1/admin/intake/files/{files[0]['id']}", headers=headers)
        assert downloaded.status_code == 200
        assert downloaded.content == b"%PDF-1.4 smoke"
    finally:
        _clear_overrides()


def test_intake_file_access_uses_intake_scope(client, monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.file_service.settings.UPLOAD_DIR", str(tmp_path))
    db_session_factory = _session_factory()
    try:
        super_headers, _ = _headers_for_role(
            db_session_factory,
            "super-local-intake-file@example.com",
            UserRole.SUPER_ADMIN,
        )
        global_headers, _ = _headers_for_role(
            db_session_factory,
            "global-intake-file@example.com",
            UserRole.TEAM_ADMIN_GLOBAL,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        intake = _create_intake(
            client,
            super_headers,
            source_program="NMF_LOCAL",
            email="local-intake@example.com",
        )
        upload = client.post(
            f"/api/v1/admin/intake/{intake['intake_id']}/files",
            headers=super_headers,
            data={"file_type": "OTHER"},
            files=[("files", ("local.pdf", b"local", "application/pdf"))],
        )
        file_id = upload.json()[0]["id"]

        assert client.get(
            f"/api/v1/admin/intake/{intake['intake_id']}/files",
            headers=global_headers,
        ).status_code == 403
        assert client.get(f"/api/v1/admin/intake/files/{file_id}", headers=global_headers).status_code == 403
    finally:
        _clear_overrides()


def test_convert_intake_with_files_creates_idea_file_records(client, monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.file_service.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.routers.intake.notify_intake_conversion", lambda *args, **kwargs: None)
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            "super-convert-intake-file@example.com",
            UserRole.SUPER_ADMIN,
        )
        intake = _create_intake(client, headers, email="convert-file@example.com")
        upload = client.post(
            f"/api/v1/admin/intake/{intake['intake_id']}/files",
            headers=headers,
            data={"file_type": "OTHER", "description": "Sketch"},
            files=[("files", ("sketch.png", b"pngdata", "image/png"))],
        )
        assert upload.status_code == 201, upload.text
        _mark_complete(client, headers, intake["intake_id"])

        converted = client.post(
            f"/api/v1/admin/intake/{intake['intake_id']}/convert-to-idea",
            headers=headers,
        )
        assert converted.status_code == 200, converted.text
        idea_id = converted.json()["standardized_idea_id"]

        idea_files = client.get(f"/api/v1/ideas/{idea_id}/files", headers=headers)
        assert idea_files.status_code == 200
        body = idea_files.json()
        assert len(body) == 1
        assert body[0]["file_name"] == "sketch.png"

        detail = client.get(f"/api/v1/admin/ideas/{idea_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["files"][0]["file_name"] == "sketch.png"
    finally:
        _clear_overrides()


def test_old_intake_without_files_still_converts(client, monkeypatch):
    monkeypatch.setattr("app.routers.intake.notify_intake_conversion", lambda *args, **kwargs: None)
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            "super-old-intake-file@example.com",
            UserRole.SUPER_ADMIN,
        )
        intake = _create_intake(client, headers, email="old-intake-file@example.com")
        _mark_complete(client, headers, intake["intake_id"])

        converted = client.post(
            f"/api/v1/admin/intake/{intake['intake_id']}/convert-to-idea",
            headers=headers,
        )
        assert converted.status_code == 200, converted.text
        idea_id = converted.json()["standardized_idea_id"]
        idea_files = client.get(f"/api/v1/ideas/{idea_id}/files", headers=headers)
        assert idea_files.status_code == 200
        assert idea_files.json() == []
    finally:
        _clear_overrides()


def test_intake_file_upload_requires_auth(client):
    response = client.post("/api/v1/admin/intake/INTAKE-2026-NOAUTH/files")
    assert response.status_code == 401


def test_convert_response_includes_created_application_id(client, monkeypatch, tmp_path):
    """convert-to-idea response must include created_application_id so the portal
    can navigate directly to the new idea without a second lookup."""
    monkeypatch.setattr("app.services.file_service.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.routers.intake.notify_intake_conversion", lambda *a, **kw: None)
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            "super-conv-appid@example.com",
            UserRole.SUPER_ADMIN,
        )
        intake = _create_intake(client, headers, email="conv-appid@example.com")
        _mark_complete(client, headers, intake["intake_id"])

        converted = client.post(
            f"/api/v1/admin/intake/{intake['intake_id']}/convert-to-idea",
            headers=headers,
        )
        assert converted.status_code == 200, converted.text
        body = converted.json()
        assert "created_application_id" in body
        assert body["created_application_id"] is not None
        assert body["created_application_id"].startswith("IDEA-")
        assert body["standardized_idea_id"] is not None
    finally:
        _clear_overrides()


def test_converted_idea_files_visible_via_public_files_endpoint(client, monkeypatch, tmp_path):
    """Files uploaded to an intake must appear via GET /api/v1/ideas/{idea_id}/files
    (the portal's FilesTab endpoint) after conversion — not only via the admin detail endpoint."""
    monkeypatch.setattr("app.services.file_service.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.routers.intake.notify_intake_conversion", lambda *a, **kw: None)
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            "super-files-pub@example.com",
            UserRole.SUPER_ADMIN,
        )
        intake = _create_intake(client, headers, email="files-pub@example.com")

        client.post(
            f"/api/v1/admin/intake/{intake['intake_id']}/files",
            headers=headers,
            data={"file_type": "DOCUMENT"},
            files=[("files", ("report.pdf", b"%PDF-1.4", "application/pdf"))],
        )
        _mark_complete(client, headers, intake["intake_id"])

        converted = client.post(
            f"/api/v1/admin/intake/{intake['intake_id']}/convert-to-idea",
            headers=headers,
        )
        assert converted.status_code == 200
        idea_id = converted.json()["standardized_idea_id"]

        # This is the exact endpoint the portal FilesTab calls
        resp = client.get(f"/api/v1/ideas/{idea_id}/files", headers=headers)
        assert resp.status_code == 200
        files = resp.json()
        assert len(files) == 1
        assert files[0]["file_name"] == "report.pdf"
        assert "file_path" not in files[0]
        assert files[0]["download_url"].startswith("/api/v1/files/")
    finally:
        _clear_overrides()


def test_multiple_intake_files_all_converted_to_idea_files(client, monkeypatch, tmp_path):
    """All files attached to an intake must be bridged to the idea on conversion."""
    monkeypatch.setattr("app.services.file_service.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.routers.intake.notify_intake_conversion", lambda *a, **kw: None)
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            "super-multi-file@example.com",
            UserRole.SUPER_ADMIN,
        )
        intake = _create_intake(client, headers, email="multi-file@example.com")

        # Upload two files in one call
        client.post(
            f"/api/v1/admin/intake/{intake['intake_id']}/files",
            headers=headers,
            data={"file_type": "OTHER"},
            files=[
                ("files", ("sketch.png", b"pngdata", "image/png")),
                ("files", ("notes.pdf", b"%PDF-1.4", "application/pdf")),
            ],
        )
        _mark_complete(client, headers, intake["intake_id"])

        converted = client.post(
            f"/api/v1/admin/intake/{intake['intake_id']}/convert-to-idea",
            headers=headers,
        )
        assert converted.status_code == 200
        idea_id = converted.json()["standardized_idea_id"]

        resp = client.get(f"/api/v1/ideas/{idea_id}/files", headers=headers)
        assert resp.status_code == 200
        names = {f["file_name"] for f in resp.json()}
        assert names == {"sketch.png", "notes.pdf"}
    finally:
        _clear_overrides()


def test_conversion_is_idempotent_on_files(client, monkeypatch, tmp_path):
    """If conversion is attempted a second time (blocked by guard), no duplicate
    IdeaFile records are created. This guards the de-dup logic in the bridge."""
    monkeypatch.setattr("app.services.file_service.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.routers.intake.notify_intake_conversion", lambda *a, **kw: None)
    db_session_factory = _session_factory()
    try:
        from fastapi.testclient import TestClient
        from app.models.idea_file import IdeaFile as IdeaFileModel
        headers, _ = _headers_for_role(
            db_session_factory,
            "super-idem-file@example.com",
            UserRole.SUPER_ADMIN,
        )
        intake = _create_intake(client, headers, email="idem-file@example.com")
        client.post(
            f"/api/v1/admin/intake/{intake['intake_id']}/files",
            headers=headers,
            data={"file_type": "OTHER"},
            files=[("files", ("only.pdf", b"pdfdata", "application/pdf"))],
        )
        _mark_complete(client, headers, intake["intake_id"])

        # First conversion succeeds
        r1 = client.post(
            f"/api/v1/admin/intake/{intake['intake_id']}/convert-to-idea",
            headers=headers,
        )
        assert r1.status_code == 200
        idea_id = r1.json()["standardized_idea_id"]

        # Second conversion blocked by guard
        r2 = client.post(
            f"/api/v1/admin/intake/{intake['intake_id']}/convert-to-idea",
            headers=headers,
        )
        assert r2.status_code == 400
        assert "already converted" in r2.json()["detail"].lower()

        # Still only one IdeaFile record
        resp = client.get(f"/api/v1/ideas/{idea_id}/files", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 1
    finally:
        _clear_overrides()
