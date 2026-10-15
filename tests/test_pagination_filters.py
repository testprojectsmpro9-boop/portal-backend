from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.idea import Idea, IdeaCategory, IdeaStatus, SourceProgram, SourceType
from app.models.intake import CompletenessStatus, IntakeStatus, IntakeSubmission
from app.models.jury import JuryAssignment, JuryProfile, ReviewStatus
from app.models.public_inquiry import PublicInquiry, PublicInquiryType
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
            JuryProfile.__table__,
            JuryAssignment.__table__,
            IntakeSubmission.__table__,
            PublicInquiry.__table__,
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


def _seed_user(db_session_factory, email, role, program_track=None, full_name=None, is_active=True):
    db = db_session_factory()
    try:
        user = User(
            full_name=full_name or email.split("@")[0],
            email=email,
            phone="1234567890",
            password_hash=hash_password("TestPass123!"),
            role=role,
            program_track=program_track,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token({"user_id": user.id, "email": user.email, "role": user.role.value})
        return user.id, {"Authorization": f"Bearer {token}"}
    finally:
        db.close()


def _seed_idea(
    db_session_factory,
    application_id,
    title,
    applicant_name,
    program_track=ProgramTrack.NATIONAL_INTERNATIONAL,
    current_status=IdeaStatus.SUBMITTED,
    created_at=None,
    category=None,
):
    db = db_session_factory()
    try:
        idea = Idea(
            application_id=application_id,
            applicant_name=applicant_name,
            email=f"{application_id.lower()}@example.com",
            phone="9999999999",
            program_track=program_track,
            source_type=SourceType.ONLINE_FORM,
            idea_title=title,
            category=category,
            current_status=current_status,
            created_at=created_at or datetime.utcnow(),
            is_public_tracking_enabled=True,
        )
        db.add(idea)
        db.commit()
        db.refresh(idea)
        return idea.id
    finally:
        db.close()


def test_admin_users_page_paginates_searches_filters_and_scopes(client):
    db_session_factory = _session_factory()
    try:
        _, super_headers = _seed_user(db_session_factory, "super-page@example.com", UserRole.SUPER_ADMIN)
        _, global_headers = _seed_user(
            db_session_factory,
            "global-page@example.com",
            UserRole.TEAM_ADMIN_GLOBAL,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        _seed_user(db_session_factory, "ada@example.com", UserRole.INVENTOR, ProgramTrack.NATIONAL_INTERNATIONAL, "Ada Inventor")
        _seed_user(db_session_factory, "alan@example.com", UserRole.JURY, ProgramTrack.NATIONAL_INTERNATIONAL, "Alan Jury")
        _seed_user(db_session_factory, "local@example.com", UserRole.INVENTOR, ProgramTrack.LOCAL_REGIONAL, "Local Maker")

        response = client.get("/api/v1/admin/users/page?limit=2&offset=0&search=a&role=INVENTOR", headers=super_headers)
        assert response.status_code == 200
        assert response.json()["total"] == 2
        assert len(response.json()["items"]) == 2
        assert "password_hash" not in str(response.json())

        scoped = client.get("/api/v1/admin/users/page?program_track=LOCAL_REGIONAL", headers=global_headers)
        assert scoped.status_code == 200
        assert scoped.json()["total"] == 0
    finally:
        _clear_overrides()


def test_admin_ideas_page_search_filters_dates_and_scope(client):
    db_session_factory = _session_factory()
    try:
        _, super_headers = _seed_user(db_session_factory, "super-ideas-page@example.com", UserRole.SUPER_ADMIN)
        _, local_headers = _seed_user(
            db_session_factory,
            "local-ideas-page@example.com",
            UserRole.TEAM_ADMIN_LOCAL,
            ProgramTrack.LOCAL_REGIONAL,
        )
        _seed_idea(
            db_session_factory,
            "IDEA-2026-PAGE01",
            "Solar Pump",
            "Asha",
            current_status=IdeaStatus.UNDER_VERIFICATION,
            created_at=datetime.utcnow() - timedelta(days=1),
            category=IdeaCategory.WATER,
        )
        _seed_idea(
            db_session_factory,
            "IDEA-2026-PAGE02",
            "School Sensor",
            "Bala",
            program_track=ProgramTrack.K12,
            created_at=datetime.utcnow(),
            category=IdeaCategory.WASTE_MANAGEMENT,
        )

        response = client.get(
            "/api/v1/admin/ideas/page?search=Solar&status=UNDER_VERIFICATION&category=WATER&limit=10",
            headers=super_headers,
        )
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["application_id"] == "IDEA-2026-PAGE01"

        legacy_label = client.get(
            "/api/v1/admin/ideas/page?category=Waste%20Management&limit=10",
            headers=super_headers,
        )
        assert legacy_label.status_code == 200
        assert legacy_label.json()["total"] == 1
        assert legacy_label.json()["items"][0]["application_id"] == "IDEA-2026-PAGE02"

        scoped = client.get("/api/v1/admin/ideas/page", headers=local_headers)
        assert scoped.status_code == 200
        assert scoped.json()["total"] == 1
        assert scoped.json()["items"][0]["program_track"] == "K12"
    finally:
        _clear_overrides()


def test_jury_profiles_page_search_availability_and_scope(client):
    db_session_factory = _session_factory()
    try:
        _, global_headers = _seed_user(
            db_session_factory,
            "global-jury-page@example.com",
            UserRole.TEAM_ADMIN_GLOBAL,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        global_jury_id, _ = _seed_user(
            db_session_factory,
            "robotics-jury@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
            "Robotics Expert",
        )
        local_jury_id, _ = _seed_user(
            db_session_factory,
            "local-jury-page@example.com",
            UserRole.JURY,
            ProgramTrack.LOCAL_REGIONAL,
            "Local Expert",
        )
        db = db_session_factory()
        try:
            db.add_all([
                JuryProfile(user_id=global_jury_id, expertise_field="Robotics", organization="Lab", is_available=True),
                JuryProfile(user_id=local_jury_id, expertise_field="Agriculture", organization="Farm", is_available=True),
            ])
            db.commit()
        finally:
            db.close()

        response = client.get("/api/v1/admin/jury-profiles/page?search=Robotics&is_available=true", headers=global_headers)
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["email"] == "robotics-jury@example.com"
    finally:
        _clear_overrides()


def test_jury_assignments_pages_filter_scope_and_jury_ownership(client):
    db_session_factory = _session_factory()
    try:
        _, super_headers = _seed_user(db_session_factory, "super-assign-page@example.com", UserRole.SUPER_ADMIN)
        _, local_headers = _seed_user(
            db_session_factory,
            "local-assign-page@example.com",
            UserRole.TEAM_ADMIN_LOCAL,
            ProgramTrack.LOCAL_REGIONAL,
        )
        jury_one_id, jury_one_headers = _seed_user(
            db_session_factory,
            "jury-one-page@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        jury_two_id, _ = _seed_user(
            db_session_factory,
            "jury-two-page@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        idea_id = _seed_idea(db_session_factory, "IDEA-2026-ASSIGN1", "Assignment Idea", "Applicant")
        db = db_session_factory()
        try:
            db.add_all([
                JuryAssignment(idea_id=idea_id, jury_user_id=jury_one_id, assigned_by_user_id=1, review_status=ReviewStatus.PENDING),
                JuryAssignment(idea_id=idea_id, jury_user_id=jury_two_id, assigned_by_user_id=1, review_status=ReviewStatus.CANCELLED),
            ])
            db.commit()
        finally:
            db.close()

        pending = client.get("/api/v1/admin/jury-assignments/page?status=PENDING", headers=super_headers)
        assert pending.status_code == 200
        assert pending.json()["total"] == 1

        scoped = client.get("/api/v1/admin/jury-assignments/page", headers=local_headers)
        assert scoped.status_code == 200
        assert scoped.json()["total"] == 0

        own = client.get("/api/v1/jury/assignments/page", headers=jury_one_headers)
        assert own.status_code == 200
        assert own.json()["total"] == 1
        assert own.json()["items"][0]["jury_user_id"] == jury_one_id
    finally:
        _clear_overrides()


def test_intake_page_search_status_source_and_scope(client):
    db_session_factory = _session_factory()
    try:
        admin_id, global_headers = _seed_user(
            db_session_factory,
            "global-intake-page@example.com",
            UserRole.TEAM_ADMIN_GLOBAL,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        db = db_session_factory()
        try:
            db.add_all([
                IntakeSubmission(
                    intake_id="INTAKE-2026-PAGE01",
                    created_by_user_id=admin_id,
                    source_type=SourceType.DOCUMENT,
                    source_program=SourceProgram.NMF_NATIONAL,
                    applicant_name="Nina",
                    email="nina@example.com",
                    raw_title="Water Filter",
                    intake_status=IntakeStatus.READY_FOR_REVIEW,
                    completeness_status=CompletenessStatus.COMPLETE,
                ),
                IntakeSubmission(
                    intake_id="INTAKE-2026-PAGE02",
                    created_by_user_id=admin_id,
                    source_type=SourceType.DOCUMENT,
                    source_program=SourceProgram.NMF_LOCAL,
                    applicant_name="Local",
                    raw_title="Local Tool",
                    intake_status=IntakeStatus.RAW_RECEIVED,
                    completeness_status=CompletenessStatus.NOT_CHECKED,
                ),
            ])
            db.commit()
        finally:
            db.close()

        response = client.get(
            "/api/v1/admin/intake/page?search=Water&status=READY_FOR_REVIEW&program_track=NATIONAL_INTERNATIONAL",
            headers=global_headers,
        )
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["intake_id"] == "INTAKE-2026-PAGE01"
    finally:
        _clear_overrides()


def test_public_inquiries_page_search_status_and_type(client):
    db_session_factory = _session_factory()
    try:
        _, headers = _seed_user(db_session_factory, "super-inquiry-page@example.com", UserRole.SUPER_ADMIN)
        db = db_session_factory()
        try:
            db.add_all([
                PublicInquiry(
                    inquiry_type=PublicInquiryType.CONTACT,
                    full_name="Contact Person",
                    email="contact@example.com",
                    phone="111",
                    message="Need help with collaboration",
                    status="NEW",
                ),
                PublicInquiry(
                    inquiry_type=PublicInquiryType.MEMBERSHIP,
                    full_name="Member Person",
                    email="member@example.com",
                    phone="222",
                    message="Membership details",
                    status="CLOSED",
                ),
            ])
            db.commit()
        finally:
            db.close()

        response = client.get(
            "/api/v1/admin/inquiries/page?search=collaboration&status=NEW&inquiry_type=CONTACT",
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["email"] == "contact@example.com"
    finally:
        _clear_overrides()
