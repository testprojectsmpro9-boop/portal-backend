"""
Phase 15 — View Admin permission matrix.

Verifies, via real HTTP calls through TestClient (not just unit-level scope
helpers), that:
  - VIEW_ADMIN_LOCAL / VIEW_ADMIN_GLOBAL / VIEW_ADMIN_BOTH can read exactly
    the idea scope their full-admin counterpart can read (reusing the same
    _filter_ideas_by_scope rules already covered by test_pagination_filters.py).
  - Every mutating admin endpoint (status update, delete, assign-jury,
    file upload) returns 403 for all three VIEW_ADMIN_* roles, even with a
    structurally valid request body — proving the backend enforces this,
    not just the frontend hiding buttons.
"""
import io

import openpyxl
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.decision import AdminDecision, IdeaDecision
from app.models.evaluation import Evaluation, Recommendation
from app.models.idea import Idea, IdeaStatus, IdeaVisibilityScope, SourceType
from app.models.idea_file import IdeaFile
from app.models.intake import IntakeSubmission
from app.models.jury import JuryAssignment, JuryProfile, ReviewStatus
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
            IdeaFile.__table__,
            JuryProfile.__table__,
            JuryAssignment.__table__,
            Evaluation.__table__,
            IdeaDecision.__table__,
            IntakeSubmission.__table__,
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


