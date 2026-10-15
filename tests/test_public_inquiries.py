from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.public_inquiry import PublicInquiry
from app.models.user import User, UserRole
from app.utils.security import create_access_token


def _client_with_db(client):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine, tables=[User.__table__, PublicInquiry.__table__])

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
    return _headers_for_role(db_session_factory, UserRole.SUPER_ADMIN, "admin@example.com")


def _headers_for_role(db_session_factory, role, email):
    db = db_session_factory()
    try:
        admin = User(
            full_name=f"{role.value} User",
            email=email,
            password_hash="not-used",
            role=role,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        token = create_access_token({"user_id": admin.id, "email": admin.email, "role": admin.role.value})
        return {"Authorization": f"Bearer {token}"}
    finally:
        db.close()


def _payload(**overrides):
    data = {
        "inquiry_type": "CONTACT",
        "full_name": "Test Visitor",
        "email": "visitor@example.com",
        "phone": "9876543210",
        "organization": "Example Org",
        "interest_area": "Innovation",
        "message": "I would like to know more.",
        "source_page": "/contact",
    }
    data.update(overrides)
    return data


def _seed_inquiry(db_session_factory, **overrides):
    db = db_session_factory()
    try:
        inquiry = PublicInquiry(
            inquiry_type=overrides.pop("inquiry_type", "CONTACT"),
            full_name=overrides.pop("full_name", "Scoped Visitor"),
            email=overrides.pop("email", "scoped@example.com"),
            message=overrides.pop("message", "Scoped message"),
            status=overrides.pop("status", "NEW"),
            **overrides,
        )
        db.add(inquiry)
        db.commit()
        db.refresh(inquiry)
        return inquiry.id
    finally:
        db.close()


def _list_ids(client, headers):
    response = client.get("/api/v1/admin/inquiries", headers=headers)
    assert response.status_code == 200
    return {row["id"] for row in response.json()}


def test_public_inquiry_create_saves_record(client, monkeypatch):
    db_session_factory = _client_with_db(client)
    monkeypatch.setattr("app.routers.public_inquiries.send_public_inquiry_notification", lambda **kwargs: True)
    monkeypatch.setattr("app.routers.public_inquiries.send_applicant_email", lambda **kwargs: True)

    try:
        response = client.post("/api/v1/public/inquiries", json=_payload())
        assert response.status_code == 201
        body = response.json()
        assert body["full_name"] == "Test Visitor"
        assert body["status"] == "NEW"

        db = db_session_factory()
        try:
            saved = db.query(PublicInquiry).one()
            assert saved.email == "visitor@example.com"
            assert saved.inquiry_type.value == "CONTACT"
            assert saved.visibility_scope == "GLOBAL_AND_LOCAL"
        finally:
            db.close()
    finally:
        _clear_overrides()


def test_public_inquiry_create_works_even_if_email_fails(client, monkeypatch):
    db_session_factory = _client_with_db(client)

    def fail_email(**kwargs):
        return False

    monkeypatch.setattr("app.routers.public_inquiries.send_public_inquiry_notification", fail_email)
    monkeypatch.setattr("app.routers.public_inquiries.send_applicant_email", fail_email)

    try:
        response = client.post("/api/v1/public/inquiries", json=_payload(inquiry_type="MEMBERSHIP"))
        assert response.status_code == 201
        assert response.json()["inquiry_type"] == "MEMBERSHIP"

        db = db_session_factory()
        try:
            assert db.query(PublicInquiry).count() == 1
        finally:
            db.close()
    finally:
        _clear_overrides()


def test_admin_inquiry_list_requires_auth(client):
    _client_with_db(client)
    try:
        response = client.get("/api/v1/admin/inquiries")
        assert response.status_code == 401
    finally:
        _clear_overrides()


def test_admin_can_update_inquiry_status(client, monkeypatch):
    db_session_factory = _client_with_db(client)
    monkeypatch.setattr("app.routers.public_inquiries.send_public_inquiry_notification", lambda **kwargs: True)
    monkeypatch.setattr("app.routers.public_inquiries.send_applicant_email", lambda **kwargs: True)

    try:
        create_response = client.post("/api/v1/public/inquiries", json=_payload())
        inquiry_id = create_response.json()["id"]
        headers = _admin_headers(db_session_factory)

        response = client.patch(
            f"/api/v1/admin/inquiries/{inquiry_id}/status",
            json={"status": "responded"},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "RESPONDED"
    finally:
        _clear_overrides()


def test_admin_can_assign_inquiry_to_internal_user(client, monkeypatch):
    db_session_factory = _client_with_db(client)
    monkeypatch.setattr("app.routers.public_inquiries.record_audit_log", lambda *args, **kwargs: None)
    inquiry_id = _seed_inquiry(db_session_factory)

    db = db_session_factory()
    try:
        assignee = User(
            full_name="Support Admin",
            email="support-admin@example.com",
            password_hash="not-used",
            role=UserRole.TEAM_ADMIN_GLOBAL,
            is_active=True,
        )
        db.add(assignee)
        db.commit()
        db.refresh(assignee)
        assignee_id = assignee.id
    finally:
        db.close()

    try:
        headers = _admin_headers(db_session_factory)
        response = client.patch(
            f"/api/v1/admin/inquiries/{inquiry_id}/assignment",
            json={"assigned_team_user_id": assignee_id},
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["assigned_team_user_id"] == assignee_id
        assert body["assigned_team_user_name"] == "Support Admin"
        assert body["assigned_team_user_email"] == "support-admin@example.com"
        assert body["assigned_team_user_role"] == "TEAM_ADMIN_GLOBAL"
    finally:
        _clear_overrides()


def test_admin_can_clear_inquiry_assignment(client, monkeypatch):
    db_session_factory = _client_with_db(client)
    monkeypatch.setattr("app.routers.public_inquiries.record_audit_log", lambda *args, **kwargs: None)
    inquiry_id = _seed_inquiry(db_session_factory, assigned_team_user_id=123)

    try:
        headers = _admin_headers(db_session_factory)
        response = client.patch(
            f"/api/v1/admin/inquiries/{inquiry_id}/assignment",
            json={"assigned_team_user_id": None},
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["assigned_team_user_id"] is None
        assert body["assigned_team_user_name"] is None
        assert body["assigned_team_user_email"] is None
        assert body["assigned_team_user_role"] is None
    finally:
        _clear_overrides()


def test_admin_inquiry_assignment_rejects_inventor_and_inactive_users(client, monkeypatch):
    db_session_factory = _client_with_db(client)
    monkeypatch.setattr("app.routers.public_inquiries.record_audit_log", lambda *args, **kwargs: None)
    inquiry_id = _seed_inquiry(db_session_factory)

    db = db_session_factory()
    try:
        inventor = User(
            full_name="Inventor User",
            email="inventor@example.com",
            password_hash="not-used",
            role=UserRole.INVENTOR,
            is_active=True,
        )
        inactive_admin = User(
            full_name="Inactive Admin",
            email="inactive-admin@example.com",
            password_hash="not-used",
            role=UserRole.TEAM_ADMIN_LOCAL,
            is_active=False,
        )
        db.add_all([inventor, inactive_admin])
        db.commit()
        db.refresh(inventor)
        db.refresh(inactive_admin)
        inventor_id = inventor.id
        inactive_admin_id = inactive_admin.id
    finally:
        db.close()

    try:
        headers = _admin_headers(db_session_factory)
        inventor_response = client.patch(
            f"/api/v1/admin/inquiries/{inquiry_id}/assignment",
            json={"assigned_team_user_id": inventor_id},
            headers=headers,
        )
        assert inventor_response.status_code == 400
        assert inventor_response.json()["detail"] == "Assigned user must be an internal admin user."

        inactive_response = client.patch(
            f"/api/v1/admin/inquiries/{inquiry_id}/assignment",
            json={"assigned_team_user_id": inactive_admin_id},
            headers=headers,
        )
        assert inactive_response.status_code == 400
        assert inactive_response.json()["detail"] == "Assigned user must be active."
    finally:
        _clear_overrides()


def test_public_inquiry_invalid_email_rejected(client):
    _client_with_db(client)
    try:
        response = client.post(
            "/api/v1/public/inquiries",
            json=_payload(email="not-an-email"),
        )
        assert response.status_code == 422
    finally:
        _clear_overrides()


def test_public_inquiry_sends_support_email_with_submitter_reply_to(client, monkeypatch):
    _client_with_db(client)
    admin_calls = []

    monkeypatch.setattr(
        "app.routers.public_inquiries.send_public_inquiry_notification",
        lambda **kwargs: admin_calls.append(kwargs) or True,
    )
    monkeypatch.setattr("app.routers.public_inquiries.send_applicant_email", lambda **kwargs: True)

    try:
        response = client.post("/api/v1/public/inquiries", json=_payload())
        assert response.status_code == 201
        assert admin_calls[0]["subject"] == "New CONTACT inquiry - Test Visitor"
        assert admin_calls[0]["reply_to"] == "visitor@example.com"
    finally:
        _clear_overrides()


def test_public_inquiry_sends_submitter_confirmation_when_email_exists(client, monkeypatch):
    _client_with_db(client)
    submitter_calls = []

    monkeypatch.setattr("app.routers.public_inquiries.send_public_inquiry_notification", lambda **kwargs: True)
    monkeypatch.setattr(
        "app.routers.public_inquiries.send_applicant_email",
        lambda **kwargs: submitter_calls.append(kwargs) or True,
    )

    try:
        response = client.post("/api/v1/public/inquiries", json=_payload())
        assert response.status_code == 201
        assert submitter_calls[0]["to_email"] == "visitor@example.com"
        assert submitter_calls[0]["subject"] == "We received your inquiry - NMF-IFIA Innovation Hub"
        assert "Our team will contact you soon." in submitter_calls[0]["text_body"]
    finally:
        _clear_overrides()


def test_public_inquiry_succeeds_if_submitter_confirmation_fails(client, monkeypatch):
    db_session_factory = _client_with_db(client)

    def fail_submitter(**kwargs):
        raise RuntimeError("smtp failed")

    monkeypatch.setattr("app.routers.public_inquiries.send_public_inquiry_notification", lambda **kwargs: True)
    monkeypatch.setattr("app.routers.public_inquiries.send_applicant_email", fail_submitter)

    try:
        response = client.post("/api/v1/public/inquiries", json=_payload())
        assert response.status_code == 201

        db = db_session_factory()
        try:
            assert db.query(PublicInquiry).count() == 1
        finally:
            db.close()
    finally:
        _clear_overrides()


def test_public_inquiry_skips_submitter_confirmation_if_no_email(client, monkeypatch):
    _client_with_db(client)
    submitter_calls = []

    monkeypatch.setattr("app.routers.public_inquiries.send_public_inquiry_notification", lambda **kwargs: True)
    monkeypatch.setattr(
        "app.routers.public_inquiries.send_applicant_email",
        lambda **kwargs: submitter_calls.append(kwargs) or True,
    )

    try:
        response = client.post("/api/v1/public/inquiries", json=_payload(email=None))
        assert response.status_code == 201
        assert submitter_calls == []
    finally:
        _clear_overrides()


def test_public_create_defaults_school_partnership_to_k12_local(client, monkeypatch):
    _client_with_db(client)
    monkeypatch.setattr("app.routers.public_inquiries.send_public_inquiry_notification", lambda **kwargs: True)
    monkeypatch.setattr("app.routers.public_inquiries.send_applicant_email", lambda **kwargs: True)

    try:
        response = client.post(
            "/api/v1/public/inquiries",
            json=_payload(
                inquiry_type="SCHOOL_PARTNERSHIP",
                interest_area="School innovation program",
            ),
        )
        assert response.status_code == 201
        body = response.json()
        assert body["program_track"] == "K12"
        assert body["visibility_scope"] == "LOCAL_ONLY"
        assert body["source_program"] == "NMF_K12"
    finally:
        _clear_overrides()


def test_super_admin_sees_all_inquiries(client):
    db_session_factory = _client_with_db(client)
    headers = _admin_headers(db_session_factory)
    all_ids = {
        _seed_inquiry(db_session_factory, program_track="NATIONAL_INTERNATIONAL", visibility_scope="GLOBAL_ONLY"),
        _seed_inquiry(db_session_factory, program_track="LOCAL_REGIONAL", visibility_scope="LOCAL_ONLY"),
        _seed_inquiry(db_session_factory, program_track="K12", visibility_scope="LOCAL_ONLY"),
        _seed_inquiry(db_session_factory, visibility_scope="SUPER_ADMIN_ONLY"),
    }

    try:
        assert _list_ids(client, headers) == all_ids
    finally:
        _clear_overrides()


def test_team_admin_global_sees_global_and_national_only(client):
    db_session_factory = _client_with_db(client)
    headers = _headers_for_role(
        db_session_factory,
        UserRole.TEAM_ADMIN_GLOBAL,
        "global-admin@example.com",
    )
    national_id = _seed_inquiry(db_session_factory, program_track="NATIONAL_INTERNATIONAL")
    global_id = _seed_inquiry(db_session_factory, visibility_scope="GLOBAL_ONLY")
    shared_id = _seed_inquiry(db_session_factory, visibility_scope="GLOBAL_AND_LOCAL")
    _seed_inquiry(db_session_factory, program_track="LOCAL_REGIONAL", visibility_scope="LOCAL_ONLY")
    _seed_inquiry(db_session_factory, program_track="K12", visibility_scope="LOCAL_ONLY")
    _seed_inquiry(db_session_factory, visibility_scope="SUPER_ADMIN_ONLY")

    try:
        assert _list_ids(client, headers) == {national_id, global_id, shared_id}
    finally:
        _clear_overrides()


def test_team_admin_local_sees_local_and_k12_only(client):
    db_session_factory = _client_with_db(client)
    headers = _headers_for_role(
        db_session_factory,
        UserRole.TEAM_ADMIN_LOCAL,
        "local-admin@example.com",
    )
    local_id = _seed_inquiry(db_session_factory, program_track="LOCAL_REGIONAL")
    k12_id = _seed_inquiry(db_session_factory, program_track="K12")
    local_scope_id = _seed_inquiry(db_session_factory, visibility_scope="LOCAL_ONLY")
    shared_id = _seed_inquiry(db_session_factory, visibility_scope="GLOBAL_AND_LOCAL")
    _seed_inquiry(db_session_factory, program_track="NATIONAL_INTERNATIONAL", visibility_scope="GLOBAL_ONLY")
    _seed_inquiry(db_session_factory, visibility_scope="SUPER_ADMIN_ONLY")

    try:
        assert _list_ids(client, headers) == {local_id, k12_id, local_scope_id, shared_id}
    finally:
        _clear_overrides()


def test_team_admin_global_cannot_view_or_update_local_only_inquiry(client):
    db_session_factory = _client_with_db(client)
    headers = _headers_for_role(
        db_session_factory,
        UserRole.TEAM_ADMIN_GLOBAL,
        "global-admin@example.com",
    )
    inquiry_id = _seed_inquiry(
        db_session_factory,
        program_track="LOCAL_REGIONAL",
        visibility_scope="LOCAL_ONLY",
    )

    try:
        detail = client.get(f"/api/v1/admin/inquiries/{inquiry_id}", headers=headers)
        assert detail.status_code == 404

        update = client.patch(
            f"/api/v1/admin/inquiries/{inquiry_id}/status",
            json={"status": "RESPONDED"},
            headers=headers,
        )
        assert update.status_code == 404
    finally:
        _clear_overrides()


def test_team_admin_local_cannot_view_or_update_global_only_inquiry(client):
    db_session_factory = _client_with_db(client)
    headers = _headers_for_role(
        db_session_factory,
        UserRole.TEAM_ADMIN_LOCAL,
        "local-admin@example.com",
    )
    inquiry_id = _seed_inquiry(
        db_session_factory,
        program_track="NATIONAL_INTERNATIONAL",
        visibility_scope="GLOBAL_ONLY",
    )

    try:
        detail = client.get(f"/api/v1/admin/inquiries/{inquiry_id}", headers=headers)
        assert detail.status_code == 404

        update = client.patch(
            f"/api/v1/admin/inquiries/{inquiry_id}/status",
            json={"status": "RESPONDED"},
            headers=headers,
        )
        assert update.status_code == 404
    finally:
        _clear_overrides()
