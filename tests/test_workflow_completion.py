from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.decision import IdeaDecision
from app.models.evaluation import Evaluation
from app.models.idea import Idea, IdeaStatus, PathwayStage, SourceType
from app.models.jury import JuryAssignment, ReviewStatus
from app.models.message import Message
from app.models.status_history import StatusHistory
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
        tables=[
            User.__table__,
            Idea.__table__,
            StatusHistory.__table__,
            AuditLog.__table__,
            JuryAssignment.__table__,
            Evaluation.__table__,
            IdeaDecision.__table__,
            Message.__table__,
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


def _seed_idea(db_session_factory, application_id="IDEA-2026-WORK01", program_track=ProgramTrack.NATIONAL_INTERNATIONAL):
    db = db_session_factory()
    try:
        idea = Idea(
            application_id=application_id,
            applicant_name="Workflow Applicant",
            email="workflow-applicant@example.com",
            phone="1234567890",
            program_track=program_track,
            source_type=SourceType.ONLINE_FORM,
            idea_title="Workflow Idea",
            current_status=IdeaStatus.SUBMITTED,
            current_pathway_stage=PathwayStage.INTAKE,
            is_public_tracking_enabled=True,
        )
        db.add(idea)
        db.commit()
        db.refresh(idea)
        return idea.id, idea.application_id
    finally:
        db.close()


def _review_payload():
    return {
        "problem_clarity_score": 8,
        "novelty_score": 16,
        "feasibility_score": 15,
        "impact_score": 17,
        "scalability_score": 8,
        "prototype_readiness_score": 7,
        "practical_usefulness_score": 9,
        "remarks": "Good idea",
        "recommendation": "SHORTLIST",
        "reason": "Strong evidence",
    }


def test_manual_status_update_creates_status_history_audit_and_email(client, monkeypatch):
    db_session_factory = _session_factory()
    sent = []
    monkeypatch.setattr(
        "app.routers.admin.notify_idea_status_update",
        lambda idea, new_status, public_message=None: sent.append((idea.application_id, new_status, public_message)),
    )
    try:
        _, headers = _seed_user(db_session_factory, "super-workflow@example.com", UserRole.SUPER_ADMIN)
        idea_id, application_id = _seed_idea(db_session_factory)

        response = client.patch(
            f"/api/v1/admin/ideas/{idea_id}/status",
            json={"current_status": "UNDER_VERIFICATION", "admin_message": "We are checking your idea."},
            headers=headers,
        )

        assert response.status_code == 200
        db = db_session_factory()
        try:
            history = db.query(StatusHistory).one()
            audit = db.query(AuditLog).filter(AuditLog.action == "admin_idea_status_updated").one()
            assert history.old_status == "SUBMITTED"
            assert history.new_status == "UNDER_VERIFICATION"
            assert history.reason == "MANUAL_STATUS_UPDATE"
            assert audit.entity_display_id == application_id
        finally:
            db.close()
        assert sent == [(application_id, "UNDER_VERIFICATION", "We are checking your idea.")]
    finally:
        _clear_overrides()


def test_manual_status_update_same_status_does_not_duplicate_history(client, monkeypatch):
    db_session_factory = _session_factory()
    monkeypatch.setattr("app.routers.admin.notify_idea_status_update", lambda *args, **kwargs: None)
    try:
        _, headers = _seed_user(db_session_factory, "super-no-dup@example.com", UserRole.SUPER_ADMIN)
        idea_id, _ = _seed_idea(db_session_factory)

        response = client.patch(
            f"/api/v1/admin/ideas/{idea_id}/status",
            json={"current_status": "SUBMITTED"},
            headers=headers,
        )

        assert response.status_code == 200
        db = db_session_factory()
        try:
            assert db.query(StatusHistory).count() == 0
            assert db.query(AuditLog).filter(AuditLog.action == "admin_idea_status_updated").count() == 1
        finally:
            db.close()
    finally:
        _clear_overrides()


def test_status_update_succeeds_if_email_fails(client, monkeypatch):
    db_session_factory = _session_factory()

    def fail_email(*args, **kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr("app.routers.admin.notify_idea_status_update", fail_email)
    try:
        _, headers = _seed_user(db_session_factory, "super-email-fail@example.com", UserRole.SUPER_ADMIN)
        idea_id, _ = _seed_idea(db_session_factory)

        response = client.patch(
            f"/api/v1/admin/ideas/{idea_id}/status",
            json={"current_status": "UNDER_VERIFICATION"},
            headers=headers,
        )

        assert response.status_code == 200
    finally:
        _clear_overrides()


def test_scoped_admin_cannot_update_out_of_scope_idea(client):
    db_session_factory = _session_factory()
    try:
        _, headers = _seed_user(
            db_session_factory,
            "local-scope@example.com",
            UserRole.TEAM_ADMIN_LOCAL,
            ProgramTrack.LOCAL_REGIONAL,
        )
        idea_id, _ = _seed_idea(db_session_factory, program_track=ProgramTrack.NATIONAL_INTERNATIONAL)

        response = client.patch(
            f"/api/v1/admin/ideas/{idea_id}/status",
            json={"current_status": "UNDER_VERIFICATION"},
            headers=headers,
        )

        assert response.status_code == 403
    finally:
        _clear_overrides()


def test_decision_sends_status_email(client, monkeypatch):
    db_session_factory = _session_factory()
    sent = []
    monkeypatch.setattr(
        "app.routers.admin_decisions.notify_idea_status_update",
        lambda idea, new_status, public_message=None: sent.append((idea.application_id, new_status, public_message)),
    )
    try:
        _, headers = _seed_user(db_session_factory, "super-decision-email@example.com", UserRole.SUPER_ADMIN)
        idea_id, application_id = _seed_idea(db_session_factory)

        response = client.post(
            f"/api/v1/admin/ideas/{idea_id}/decision",
            json={"decision": "SHORTLISTED", "public_message": "Shortlisted for review."},
            headers=headers,
        )

        assert response.status_code == 201
        assert sent == [(application_id, "FIELD_REVIEW_CLEARED", "Shortlisted for review.")]
    finally:
        _clear_overrides()


def test_jury_assignment_sends_email_and_still_succeeds_if_email_fails(client, monkeypatch):
    db_session_factory = _session_factory()
    sent = []
    monkeypatch.setattr(
        "app.routers.admin_jury.notify_jury_assignment",
        lambda idea, jury_user: sent.append((idea.application_id, jury_user.email)),
    )
    try:
        _, headers = _seed_user(db_session_factory, "super-assign@example.com", UserRole.SUPER_ADMIN)
        jury_id, _ = _seed_user(
            db_session_factory,
            "jury-assign@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        idea_id, application_id = _seed_idea(db_session_factory)

        response = client.post(
            f"/api/v1/admin/ideas/{idea_id}/assign-jury",
            json={"jury_user_ids": [jury_id]},
            headers=headers,
        )

        assert response.status_code == 201
        assert sent == [(application_id, "jury-assign@example.com")]
    finally:
        _clear_overrides()

    db_session_factory = _session_factory()

    def fail_assignment(*args, **kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr("app.routers.admin_jury.notify_jury_assignment", fail_assignment)
    try:
        _, headers = _seed_user(db_session_factory, "super-assign-fail@example.com", UserRole.SUPER_ADMIN)
        jury_id, _ = _seed_user(
            db_session_factory,
            "jury-assign-fail@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        idea_id, _ = _seed_idea(db_session_factory, application_id="IDEA-2026-WORK02")

        response = client.post(
            f"/api/v1/admin/ideas/{idea_id}/assign-jury",
            json={"jury_user_ids": [jury_id]},
            headers=headers,
        )

        assert response.status_code == 201
    finally:
        _clear_overrides()


def test_jury_review_completion_notification_and_audit(client, monkeypatch):
    db_session_factory = _session_factory()
    sent = []
    monkeypatch.setattr(
        "app.routers.jury.notify_jury_review_completed",
        lambda idea, jury_user: sent.append((idea.application_id, jury_user.email)),
    )
    try:
        _, admin_headers = _seed_user(db_session_factory, "super-review@example.com", UserRole.SUPER_ADMIN)
        jury_id, jury_headers = _seed_user(
            db_session_factory,
            "jury-review@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        idea_id, application_id = _seed_idea(db_session_factory)
        client.post(
            f"/api/v1/admin/ideas/{idea_id}/assign-jury",
            json={"jury_user_ids": [jury_id]},
            headers=admin_headers,
        )

        response = client.post(
            f"/api/v1/jury/ideas/{idea_id}/review",
            json=_review_payload(),
            headers=jury_headers,
        )

        assert response.status_code == 201
        assert sent == [(application_id, "jury-review@example.com")]
        db = db_session_factory()
        try:
            assert db.query(AuditLog).filter(AuditLog.action == "jury_review_submitted").count() == 1
        finally:
            db.close()
    finally:
        _clear_overrides()


def test_jury_review_still_succeeds_if_notification_fails(client, monkeypatch):
    db_session_factory = _session_factory()
    monkeypatch.setattr(
        "app.routers.jury.notify_jury_review_completed",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("smtp down")),
    )
    try:
        _, admin_headers = _seed_user(db_session_factory, "super-review-fail@example.com", UserRole.SUPER_ADMIN)
        jury_id, jury_headers = _seed_user(
            db_session_factory,
            "jury-review-fail@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        idea_id, _ = _seed_idea(db_session_factory)
        client.post(
            f"/api/v1/admin/ideas/{idea_id}/assign-jury",
            json={"jury_user_ids": [jury_id]},
            headers=admin_headers,
        )

        response = client.post(
            f"/api/v1/jury/ideas/{idea_id}/review",
            json=_review_payload(),
            headers=jury_headers,
        )

        assert response.status_code == 201
    finally:
        _clear_overrides()


def test_super_admin_cancels_assignment_and_audit_log_created(client, monkeypatch):
    db_session_factory = _session_factory()
    monkeypatch.setattr("app.routers.admin_jury.notify_jury_assignment_status", lambda *args, **kwargs: None)
    try:
        _, headers = _seed_user(db_session_factory, "super-cancel@example.com", UserRole.SUPER_ADMIN)
        jury_id, _ = _seed_user(
            db_session_factory,
            "jury-cancel@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        idea_id, application_id = _seed_idea(db_session_factory)
        created = client.post(
            f"/api/v1/admin/ideas/{idea_id}/assign-jury",
            json={"jury_user_ids": [jury_id]},
            headers=headers,
        ).json()
        assignment_id = created[0]["id"]

        response = client.patch(
            f"/api/v1/admin/jury-assignments/{assignment_id}/status",
            json={"status": "CANCELLED", "note": "Unavailable"},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["review_status"] == "CANCELLED"
        db = db_session_factory()
        try:
            audit = db.query(AuditLog).filter(AuditLog.action == "jury_assignment_status_updated").one()
            assert audit.entity_display_id == application_id
            assert audit.old_values["review_status"] == "PENDING"
            assert audit.new_values["review_status"] == "CANCELLED"
        finally:
            db.close()
    finally:
        _clear_overrides()


def test_scoped_and_non_admin_assignment_status_permissions(client):
    db_session_factory = _session_factory()
    try:
        _, super_headers = _seed_user(db_session_factory, "super-perm@example.com", UserRole.SUPER_ADMIN)
        _, local_headers = _seed_user(
            db_session_factory,
            "local-perm@example.com",
            UserRole.TEAM_ADMIN_LOCAL,
            ProgramTrack.LOCAL_REGIONAL,
        )
        jury_id, jury_headers = _seed_user(
            db_session_factory,
            "jury-perm@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        idea_id, _ = _seed_idea(db_session_factory)
        created = client.post(
            f"/api/v1/admin/ideas/{idea_id}/assign-jury",
            json={"jury_user_ids": [jury_id]},
            headers=super_headers,
        ).json()
        assignment_id = created[0]["id"]

        assert client.patch(
            f"/api/v1/admin/jury-assignments/{assignment_id}/status",
            json={"status": "CANCELLED"},
            headers=local_headers,
        ).status_code == 403
        assert client.patch(
            f"/api/v1/admin/jury-assignments/{assignment_id}/status",
            json={"status": "CANCELLED"},
            headers=jury_headers,
        ).status_code == 403
    finally:
        _clear_overrides()


def test_cancelling_assignment_allows_different_jury_assignment(client, monkeypatch):
    db_session_factory = _session_factory()
    monkeypatch.setattr("app.routers.admin_jury.notify_jury_assignment_status", lambda *args, **kwargs: None)
    try:
        _, headers = _seed_user(db_session_factory, "super-reassign@example.com", UserRole.SUPER_ADMIN)
        jury_one_id, _ = _seed_user(
            db_session_factory,
            "jury-one@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        jury_two_id, _ = _seed_user(
            db_session_factory,
            "jury-two@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        idea_id, _ = _seed_idea(db_session_factory)
        created = client.post(
            f"/api/v1/admin/ideas/{idea_id}/assign-jury",
            json={"jury_user_ids": [jury_one_id]},
            headers=headers,
        ).json()
        duplicate = client.post(
            f"/api/v1/admin/ideas/{idea_id}/assign-jury",
            json={"jury_user_ids": [jury_one_id]},
            headers=headers,
        )
        assert duplicate.status_code == 400

        client.patch(
            f"/api/v1/admin/jury-assignments/{created[0]['id']}/status",
            json={"status": "CANCELLED"},
            headers=headers,
        )
        replacement = client.post(
            f"/api/v1/admin/ideas/{idea_id}/assign-jury",
            json={"jury_user_ids": [jury_two_id]},
            headers=headers,
        )

        assert replacement.status_code == 201
        assert replacement.json()[0]["jury_user_id"] == jury_two_id
    finally:
        _clear_overrides()
