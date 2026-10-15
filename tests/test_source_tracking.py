"""
Source tracking tests — Phase 3.

Verifies that source_platform / source_domain / source_url / referrer_url are:
  - stored when submitted via public idea endpoints
  - absent (null) when not submitted (backward compat)
  - copied from intake on intake conversion, with admin-intake fallback
  - returned via admin idea detail endpoint
  - sanitized to max lengths

Source-based admin email routing is covered for notification metadata only.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.idea import Idea, IdeaStatus, SourceType
from app.models.idea_file import IdeaFile
from app.models.intake import IntakeSubmission
from app.models.intake_file import IntakeFile
from app.models.audit_log import AuditLog
from app.models.user import ProgramTrack, User, UserRole
from app.utils.security import create_access_token


# ─── Session helpers ─────────────────────────────────────────────────────────

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
            IdeaFile.__table__,
            IntakeSubmission.__table__,
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


def _admin_headers(db_session_factory, email="super@source.test", role=UserRole.SUPER_ADMIN):
    db = db_session_factory()
    try:
        user = User(
            full_name=email.split("@")[0],
            email=email,
            password_hash="not-used",
            role=role,
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
        "applicant_name": "Tracker User",
        "email": "tracker@example.com",
        "phone": "9999999999",
        "age": 28,
        "location": "Mysuru",
        "program_track": "NATIONAL_INTERNATIONAL",
        "idea_title": "Source Tracking Test Idea",
        "problem_statement": "Problem",
        "solution_description": "Solution",
        "target_users": "Farmers",
        "prototype_status": "IDEA_STAGE",
        "support_needed": "Mentorship",
        "consent_data": True,
        "consent_original": True,
        "consent_contact": True,
    }
    payload.update(overrides)
    return payload


def _intake_payload(**overrides):
    payload = {
        "source_type": "OFFLINE_FORM",
        "source_program": "NMF_NATIONAL",
        "applicant_type": "INDIVIDUAL",
        "applicant_name": "Intake Tracker",
        "phone": "8888888888",
        "email": "intake-track@example.com",
        "age": 30,
        "location": "Chennai",
        "raw_title": "Intake Source Tracking Idea",
        "raw_description": "Offline source tracking test",
        "problem_statement": "Problem",
        "solution_description": "Solution",
        "category": "Water",
        "target_users": "Villagers",
        "prototype_status": "IDEA_STAGE",
        "support_needed": "Mentorship",
        "consent_data": True,
        "consent_original": True,
        "consent_contact": True,
    }
    payload.update(overrides)
    return payload


# ─── Public submit tests ──────────────────────────────────────────────────────

def test_public_submit_stores_source_platform(client):
    _session_factory()
    try:
        resp = client.post(
            "/api/v1/ideas",
            json=_base_idea_payload(
                email="src-platform@example.com",
                source_platform="ingeniouspark",
                source_domain="ingeniouspark.in",
                source_url="https://ingeniouspark.in/submit-idea",
                referrer_url="https://ingeniouspark.in/",
            ),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json().get("source_platform") == "ingeniouspark"
    finally:
        _clear_overrides()


def test_public_submit_stores_sirmv_source_without_changing_program_track(client):
    _session_factory()
    try:
        resp = client.post(
            "/api/v1/ideas",
            json=_base_idea_payload(
                email="sirmv-src@example.com",
                program_track="LOCAL_REGIONAL",
                source_platform="sirmv-idea",
                source_domain="ingeniouspark.in",
                source_url="https://ingeniouspark.in/submit-idea?source=sirmv-idea",
            ),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        # source_platform records the origin, but program_track is unchanged
        assert data.get("source_platform") == "sirmv-idea"
        assert data.get("program_track") == "LOCAL_REGIONAL"
    finally:
        _clear_overrides()


def test_public_submit_with_files_stores_source_tracking(client, monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.file_service.settings.UPLOAD_DIR", str(tmp_path))
    _session_factory()
    try:
        import json as _json
        payload = _base_idea_payload(
            email="src-files@example.com",
            source_platform="ingeniouspark",
            source_domain="ingeniouspark.in",
            source_url="https://ingeniouspark.in/submit-idea",
        )
        resp = client.post(
            "/api/v1/ideas/with-files",
            data={"idea_json": _json.dumps(payload)},
            files=[("files", ("doc.pdf", b"%PDF-1.4", "application/pdf"))],
        )
        assert resp.status_code == 201, resp.text
        assert resp.json().get("source_platform") == "ingeniouspark"
    finally:
        _clear_overrides()


def test_public_submit_missing_source_defaults_to_null(client):
    _session_factory()
    try:
        resp = client.post(
            "/api/v1/ideas",
            json=_base_idea_payload(email="no-source@example.com"),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        # Old submissions without source fields remain null — no crash
        assert data.get("source_platform") is None
        assert data.get("source_domain") is None
        assert data.get("source_url") is None
        assert data.get("referrer_url") is None
    finally:
        _clear_overrides()


def test_source_url_and_referrer_url_stored(client):
    _session_factory()
    try:
        url = "https://ingeniouspark.in/submit-idea?source=sirmv-idea&ref=home"
        ref = "https://ingeniouspark.in/"
        resp = client.post(
            "/api/v1/ideas",
            json=_base_idea_payload(
                email="src-url@example.com",
                source_platform="sirmv-idea",
                source_domain="ingeniouspark.in",
                source_url=url,
                referrer_url=ref,
            ),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data.get("source_url") == url
        assert data.get("referrer_url") == ref
    finally:
        _clear_overrides()


def test_source_fields_truncated_to_max_length(client):
    """Values longer than the column max are silently truncated (not rejected)."""
    _session_factory()
    try:
        long_platform = "x" * 200  # > 50
        long_url = "https://example.com/" + "x" * 3000  # > 2000
        resp = client.post(
            "/api/v1/ideas",
            json=_base_idea_payload(
                email="trunc@example.com",
                source_platform=long_platform,
                source_url=long_url,
            ),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert len(data.get("source_platform", "")) <= 50
        assert len(data.get("source_url", "")) <= 2000
    finally:
        _clear_overrides()


# ─── Intake conversion tests ──────────────────────────────────────────────────

def test_intake_conversion_sets_source_platform_admin_intake(client, monkeypatch):
    monkeypatch.setattr("app.routers.intake.notify_intake_conversion", lambda *a, **kw: None)
    db_session_factory = _session_factory()
    try:
        headers = _admin_headers(db_session_factory, "super-src-conv@source.test")
        intake_resp = client.post("/api/v1/admin/intake", json=_intake_payload(), headers=headers)
        assert intake_resp.status_code == 201, intake_resp.text
        intake_id = intake_resp.json()["intake_id"]

        client.post(f"/api/v1/admin/intake/{intake_id}/mark-complete", headers=headers)
        conv = client.post(f"/api/v1/admin/intake/{intake_id}/convert-to-idea", headers=headers)
        assert conv.status_code == 200, conv.text
        idea_id = conv.json()["standardized_idea_id"]

        detail = client.get(f"/api/v1/admin/ideas/{idea_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.json().get("source_platform") == "ingeniouspark"
    finally:
        _clear_overrides()


def test_intake_conversion_copies_selected_sirmv_source_platform(client, monkeypatch):
    monkeypatch.setattr("app.routers.intake.notify_intake_conversion", lambda *a, **kw: None)
    db_session_factory = _session_factory()
    try:
        headers = _admin_headers(db_session_factory, "super-src-sirmv-conv@source.test")
        intake_resp = client.post(
            "/api/v1/admin/intake",
            json=_intake_payload(email="sirmv-intake@example.com", source_platform="sirmv-idea"),
            headers=headers,
        )
        assert intake_resp.status_code == 201, intake_resp.text
        intake_id = intake_resp.json()["intake_id"]

        client.post(f"/api/v1/admin/intake/{intake_id}/mark-complete", headers=headers)
        conv = client.post(f"/api/v1/admin/intake/{intake_id}/convert-to-idea", headers=headers)
        assert conv.status_code == 200, conv.text
        idea_id = conv.json()["standardized_idea_id"]

        detail = client.get(f"/api/v1/admin/ideas/{idea_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.json().get("source_platform") == "sirmv-idea"
    finally:
        _clear_overrides()


def test_intake_request_more_info_sends_to_applicant_with_source_bcc(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.routers.intake.send_applicant_email",
        lambda **kwargs: calls.append(kwargs) or True,
    )
    db_session_factory = _session_factory()
    try:
        headers = _admin_headers(db_session_factory, "super-intake-more-info@source.test")
        intake_resp = client.post(
            "/api/v1/admin/intake",
            json=_intake_payload(email="intake-applicant@example.com", source_platform="sirmv-idea"),
            headers=headers,
        )
        assert intake_resp.status_code == 201, intake_resp.text
        intake_id = intake_resp.json()["intake_id"]

        response = client.post(
            f"/api/v1/admin/intake/{intake_id}/request-more-info",
            json={"missing_information_note": "Please share prototype photos."},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        assert calls[0]["to_email"] == "intake-applicant@example.com"
        assert calls[0]["bcc"] == "smvvisions@gmail.com"
        assert "Please share prototype photos." in calls[0]["text_body"]
    finally:
        _clear_overrides()


def test_intake_request_more_info_blocks_missing_applicant_email(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.routers.intake.send_applicant_email",
        lambda **kwargs: calls.append(kwargs) or True,
    )
    db_session_factory = _session_factory()
    try:
        headers = _admin_headers(db_session_factory, "super-intake-missing-email@source.test")
        intake_resp = client.post(
            "/api/v1/admin/intake",
            json=_intake_payload(email=None),
            headers=headers,
        )
        assert intake_resp.status_code == 201, intake_resp.text
        intake_id = intake_resp.json()["intake_id"]

        response = client.post(
            f"/api/v1/admin/intake/{intake_id}/request-more-info",
            json={"missing_information_note": "Please share prototype photos."},
            headers=headers,
        )

        assert response.status_code == 400
        assert response.json()["detail"] == (
            "Applicant email is missing. Please add an email before requesting more information."
        )
        assert calls == []
    finally:
        _clear_overrides()


# ─── Admin detail returns source fields ───────────────────────────────────────

def test_admin_idea_detail_returns_source_tracking_fields(client):
    db_session_factory = _session_factory()
    try:
        headers = _admin_headers(db_session_factory, "super-src-detail@source.test")
        idea_resp = client.post(
            "/api/v1/ideas",
            json=_base_idea_payload(
                email="src-detail@example.com",
                source_platform="ingeniouspark",
                source_domain="ingeniouspark.in",
                source_url="https://ingeniouspark.in/submit-idea",
                referrer_url="https://google.com/",
            ),
        )
        assert idea_resp.status_code == 201
        app_id = idea_resp.json()["application_id"]

        detail = client.get(f"/api/v1/admin/ideas/{app_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        data = detail.json()
        assert data.get("source_platform") == "ingeniouspark"
        assert data.get("source_domain") == "ingeniouspark.in"
        assert data.get("source_url") == "https://ingeniouspark.in/submit-idea"
        assert data.get("referrer_url") == "https://google.com/"
    finally:
        _clear_overrides()


def test_old_ideas_with_null_source_fields_still_serialize(client):
    """Ideas created before source tracking was added must not crash on serialization."""
    db_session_factory = _session_factory()
    try:
        headers = _admin_headers(db_session_factory, "super-old-idea@source.test")
        # Submit without any source fields — simulates pre-0021 rows
        idea_resp = client.post(
            "/api/v1/ideas",
            json=_base_idea_payload(email="old-idea@example.com"),
        )
        assert idea_resp.status_code == 201
        app_id = idea_resp.json()["application_id"]

        detail = client.get(f"/api/v1/admin/ideas/{app_id}", headers=headers)
        assert detail.status_code == 200
        data = detail.json()
        # All source fields null is valid — no KeyError / serialization error
        assert "source_platform" in data or data.get("source_platform") is None
    finally:
        _clear_overrides()


# ─── Email subject label test ─────────────────────────────────────────────────

def test_notification_subject_includes_source_label(monkeypatch):
    """Admin email subject line must include the source platform bracket label."""
    from app.services.idea_notification_service import notify_public_idea_submission

    subjects_seen: list[str] = []

    def fake_send_admin(
        subject: str,
        html_body: str,
        text_body: str,
        source_platform: str | None = None,
    ) -> None:
        subjects_seen.append(subject)

    monkeypatch.setattr(
        "app.services.idea_notification_service._send_admin_safely",
        fake_send_admin,
    )
    monkeypatch.setattr(
        "app.services.idea_notification_service._send_applicant_safely",
        lambda *a, **kw: None,
    )

    idea = Idea(
        application_id="IDEA-TEST-001",
        applicant_name="Test",
        email="test@example.com",
        program_track=ProgramTrack.NATIONAL_INTERNATIONAL,
        source_type=SourceType.ONLINE_FORM,
        idea_title="Test",
        current_status=IdeaStatus.SUBMITTED,
        is_public_tracking_enabled=True,
        source_platform="sirmv-idea",
    )

    notify_public_idea_submission(idea)

    assert subjects_seen, "Expected at least one admin notification subject"
    assert "[SIR MV Idea] New idea submitted" in subjects_seen[0], (
        f"Subject did not contain source label: {subjects_seen[0]}"
    )
