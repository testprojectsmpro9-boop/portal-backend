import re
from datetime import datetime
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.idea import Idea
from app.models.idea_file import IdeaFile
from app.models.intake import CompletenessStatus, IntakeStatus, IntakeSubmission
from app.models.intake_file import IntakeFile
from app.models.user import User, UserRole
from app.services.idea_notification_service import notify_public_idea_submission
from app.utils.security import create_access_token


ID_RE = re.compile(r"^IDEA-\d{4}-[A-Z0-9]{6}$")
INTAKE_RE = re.compile(r"^INTAKE-\d{4}-[A-Z0-9]{6}$")


def _client_with_db(client):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(
        bind=engine,
        tables=[User.__table__, Idea.__table__, IntakeSubmission.__table__, IdeaFile.__table__, IntakeFile.__table__],
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


def _admin_headers(db_session_factory):
    db = db_session_factory()
    try:
        admin = User(
            full_name="Admin User",
            email="admin-idea@example.com",
            password_hash="not-used",
            role=UserRole.SUPER_ADMIN,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        token = create_access_token({"user_id": admin.id, "email": admin.email, "role": admin.role.value})
        return {"Authorization": f"Bearer {token}"}
    finally:
        db.close()


def _idea_payload(**overrides):
    data = {
        "applicant_name": "Public Applicant",
        "email": "public@example.com",
        "phone": "9876543210",
        "age": 21,
        "location": "Pune",
        "organization": "Example College",
        "program_track": "NATIONAL_INTERNATIONAL",
        "source_type": "ONLINE_FORM",
        "idea_title": "Smart Water Meter",
        "problem_statement": "Water use is hard to monitor.",
        "solution_description": "A simple low-cost meter.",
        "category": "Water",
        "sub_category": "Monitoring",
        "prototype_status": "Concept",
        "support_needed": "Mentoring",
        "source_program": "NATIONAL_INTERNATIONAL",
        "applicant_type": "COLLEGE_STUDENT",
    }
    data.update(overrides)
    return data


def _intake_payload(**overrides):
    data = {
        "source_type": "OFFLINE_FORM",
        "source_program": "NMF_LOCAL",
        "applicant_type": "INDIVIDUAL",
        "visibility_scope": "LOCAL_ONLY",
        "applicant_name": "New Intake Applicant",
        "phone": "8888888888",
        "email": "new-intake@example.com",
        "age": 29,
        "location": "Nashik",
        "organization": "New Intake Org",
        "raw_title": "New Intake Idea",
        "raw_description": "Problem: A local issue\n\nSolution: A practical fix",
    }
    data.update(overrides)
    return data


def _create_ready_intake(db_session_factory, email="offline@example.com"):
    db = db_session_factory()
    try:
        admin = User(
            full_name="Intake Admin",
            email=f"intake-admin-{datetime.utcnow().timestamp()}@example.com",
            password_hash="not-used",
            role=UserRole.SUPER_ADMIN,
            is_active=True,
        )
        db.add(admin)
        db.flush()
        intake = IntakeSubmission(
            intake_id="INTAKE-0001",
            created_by_user_id=admin.id,
            source_type="OFFLINE_FORM",
            source_program="NMF_LOCAL",
            applicant_type="INDIVIDUAL",
            visibility_scope="LOCAL_ONLY",
            applicant_name="Offline Applicant",
            phone="9999999999",
            email=email,
            age=35,
            location="Nagpur",
            organization="Offline Org",
            raw_title="Offline Solar Dryer",
            problem_statement="Farmers need low-cost drying.",
            solution_description="A solar drying cabinet.",
            category="Agriculture",
            sub_category="Post harvest",
            target_users="Farmers",
            prototype_status="Prototype ready",
            support_needed="Field testing",
            intake_status=IntakeStatus.READY_FOR_REVIEW,
            completeness_status=CompletenessStatus.COMPLETE,
        )
        db.add(intake)
        db.commit()
        return intake.intake_id
    finally:
        db.close()


def _create_idea(db_session_factory):
    db = db_session_factory()
    try:
        idea = Idea(
            application_id="IDEA-9999",
            applicant_name="Converted Applicant",
            email="converted@example.com",
            program_track="LOCAL_REGIONAL",
            source_type="OFFLINE_FORM",
            source_program="LOCAL_REGIONAL",
            applicant_type="ADULT_INNOVATOR",
            idea_title="Converted Idea",
            solution_description="Converted solution",
            current_status="SUBMITTED",
            is_public_tracking_enabled=True,
        )
        db.add(idea)
        db.commit()
        db.refresh(idea)
        return idea.id
    finally:
        db.close()


def test_public_idea_submission_succeeds_if_admin_email_succeeds(client, monkeypatch):
    _client_with_db(client)
    calls = []

    monkeypatch.setattr(
        "app.services.idea_notification_service.send_admin_notification",
        lambda **kwargs: calls.append(("admin", kwargs)) or True,
    )
    monkeypatch.setattr(
        "app.services.idea_notification_service.send_applicant_email",
        lambda **kwargs: calls.append(("applicant", kwargs)) or True,
    )

    try:
        response = client.post("/api/v1/ideas", json=_idea_payload())
        assert response.status_code == 201
        application_id = response.json()["application_id"]
        assert ID_RE.match(application_id)
        assert calls[0][0] == "admin"
        assert calls[0][1]["subject"] == f"New idea submitted - {application_id}"
    finally:
        _clear_overrides()


def test_public_individual_idea_submission_allows_empty_team_fields(client, monkeypatch):
    _client_with_db(client)
    monkeypatch.setattr("app.services.idea_notification_service.send_admin_notification", lambda **kwargs: True)
    monkeypatch.setattr("app.services.idea_notification_service.send_applicant_email", lambda **kwargs: True)

    try:
        response = client.post("/api/v1/ideas", json=_idea_payload())
        assert response.status_code == 201
        body = response.json()
        assert body["team_name"] is None
        assert body["team_member_count"] is None
        assert body["team_member_names"] is None
    finally:
        _clear_overrides()


def test_public_team_idea_submission_persists_team_fields(client, monkeypatch):
    db_session_factory = _client_with_db(client)
    monkeypatch.setattr("app.services.idea_notification_service.send_admin_notification", lambda **kwargs: True)
    monkeypatch.setattr("app.services.idea_notification_service.send_applicant_email", lambda **kwargs: True)

    payload = _idea_payload(
        team_name="Water Watchers",
        team_member_count=3,
        team_member_names=["Asha Lead", "Ravi Member", "Neha Member"],
    )

    try:
        response = client.post("/api/v1/ideas", json=payload)
        assert response.status_code == 201
        body = response.json()
        assert body["team_name"] == "Water Watchers"
        assert body["team_member_count"] == 3
        assert body["team_member_names"] == ["Asha Lead", "Ravi Member", "Neha Member"]

        db = db_session_factory()
        try:
            idea = db.query(Idea).filter(Idea.application_id == body["application_id"]).one()
            assert idea.team_name == "Water Watchers"
            assert idea.team_member_count == 3
            assert idea.team_member_names == ["Asha Lead", "Ravi Member", "Neha Member"]
        finally:
            db.close()
    finally:
        _clear_overrides()


def test_public_team_idea_submission_rejects_invalid_team_count(client, monkeypatch):
    _client_with_db(client)
    monkeypatch.setattr("app.services.idea_notification_service.send_admin_notification", lambda **kwargs: True)
    monkeypatch.setattr("app.services.idea_notification_service.send_applicant_email", lambda **kwargs: True)

    try:
        response = client.post(
            "/api/v1/ideas",
            json=_idea_payload(
                team_name="Too Small",
                team_member_count=1,
                team_member_names=["Solo Lead"],
            ),
        )
        assert response.status_code == 422
    finally:
        _clear_overrides()


def test_public_team_idea_submission_rejects_member_name_count_mismatch(client, monkeypatch):
    _client_with_db(client)
    monkeypatch.setattr("app.services.idea_notification_service.send_admin_notification", lambda **kwargs: True)
    monkeypatch.setattr("app.services.idea_notification_service.send_applicant_email", lambda **kwargs: True)

    try:
        response = client.post(
            "/api/v1/ideas",
            json=_idea_payload(
                team_name="Missing Member",
                team_member_count=3,
                team_member_names=["Lead", "Second"],
            ),
        )
        assert response.status_code == 422
    finally:
        _clear_overrides()


def test_public_idea_submission_succeeds_if_admin_email_fails(client, monkeypatch):
    _client_with_db(client)

    def fail_admin(**kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr("app.services.idea_notification_service.send_admin_notification", fail_admin)
    monkeypatch.setattr("app.services.idea_notification_service.send_applicant_email", lambda **kwargs: True)

    try:
        response = client.post("/api/v1/ideas", json=_idea_payload())
        assert response.status_code == 201
        assert ID_RE.match(response.json()["application_id"])
    finally:
        _clear_overrides()


def test_public_idea_submission_sends_applicant_email_if_email_exists(client, monkeypatch):
    _client_with_db(client)
    applicant_calls = []

    monkeypatch.setattr("app.services.idea_notification_service.send_admin_notification", lambda **kwargs: True)
    monkeypatch.setattr(
        "app.services.idea_notification_service.send_applicant_email",
        lambda **kwargs: applicant_calls.append(kwargs) or True,
    )

    try:
        response = client.post("/api/v1/ideas", json=_idea_payload())
        assert response.status_code == 201
        application_id = response.json()["application_id"]
        assert ID_RE.match(application_id)
        assert applicant_calls[0]["to_email"] == "public@example.com"
        assert applicant_calls[0]["subject"] == f"Your idea has been submitted - {application_id}"
    finally:
        _clear_overrides()


def test_public_idea_admin_notification_passes_source_platform_and_applicant_uses_sirmv_sender(client, monkeypatch):
    _client_with_db(client)
    admin_calls = []
    applicant_calls = []

    monkeypatch.setattr(
        "app.services.idea_notification_service.send_admin_notification",
        lambda **kwargs: admin_calls.append(kwargs) or True,
    )
    monkeypatch.setattr(
        "app.services.idea_notification_service.send_applicant_email",
        lambda **kwargs: applicant_calls.append(kwargs) or True,
    )

    try:
        response = client.post(
            "/api/v1/ideas",
            json=_idea_payload(
                email="sirmv-applicant@example.com",
                source_platform="sirmv-idea",
            ),
        )
        assert response.status_code == 201
        assert admin_calls[0]["source_platform"] == "sirmv-idea"
        assert admin_calls[0]["subject"].startswith("[SIR MV Idea] New idea submitted - IDEA-")
        assert applicant_calls[0]["to_email"] == "sirmv-applicant@example.com"
        assert applicant_calls[0].get("source_platform") == "sirmv-idea"
    finally:
        _clear_overrides()


def test_public_idea_notification_skips_applicant_email_if_no_email(monkeypatch):
    applicant_calls = []
    idea = MagicMock()
    idea.application_id = "IDEA-9999"
    idea.idea_title = "No Email Idea"
    idea.applicant_name = "No Email Applicant"
    idea.email = None
    idea.phone = None
    idea.age = None
    idea.location = None
    idea.organization = None
    idea.applicant_type = None
    idea.program_track = "LOCAL_REGIONAL"
    idea.source_program = "LOCAL_REGIONAL"
    idea.category = None
    idea.sub_category = None
    idea.prototype_status = None
    idea.support_needed = None
    idea.created_at = datetime.utcnow()

    monkeypatch.setattr("app.services.idea_notification_service.send_admin_notification", lambda **kwargs: True)
    monkeypatch.setattr(
        "app.services.idea_notification_service.send_applicant_email",
        lambda **kwargs: applicant_calls.append(kwargs) or True,
    )

    notify_public_idea_submission(idea)
    assert applicant_calls == []


def test_intake_convert_to_idea_succeeds_if_email_succeeds(client, monkeypatch):
    db_session_factory = _client_with_db(client)
    intake_id = _create_ready_intake(db_session_factory)
    headers = _admin_headers(db_session_factory)

    monkeypatch.setattr("app.services.idea_notification_service.send_admin_notification", lambda **kwargs: True)
    monkeypatch.setattr("app.services.idea_notification_service.send_applicant_email", lambda **kwargs: True)

    try:
        response = client.post(f"/api/v1/admin/intake/{intake_id}/convert-to-idea", headers=headers)
        assert response.status_code == 200
        assert response.json()["standardized_idea_id"] == 1
    finally:
        _clear_overrides()


def test_intake_convert_to_idea_succeeds_if_email_fails(client, monkeypatch):
    db_session_factory = _client_with_db(client)
    intake_id = _create_ready_intake(db_session_factory)
    headers = _admin_headers(db_session_factory)

    def fail_email(**kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr("app.services.idea_notification_service.send_admin_notification", fail_email)
    monkeypatch.setattr("app.services.idea_notification_service.send_applicant_email", fail_email)

    try:
        response = client.post(f"/api/v1/admin/intake/{intake_id}/convert-to-idea", headers=headers)
        assert response.status_code == 200
        assert response.json()["intake_status"] == "CONVERTED_TO_IDEA"
    finally:
        _clear_overrides()


def test_intake_convert_to_idea_sends_applicant_email_if_email_exists(client, monkeypatch):
    db_session_factory = _client_with_db(client)
    intake_id = _create_ready_intake(db_session_factory)
    headers = _admin_headers(db_session_factory)
    applicant_calls = []

    monkeypatch.setattr("app.services.idea_notification_service.send_admin_notification", lambda **kwargs: True)
    monkeypatch.setattr(
        "app.services.idea_notification_service.send_applicant_email",
        lambda **kwargs: applicant_calls.append(kwargs) or True,
    )

    try:
        response = client.post(f"/api/v1/admin/intake/{intake_id}/convert-to-idea", headers=headers)
        assert response.status_code == 200
        assert applicant_calls[0]["to_email"] == "offline@example.com"
        subject = applicant_calls[0]["subject"]
        assert subject.startswith("Your offline idea entry has been registered - IDEA-")
    finally:
        _clear_overrides()


def test_intake_conversion_admin_notification_uses_ingeniouspark_source_for_default_intake(client, monkeypatch):
    db_session_factory = _client_with_db(client)
    intake_id = _create_ready_intake(db_session_factory)
    headers = _admin_headers(db_session_factory)
    admin_calls = []
    applicant_calls = []

    monkeypatch.setattr(
        "app.services.idea_notification_service.send_admin_notification",
        lambda **kwargs: admin_calls.append(kwargs) or True,
    )
    monkeypatch.setattr(
        "app.services.idea_notification_service.send_applicant_email",
        lambda **kwargs: applicant_calls.append(kwargs) or True,
    )

    try:
        response = client.post(f"/api/v1/admin/intake/{intake_id}/convert-to-idea", headers=headers)
        assert response.status_code == 200
        # Default intake (no source_platform) converts to "ingeniouspark" — routes to Ingeniouspark admin
        assert admin_calls[0]["source_platform"] == "ingeniouspark"
        assert admin_calls[0]["subject"].startswith("[Admin Intake] Offline intake converted to idea - IDEA-")
        assert applicant_calls[0]["to_email"] == "offline@example.com"
        assert applicant_calls[0].get("source_platform") == "ingeniouspark"
    finally:
        _clear_overrides()


def test_email_service_called_after_application_id_is_created(client, monkeypatch):
    _client_with_db(client)
    subjects = []

    def record_admin(**kwargs):
        subjects.append(kwargs["subject"])
        return True

    monkeypatch.setattr("app.services.idea_notification_service.send_admin_notification", record_admin)
    monkeypatch.setattr("app.services.idea_notification_service.send_applicant_email", lambda **kwargs: True)

    try:
        response = client.post("/api/v1/ideas", json=_idea_payload())
        assert response.status_code == 201
        application_id = response.json()["application_id"]
        assert ID_RE.match(application_id)
        assert subjects == [f"New idea submitted - {application_id}"]
    finally:
        _clear_overrides()


def test_password_reset_email_is_not_source_routed(monkeypatch):
    from app.services.password_reset_service import send_password_reset_email

    calls = []
    user = MagicMock()
    user.id = 101
    user.full_name = "Reset User"
    user.email = "reset-user@example.com"

    monkeypatch.setattr(
        "app.services.password_reset_service.send_applicant_email",
        lambda **kwargs: calls.append(kwargs) or True,
    )

    assert send_password_reset_email(user, "safe-token", datetime.utcnow()) is True
    assert calls[0]["to_email"] == "reset-user@example.com"
    assert "source_platform" not in calls[0]


def test_admin_created_user_email_is_not_source_routed(monkeypatch):
    from app.models.user import ProgramTrack
    from app.services.user_notification_service import notify_user_created

    calls = []
    user = MagicMock()
    user.id = 102
    user.full_name = "Created User"
    user.email = "created-user@example.com"
    user.role = UserRole.JURY
    user.program_track = ProgramTrack.NATIONAL_INTERNATIONAL

    monkeypatch.setattr(
        "app.services.user_notification_service.send_applicant_email",
        lambda **kwargs: calls.append(kwargs) or True,
    )

    notify_user_created(user, "TempPass123!")
    assert calls[0]["to_email"] == "created-user@example.com"
    assert "source_platform" not in calls[0]


def test_idea_request_more_info_email_uses_applicant_and_source_bcc(monkeypatch):
    from app.models.idea import IdeaStatus
    from app.services.idea_notification_service import notify_idea_status_update

    calls = []
    monkeypatch.setattr(
        "app.services.idea_notification_service.send_applicant_email",
        lambda **kwargs: calls.append(kwargs) or True,
    )

    idea = Idea(
        application_id="IDEA-TEST-INFO",
        applicant_name="Info Applicant",
        email="idea-applicant@example.com",
        idea_title="Request Info Idea",
        current_status=IdeaStatus.NEEDS_MORE_INFORMATION,
        source_platform="sirmv-idea",
    )

    notify_idea_status_update(
        idea,
        new_status="NEEDS_MORE_INFORMATION",
        public_message="Please provide more prototype details.",
    )

    assert calls[0]["to_email"] == "idea-applicant@example.com"
    assert calls[0]["bcc"] == "smvvisions@gmail.com"
    assert "Please provide more prototype details." in calls[0]["text_body"]


def test_create_intake_succeeds_and_does_not_reference_idea(client, monkeypatch):
    db_session_factory = _client_with_db(client)
    headers = _admin_headers(db_session_factory)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("plain intake creation must not send idea conversion email")

    monkeypatch.setattr("app.routers.intake.notify_intake_conversion", fail_if_called)

    try:
        response = client.post("/api/v1/admin/intake", json=_intake_payload(), headers=headers)
        assert response.status_code == 201
        body = response.json()
        assert INTAKE_RE.match(body["intake_id"])
        assert body["intake_status"] == "RAW_RECEIVED"
        assert body["standardized_idea_id"] is None
    finally:
        _clear_overrides()


def test_create_intake_with_team_and_guardian_fields(client, monkeypatch):
    db_session_factory = _client_with_db(client)
    headers = _admin_headers(db_session_factory)
    monkeypatch.setattr("app.routers.intake.notify_intake_conversion", lambda *args, **kwargs: None)

    payload = _intake_payload(
        source_program="NMF_K12",
        applicant_type="TEAM",
        age=16,
        team_name="School Makers",
        team_member_count=2,
        team_member_names=["Student Lead", "Student Member"],
        guardian_name="Parent Name",
        guardian_phone="7777777777",
        guardian_email="parent@example.com",
        guardian_relationship="Father",
        guardian_consent=True,
        gender="Prefer not to say",
        application_context="Used in school science lab",
        uniqueness="Uses local materials",
        consent_data=True,
        consent_original=True,
        consent_contact=True,
    )

    try:
        response = client.post("/api/v1/admin/intake", json=payload, headers=headers)
        assert response.status_code == 201
        body = response.json()
        assert body["team_name"] == "School Makers"
        assert body["team_member_count"] == 2
        assert body["team_member_names"] == ["Student Lead", "Student Member"]
        assert body["guardian_name"] == "Parent Name"
        assert body["guardian_consent"] is True
        assert body["application_context"] == "Used in school science lab"
        assert body["consent_original"] is True
    finally:
        _clear_overrides()


def test_update_intake_with_team_and_guardian_fields(client):
    db_session_factory = _client_with_db(client)
    headers = _admin_headers(db_session_factory)

    try:
        created = client.post("/api/v1/admin/intake", json=_intake_payload(), headers=headers)
        assert created.status_code == 201
        intake_id = created.json()["intake_id"]

        response = client.patch(
            f"/api/v1/admin/intake/{intake_id}",
            json={
                "source_program": "NMF_K12",
                "applicant_type": "TEAM",
                "age": 15,
                "team_name": "Updated Team",
                "team_member_count": 3,
                "team_member_names": ["One", "Two", "Three"],
                "guardian_name": "Updated Parent",
                "guardian_phone": "6666666666",
                "guardian_relationship": "Guardian",
                "guardian_consent": True,
                "application_context": "Community fair",
                "uniqueness": "Simple repairable parts",
            },
            headers=headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["team_name"] == "Updated Team"
        assert body["team_member_names"] == ["One", "Two", "Three"]
        assert body["guardian_name"] == "Updated Parent"
        assert body["uniqueness"] == "Simple repairable parts"
    finally:
        _clear_overrides()


def test_convert_intake_to_idea_preserves_team_guardian_and_alignment_fields(client, monkeypatch):
    db_session_factory = _client_with_db(client)
    headers = _admin_headers(db_session_factory)
    monkeypatch.setattr("app.services.idea_notification_service.send_admin_notification", lambda **kwargs: True)
    monkeypatch.setattr("app.services.idea_notification_service.send_applicant_email", lambda **kwargs: True)

    db = db_session_factory()
    try:
        admin = User(
            full_name="Conversion Admin",
            email="conversion-admin@example.com",
            password_hash="not-used",
            role=UserRole.SUPER_ADMIN,
            is_active=True,
        )
        db.add(admin)
        db.flush()
        intake = IntakeSubmission(
            intake_id="INTAKE-PRESERVE",
            created_by_user_id=admin.id,
            source_type="OFFLINE_FORM",
            source_program="NMF_K12",
            applicant_type="TEAM",
            visibility_scope="LOCAL_ONLY",
            applicant_name="K12 Team",
            phone="9999999999",
            email="k12-team@example.com",
            age=16,
            gender="Female",
            location="Mysuru",
            organization="School",
            team_name="K12 Makers",
            team_member_count=2,
            team_member_names=["Lead Student", "Second Student"],
            guardian_name="Guardian Name",
            guardian_phone="8888888888",
            guardian_email="guardian@example.com",
            guardian_relationship="Mother",
            guardian_consent=True,
            raw_title="K12 Preserved Idea",
            problem_statement="A school problem.",
            solution_description="A school solution.",
            application_context="Classroom usage",
            uniqueness="Reusable parts",
            category="Education",
            target_users="Students",
            prototype_status="Concept",
            support_needed="Mentorship",
            consent_data=True,
            consent_original=True,
            consent_contact=True,
            intake_status=IntakeStatus.READY_FOR_REVIEW,
            completeness_status=CompletenessStatus.COMPLETE,
        )
        db.add(intake)
        db.commit()
    finally:
        db.close()

    try:
        response = client.post("/api/v1/admin/intake/INTAKE-PRESERVE/convert-to-idea", headers=headers)
        assert response.status_code == 200
        idea_id = response.json()["standardized_idea_id"]

        db = db_session_factory()
        try:
            idea = db.query(Idea).filter(Idea.id == idea_id).one()
            assert idea.team_name == "K12 Makers"
            assert idea.team_member_count == 2
            assert idea.team_member_names == ["Lead Student", "Second Student"]
            assert idea.guardian_name == "Guardian Name"
            assert idea.guardian_phone == "8888888888"
            assert idea.guardian_email == "guardian@example.com"
            assert idea.guardian_relationship == "Mother"
            assert idea.guardian_consent is True
            assert idea.gender == "Female"
            assert idea.application_context == "Classroom usage"
            assert idea.uniqueness == "Reusable parts"
            assert idea.consent_data is True
            assert idea.consent_original is True
            assert idea.consent_contact is True
        finally:
            db.close()
    finally:
        _clear_overrides()


def test_pending_intake_stats_excludes_converted_intake(client):
    db_session_factory = _client_with_db(client)
    headers = _admin_headers(db_session_factory)
    converted_idea_id = _create_idea(db_session_factory)

    db = db_session_factory()
    try:
        admin = db.query(User).filter(User.email == "admin-idea@example.com").first()
        raw = IntakeSubmission(
            intake_id="INTAKE-RAW",
            created_by_user_id=admin.id,
            source_type="OFFLINE_FORM",
            source_program="NMF_LOCAL",
            applicant_name="Raw Applicant",
            raw_title="Raw Idea",
            intake_status=IntakeStatus.RAW_RECEIVED,
            completeness_status=CompletenessStatus.NOT_CHECKED,
        )
        converted = IntakeSubmission(
            intake_id="INTAKE-CONVERTED",
            created_by_user_id=admin.id,
            source_type="OFFLINE_FORM",
            source_program="NMF_LOCAL",
            applicant_name="Converted Applicant",
            email="converted@example.com",
            raw_title="Converted Idea",
            standardized_idea_id=converted_idea_id,
            intake_status=IntakeStatus.CONVERTED_TO_IDEA,
            completeness_status=CompletenessStatus.COMPLETE,
        )
        db.add_all([raw, converted])
        db.commit()
    finally:
        db.close()

    try:
        response = client.get("/api/v1/admin/intake/stats", headers=headers)
        assert response.status_code == 200
        assert response.json()["pending_intake"] == 1
    finally:
        _clear_overrides()


def test_pending_intake_stats_counts_raw_new_intake(client):
    db_session_factory = _client_with_db(client)
    headers = _admin_headers(db_session_factory)

    db = db_session_factory()
    try:
        admin = db.query(User).filter(User.email == "admin-idea@example.com").first()
        intake = IntakeSubmission(
            intake_id="INTAKE-RAW",
            created_by_user_id=admin.id,
            source_type="OFFLINE_FORM",
            source_program="NMF_LOCAL",
            applicant_name="Raw Applicant",
            raw_title="Raw Idea",
            intake_status=IntakeStatus.RAW_RECEIVED,
            completeness_status=CompletenessStatus.NOT_CHECKED,
        )
        db.add(intake)
        db.commit()
    finally:
        db.close()

    try:
        response = client.get("/api/v1/admin/intake/stats", headers=headers)
        assert response.status_code == 200
        assert response.json()["pending_intake"] == 1
    finally:
        _clear_overrides()


def test_intake_list_returns_status_and_standardized_idea_id(client):
    db_session_factory = _client_with_db(client)
    headers = _admin_headers(db_session_factory)
    converted_idea_id = _create_idea(db_session_factory)

    db = db_session_factory()
    try:
        admin = db.query(User).filter(User.email == "admin-idea@example.com").first()
        intake = IntakeSubmission(
            intake_id="INTAKE-CONVERTED",
            created_by_user_id=admin.id,
            source_type="OFFLINE_FORM",
            source_program="NMF_LOCAL",
            applicant_name="Converted Applicant",
            raw_title="Converted Idea",
            standardized_idea_id=converted_idea_id,
            intake_status=IntakeStatus.CONVERTED_TO_IDEA,
            completeness_status=CompletenessStatus.COMPLETE,
        )
        db.add(intake)
        db.commit()
    finally:
        db.close()

    try:
        response = client.get("/api/v1/admin/intake", headers=headers)
        assert response.status_code == 200
        rows = response.json()
        assert rows[0]["intake_status"] == "CONVERTED_TO_IDEA"
        assert rows[0]["standardized_idea_id"] == converted_idea_id
    finally:
        _clear_overrides()
