"""
Phase 11 — jury access to admin/intake-uploaded attachments (e.g. a scanned
PDF captured at intake, then converted to an idea).

Confirms the full real-world chain: admin uploads a scanned document during
intake -> intake is converted to an idea -> the file is correctly linked to
the resulting idea -> an assigned jury member can list and download it via
the jury router -> an unassigned or cancelled/reassigned jury member cannot.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.file_access_log import FileAccessLog
from app.models.idea import Idea
from app.models.idea_file import IdeaFile
from app.models.intake import IntakeSubmission
from app.models.intake_file import IntakeFile
from app.models.jury import JuryAssignment, ReviewStatus
from app.models.user import ProgramTrack, User, UserRole
from app.utils.security import create_access_token


def _session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__, Idea.__table__, IntakeSubmission.__table__,
            IdeaFile.__table__, IntakeFile.__table__, JuryAssignment.__table__,
            AuditLog.__table__, FileAccessLog.__table__,
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


def _intake_payload(**overrides):
    data = {
        "source_type": "OFFLINE_FORM",
        "source_program": "NMF_NATIONAL",
        "applicant_type": "INDIVIDUAL",
        "applicant_name": "Scan Applicant",
        "phone": "9999999999",
        "email": "scan-applicant@example.com",
        "location": "Mysuru",
        "raw_title": "Scanned Idea",
        "problem_statement": "Problem",
        "solution_description": "Solution",
        "consent_data": True,
        "consent_original": True,
        "consent_contact": True,
    }
    data.update(overrides)
    return data


def _build_scanned_idea(client, monkeypatch, tmp_path, admin_headers):
    monkeypatch.setattr("app.services.file_service.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("app.routers.intake.notify_intake_conversion", lambda *a, **k: None)

    intake = client.post("/api/v1/admin/intake", json=_intake_payload(), headers=admin_headers)
    assert intake.status_code == 201, intake.text
    intake_id = intake.json()["intake_id"]

    upload = client.post(
        f"/api/v1/admin/intake/{intake_id}/files",
        headers=admin_headers,
        data={"file_type": "LETTER_SCAN", "description": "Scanned application form"},
        files=[("files", ("application_scan.pdf", b"%PDF-1.4 scanned content", "application/pdf"))],
    )
    assert upload.status_code == 201, upload.text

    complete = client.post(f"/api/v1/admin/intake/{intake_id}/mark-complete", headers=admin_headers)
    assert complete.status_code == 200, complete.text

    converted = client.post(f"/api/v1/admin/intake/{intake_id}/convert-to-idea", headers=admin_headers)
    assert converted.status_code == 200, converted.text
    return converted.json()["standardized_idea_id"]


def test_assigned_jury_can_see_and_download_admin_uploaded_scan(client, monkeypatch, tmp_path):
    db_session_factory = _session_factory()
    try:
        admin_headers, admin_id = _headers_for_role(db_session_factory, "admin-scan@example.com", UserRole.SUPER_ADMIN)
        idea_id = _build_scanned_idea(client, monkeypatch, tmp_path, admin_headers)

        jury_headers, jury_id = _headers_for_role(db_session_factory, "juror-scan@example.com", UserRole.JURY)
        db = db_session_factory()
        try:
            db.add(JuryAssignment(
                idea_id=idea_id, jury_user_id=jury_id, assigned_by_user_id=admin_id,
                review_status=ReviewStatus.PENDING,
            ))
            db.commit()
        finally:
            db.close()

        listing = client.get(f"/api/v1/jury/ideas/{idea_id}/files", headers=jury_headers)
        assert listing.status_code == 200, listing.text
        files = listing.json()
        assert len(files) == 1
        assert files[0]["file_name"] == "application_scan.pdf"

        download = client.get(f"/api/v1/files/{files[0]['id']}", headers=jury_headers)
        assert download.status_code == 200
        assert download.content == b"%PDF-1.4 scanned content"
    finally:
        _clear_overrides()


def test_unassigned_jury_cannot_see_the_scan(client, monkeypatch, tmp_path):
    db_session_factory = _session_factory()
    try:
        admin_headers, admin_id = _headers_for_role(db_session_factory, "admin-scan2@example.com", UserRole.SUPER_ADMIN)
        idea_id = _build_scanned_idea(client, monkeypatch, tmp_path, admin_headers)

        jury_headers, _jury_id = _headers_for_role(db_session_factory, "unassigned-juror@example.com", UserRole.JURY)

        listing = client.get(f"/api/v1/jury/ideas/{idea_id}/files", headers=jury_headers)
        assert listing.status_code == 403
    finally:
        _clear_overrides()


def test_cancelled_or_reassigned_jury_loses_access_to_the_scan(client, monkeypatch, tmp_path):
    db_session_factory = _session_factory()
    try:
        admin_headers, admin_id = _headers_for_role(db_session_factory, "admin-scan3@example.com", UserRole.SUPER_ADMIN)
        idea_id = _build_scanned_idea(client, monkeypatch, tmp_path, admin_headers)

        for status_value, label in ((ReviewStatus.CANCELLED, "cancelled"), (ReviewStatus.REASSIGNED, "reassigned")):
            jury_headers, jury_id = _headers_for_role(
                db_session_factory, f"{label}-juror@example.com", UserRole.JURY,
            )
            db = db_session_factory()
            try:
                db.add(JuryAssignment(
                    idea_id=idea_id, jury_user_id=jury_id, assigned_by_user_id=admin_id,
                    review_status=status_value,
                ))
                db.commit()
            finally:
                db.close()

            listing = client.get(f"/api/v1/jury/ideas/{idea_id}/files", headers=jury_headers)
            assert listing.status_code == 403, label
    finally:
        _clear_overrides()


def test_view_admin_can_also_see_the_scan_via_admin_detail(client, monkeypatch, tmp_path):
    """Phase 6/11: View Admin's read-only dashboard must include attachments
    for ideas within scope, same as full admin."""
    db_session_factory = _session_factory()
    try:
        admin_headers, admin_id = _headers_for_role(db_session_factory, "admin-scan4@example.com", UserRole.SUPER_ADMIN)
        idea_id = _build_scanned_idea(client, monkeypatch, tmp_path, admin_headers)

        view_headers, _view_id = _headers_for_role(db_session_factory, "view-scan@example.com", UserRole.VIEW_ADMIN_BOTH)

        detail = client.get(f"/api/v1/admin/ideas/{idea_id}", headers=view_headers)
        assert detail.status_code == 200
        assert detail.json()["files"][0]["file_name"] == "application_scan.pdf"

        download = client.get(f"/api/v1/files/{detail.json()['files'][0]['id']}", headers=view_headers)
        assert download.status_code == 200
    finally:
        _clear_overrides()