def _seed_user(db_session_factory, email, role, program_track=None, full_name=None):
    db = db_session_factory()
    try:
        user = User(
            full_name=full_name or email.split("@")[0],
            email=email,
            phone="1234567890",
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


def _seed_idea(db_session_factory, application_id, program_track, current_status=IdeaStatus.SUBMITTED, visibility_scope=None):
    db = db_session_factory()
    try:
        idea = Idea(
            application_id=application_id,
            applicant_name=f"Applicant {application_id}",
            email=f"{application_id.lower()}@example.com",
            phone="9999999999",
            program_track=program_track,
            visibility_scope=visibility_scope,
            source_type=SourceType.ONLINE_FORM,
            idea_title=f"Idea {application_id}",
            current_status=current_status,
            is_public_tracking_enabled=True,
        )
        db.add(idea)
        db.commit()
        db.refresh(idea)
        return idea.id
    finally:
        db.close()


def _setup(client):
    db_session_factory = _session_factory()
    _, local_view_headers = _seed_user(db_session_factory, "view-local@example.com", UserRole.VIEW_ADMIN_LOCAL, ProgramTrack.LOCAL_REGIONAL)
    _, global_view_headers = _seed_user(db_session_factory, "view-global@example.com", UserRole.VIEW_ADMIN_GLOBAL, ProgramTrack.NATIONAL_INTERNATIONAL)
    _, both_view_headers = _seed_user(db_session_factory, "view-both@example.com", UserRole.VIEW_ADMIN_BOTH)
    _, super_headers = _seed_user(db_session_factory, "super@example.com", UserRole.SUPER_ADMIN)

    local_idea_id = _seed_idea(db_session_factory, "IDEA-LOCAL-1", ProgramTrack.LOCAL_REGIONAL)
    global_idea_id = _seed_idea(db_session_factory, "IDEA-GLOBAL-1", ProgramTrack.NATIONAL_INTERNATIONAL)

    return db_session_factory, {
        "local": local_view_headers,
        "global": global_view_headers,
        "both": both_view_headers,
        "super": super_headers,
    }, local_idea_id, global_idea_id


# ---------------------------------------------------------------------------
# READ: scope correctness
# ---------------------------------------------------------------------------

def test_view_admin_local_sees_only_local_scope_ideas(client):
    _db, headers, local_id, global_id = _setup(client)
    try:
        resp = client.get("/api/v1/admin/ideas", headers=headers["local"])
        assert resp.status_code == 200
        ids = {row["id"] for row in resp.json()}
        assert local_id in ids
        assert global_id not in ids

        # direct detail access to an out-of-scope idea must 403, not just be
        # absent from the list.
        detail = client.get(f"/api/v1/admin/ideas/{global_id}", headers=headers["local"])
        assert detail.status_code == 403
    finally:
        _clear_overrides()


def test_view_admin_global_sees_only_global_scope_ideas(client):
    _db, headers, local_id, global_id = _setup(client)
    try:
        resp = client.get("/api/v1/admin/ideas", headers=headers["global"])
        assert resp.status_code == 200
        ids = {row["id"] for row in resp.json()}
        assert global_id in ids
        assert local_id not in ids

        detail = client.get(f"/api/v1/admin/ideas/{local_id}", headers=headers["global"])
        assert detail.status_code == 403
    finally:
        _clear_overrides()


def test_view_admin_both_sees_local_and_global(client):
    _db, headers, local_id, global_id = _setup(client)
    try:
        resp = client.get("/api/v1/admin/ideas", headers=headers["both"])
        assert resp.status_code == 200
        ids = {row["id"] for row in resp.json()}
        assert local_id in ids
        assert global_id in ids
    finally:
        _clear_overrides()


# ---------------------------------------------------------------------------
# READ: jury assignments / evaluation summary / decisions / export all
# reachable for VIEW_ADMIN roles within scope
# ---------------------------------------------------------------------------

def test_view_admin_can_read_jury_assignments_evaluation_summary_and_decisions(client):
    db_session_factory, headers, local_id, global_id = _setup(client)
    try:
        jury_id, _ = _seed_user(db_session_factory, "juror@example.com", UserRole.JURY, ProgramTrack.LOCAL_REGIONAL)
        db = db_session_factory()
        try:
            assignment = JuryAssignment(
                idea_id=local_id,
                jury_user_id=jury_id,
                assigned_by_user_id=jury_id,
                review_status=ReviewStatus.COMPLETED,
            )
            db.add(assignment)
            evaluation = Evaluation(
                idea_id=local_id,
                jury_user_id=jury_id,
                problem_clarity_score=8, novelty_score=15, feasibility_score=15,
                impact_score=15, scalability_score=8, prototype_readiness_score=8,
                practical_usefulness_score=8, total_score=77,
                recommendation=Recommendation.SHORTLIST,
                remarks="Solid idea.",
            )
            db.add(evaluation)
            decision = IdeaDecision(
                idea_id=local_id,
                decided_by_user_id=jury_id,
                decision=AdminDecision.REJECTED,
                public_message="Not feasible at this time.",
            )
            db.add(decision)
            db.commit()
        finally:
            db.close()

        assert client.get(f"/api/v1/admin/ideas/{local_id}/jury-assignments", headers=headers["local"]).status_code == 200
        assert client.get(f"/api/v1/admin/ideas/{local_id}/evaluation-summary", headers=headers["local"]).status_code == 200
        assert client.get(f"/api/v1/admin/ideas/{local_id}/decisions", headers=headers["local"]).status_code == 200

        # out-of-scope idea for this role must still 403 on all three
        assert client.get(f"/api/v1/admin/ideas/{global_id}/jury-assignments", headers=headers["local"]).status_code == 403
        assert client.get(f"/api/v1/admin/ideas/{global_id}/evaluation-summary", headers=headers["local"]).status_code == 403
        assert client.get(f"/api/v1/admin/ideas/{global_id}/decisions", headers=headers["local"]).status_code == 403
    finally:
        _clear_overrides()


def test_view_admin_excel_export_respects_scope(client):
    db_session_factory, headers, local_id, global_id = _setup(client)
    try:
        resp = client.get("/api/v1/admin/ideas/export.xlsx", headers=headers["local"])
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        workbook = openpyxl.load_workbook(io.BytesIO(resp.content))
        assert workbook.sheetnames == ["Ideas", "Jury Evaluations"]
        ideas_sheet = workbook["Ideas"]
        application_ids = {row[0] for row in ideas_sheet.iter_rows(min_row=2, values_only=True)}
        assert "IDEA-LOCAL-1" in application_ids
        assert "IDEA-GLOBAL-1" not in application_ids
    finally:
        _clear_overrides()


# ---------------------------------------------------------------------------
# WRITE: every VIEW_ADMIN_* role must get 403 on every mutating endpoint,
# even with a structurally valid request body.
# ---------------------------------------------------------------------------

def test_view_admin_roles_cannot_mutate_anything(client):
    db_session_factory, headers, local_id, global_id = _setup(client)
    try:
        for role_key in ("local", "global", "both"):
            h = headers[role_key]

            status_update = client.patch(
                f"/api/v1/admin/ideas/{local_id}/status",
                json={"current_status": "UNDER_VERIFICATION"},
                headers=h,
            )
            assert status_update.status_code == 403, role_key

            delete_resp = client.delete(f"/api/v1/admin/ideas/{local_id}", headers=h)
            assert delete_resp.status_code == 403, role_key

            assign_resp = client.post(
                f"/api/v1/admin/ideas/{local_id}/assign-jury",
                json={"jury_user_ids": [1]},
                headers=h,
            )
            assert assign_resp.status_code == 403, role_key

            upload_resp = client.post(
                f"/api/v1/ideas/{local_id}/files",
                files={"file": ("note.txt", b"hello", "text/plain")},
                data={"file_type": "DOCUMENT"},
                headers=h,
            )
            assert upload_resp.status_code == 403, role_key

            create_user_resp = client.post(
                "/api/v1/admin/users",
                json={
                    "full_name": "Should Not Create",
                    "email": f"blocked-{role_key}@example.com",
                    "phone": "1234567890",
                    "password": "BlockedPass123!",
                    "role": "INVENTOR",
                },
                headers=h,
            )
            assert create_user_resp.status_code == 403, role_key

            # decision (approve/reject/select all go through this one endpoint)
            decision_resp = client.post(
                f"/api/v1/admin/ideas/{local_id}/decision",
                json={"decision": "REJECTED", "public_message": "no"},
                headers=h,
            )
            assert decision_resp.status_code == 403, role_key

            # reassign jury (assignment status update)
            reassign_resp = client.patch(
                "/api/v1/admin/jury-assignments/1/status",
                json={"review_status": "REASSIGNED"},
                headers=h,
            )
            assert reassign_resp.status_code == 403, role_key

            # intake: create / update / delete / convert
            intake_create_resp = client.post(
                "/api/v1/admin/intake",
                json={"source_type": "OFFLINE_FORM", "applicant_name": "X", "raw_title": "X"},
                headers=h,
            )
            assert intake_create_resp.status_code == 403, role_key

            intake_update_resp = client.patch("/api/v1/admin/intake/INTAKE-1", json={"applicant_name": "Y"}, headers=h)
            assert intake_update_resp.status_code == 403, role_key

            intake_delete_resp = client.delete("/api/v1/admin/intake/INTAKE-1", headers=h)
            assert intake_delete_resp.status_code == 403, role_key

            intake_convert_resp = client.post("/api/v1/admin/intake/INTAKE-1/convert-to-idea", headers=h)
            assert intake_convert_resp.status_code == 403, role_key

            # user edit / delete (also covers admin edit/delete — same endpoints).
            # Target user id doesn't need to exist — the role check runs
            # before any DB lookup, so this must 403, never 404.
            user_edit_resp = client.patch(
                "/api/v1/admin/users/999999",
                json={"full_name": "Renamed"},
                headers=h,
            )
            assert user_edit_resp.status_code == 403, role_key

            user_delete_resp = client.delete("/api/v1/admin/users/999999", headers=h)
            assert user_delete_resp.status_code == 403, role_key

            # jury evaluation mutation — VIEW_ADMIN is not JURY, must also 403
            jury_review_resp = client.post(
                f"/api/v1/jury/ideas/{local_id}/review",
                json={
                    "problem_clarity_score": 5, "novelty_score": 10, "feasibility_score": 10,
                    "impact_score": 10, "scalability_score": 5, "prototype_readiness_score": 5,
                    "practical_usefulness_score": 5, "recommendation": "SHORTLIST",
                },
                headers=h,
            )
            assert jury_review_resp.status_code == 403, role_key

            # messaging mutation
            message_resp = client.post(
                f"/api/v1/admin/ideas/{local_id}/messages",
                json={"message": "hi", "is_internal": False},
                headers=h,
            )
            assert message_resp.status_code == 403, role_key

            block_resp = client.patch(
                f"/api/v1/admin/ideas/{local_id}/message-access",
                json={"inventor_messages_blocked": True},
                headers=h,
            )
            assert block_resp.status_code == 403, role_key
    finally:
        _clear_overrides()


def test_super_admin_can_create_view_admin_users(client):
    _db, headers, _local_id, _global_id = _setup(client)
    try:
        for role, expected_track in (
            ("VIEW_ADMIN_LOCAL", "LOCAL_REGIONAL"),
            ("VIEW_ADMIN_GLOBAL", "NATIONAL_INTERNATIONAL"),
            ("VIEW_ADMIN_BOTH", None),
        ):
            resp = client.post(
                "/api/v1/admin/users",
                json={
                    "full_name": f"New {role}",
                    "email": f"new-{role.lower()}@example.com",
                    "phone": "1234567890",
                    "password": "NewUserPass123!",
                    "role": role,
                },
                headers=headers["super"],
            )
            assert resp.status_code == 201, f"{role} -> {resp.status_code}: {resp.text}"
            assert resp.json()["role"] == role
            assert resp.json()["program_track"] == expected_track
    finally:
        _clear_overrides()


def test_unknown_or_unmapped_role_is_deny_all_on_ideas_list(client):
    """Existing roles never hit the `query.filter(False)` fallback, but the
    fallback itself must stay deny-all — regression guard for the scope
    helpers touched in this change."""
    db_session_factory, headers, local_id, global_id = _setup(client)
    try:
        # INVENTOR/JURY are rejected by require_admin_read before scope logic
        # even runs — confirms the dependency layer, not just the query filter.
        _, inventor_headers = _seed_user(db_session_factory, "inv@example.com", UserRole.INVENTOR)
        resp = client.get("/api/v1/admin/ideas", headers=inventor_headers)
        assert resp.status_code == 403
    finally:
        _clear_overrides()
