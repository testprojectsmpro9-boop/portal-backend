from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.user import ProgramTrack, User, UserRole
from app.utils.security import create_access_token, verify_password


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine, tables=[User.__table__])

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


def _headers_for_role(db_session_factory, role, email, program_track=None):
    db = db_session_factory()
    try:
        user = User(
            full_name=f"{role.value} User",
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


def _user_payload(**overrides):
    data = {
        "full_name": "Created User",
        "email": "created@example.com",
        "phone": "1234567890",
        "password": "CreatedPass123!",
        "role": "INVENTOR",
        "program_track": "NATIONAL_INTERNATIONAL",
    }
    data.update(overrides)
    return data


def _seed_user(db_session_factory, email, role, program_track=None, is_active=True):
    db = db_session_factory()
    try:
        user = User(
            full_name=email.split("@")[0],
            email=email,
            password_hash=f"hash-{email}",
            role=role,
            program_track=program_track,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id
    finally:
        db.close()


def test_public_register_with_super_admin_role_creates_inventor(client):
    db_session_factory = _session_factory()
    try:
        response = client.post(
            "/api/v1/auth/register",
            json=_user_payload(email="public@example.com", role="SUPER_ADMIN", program_track="K12"),
        )

        assert response.status_code == 201
        data = response.json()
        assert data["role"] == "INVENTOR"
        assert data["program_track"] is None
        assert "password_hash" not in data

        db = db_session_factory()
        try:
            user = db.query(User).filter(User.email == "public@example.com").one()
            assert user.role == UserRole.INVENTOR
            assert user.program_track is None
        finally:
            db.close()
    finally:
        _clear_overrides()


def test_super_admin_can_create_global_admin(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, UserRole.SUPER_ADMIN, "super@example.com")
        response = client.post(
            "/api/v1/admin/users",
            json=_user_payload(email="global@example.com", role="TEAM_ADMIN_GLOBAL"),
            headers=headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["role"] == "TEAM_ADMIN_GLOBAL"
        assert data["program_track"] == "NATIONAL_INTERNATIONAL"
        assert "password_hash" not in data
    finally:
        _clear_overrides()


def test_super_admin_can_create_local_admin(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, UserRole.SUPER_ADMIN, "super@example.com")
        response = client.post(
            "/api/v1/admin/users",
            json=_user_payload(
                email="local@example.com",
                role="TEAM_ADMIN_LOCAL",
                program_track="LOCAL_REGIONAL",
            ),
            headers=headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["role"] == "TEAM_ADMIN_LOCAL"
        assert data["program_track"] == "LOCAL_REGIONAL"
    finally:
        _clear_overrides()


def test_super_admin_can_create_jury(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, UserRole.SUPER_ADMIN, "super@example.com")
        response = client.post(
            "/api/v1/admin/users",
            json=_user_payload(email="jury@example.com", role="JURY"),
            headers=headers,
        )

        assert response.status_code == 201
        assert response.json()["role"] == "JURY"
    finally:
        _clear_overrides()


def test_global_admin_can_create_scoped_jury_and_inventor(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            UserRole.TEAM_ADMIN_GLOBAL,
            "global-admin@example.com",
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        jury_response = client.post(
            "/api/v1/admin/users",
            json=_user_payload(email="global-jury@example.com", role="JURY"),
            headers=headers,
        )
        inventor_response = client.post(
            "/api/v1/admin/users",
            json=_user_payload(email="global-inventor@example.com", role="INVENTOR"),
            headers=headers,
        )

        assert jury_response.status_code == 201
        assert jury_response.json()["program_track"] == "NATIONAL_INTERNATIONAL"
        assert inventor_response.status_code == 201
        assert inventor_response.json()["program_track"] == "NATIONAL_INTERNATIONAL"
    finally:
        _clear_overrides()


def test_local_admin_can_create_local_or_k12_jury_and_inventor(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            UserRole.TEAM_ADMIN_LOCAL,
            "local-admin@example.com",
            ProgramTrack.LOCAL_REGIONAL,
        )
        jury_response = client.post(
            "/api/v1/admin/users",
            json=_user_payload(email="local-jury@example.com", role="JURY", program_track="LOCAL_REGIONAL"),
            headers=headers,
        )
        inventor_response = client.post(
            "/api/v1/admin/users",
            json=_user_payload(email="k12-inventor@example.com", role="INVENTOR", program_track="K12"),
            headers=headers,
        )

        assert jury_response.status_code == 201
        assert jury_response.json()["program_track"] == "LOCAL_REGIONAL"
        assert inventor_response.status_code == 201
        assert inventor_response.json()["program_track"] == "K12"
    finally:
        _clear_overrides()


def test_local_admin_cannot_create_global_admin(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            UserRole.TEAM_ADMIN_LOCAL,
            "local-admin@example.com",
            ProgramTrack.LOCAL_REGIONAL,
        )
        response = client.post(
            "/api/v1/admin/users",
            json=_user_payload(email="bad-global@example.com", role="TEAM_ADMIN_GLOBAL"),
            headers=headers,
        )

        assert response.status_code == 403
    finally:
        _clear_overrides()


def test_jury_cannot_create_users(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, UserRole.JURY, "jury-admin@example.com")
        response = client.post(
            "/api/v1/admin/users",
            json=_user_payload(email="blocked@example.com", role="INVENTOR"),
            headers=headers,
        )

        assert response.status_code == 403
    finally:
        _clear_overrides()


def test_created_user_password_is_hashed(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, UserRole.SUPER_ADMIN, "super@example.com")
        payload = _user_payload(email="hashed@example.com", password="HashMe123!", role="INVENTOR")
        response = client.post("/api/v1/admin/users", json=payload, headers=headers)

        assert response.status_code == 201
        db = db_session_factory()
        try:
            user = db.query(User).filter(User.email == "hashed@example.com").one()
            assert user.password_hash != "HashMe123!"
            assert verify_password("HashMe123!", user.password_hash)
        finally:
            db.close()
    finally:
        _clear_overrides()


def test_user_list_is_scoped_and_does_not_expose_password_hash(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            UserRole.TEAM_ADMIN_GLOBAL,
            "global-admin@example.com",
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        db = db_session_factory()
        try:
            db.add_all([
                User(
                    full_name="Global Jury",
                    email="global-jury@example.com",
                    password_hash="secret-a",
                    role=UserRole.JURY,
                    program_track=ProgramTrack.NATIONAL_INTERNATIONAL,
                    is_active=True,
                ),
                User(
                    full_name="Local Jury",
                    email="local-jury@example.com",
                    password_hash="secret-b",
                    role=UserRole.JURY,
                    program_track=ProgramTrack.LOCAL_REGIONAL,
                    is_active=True,
                ),
            ])
            db.commit()
        finally:
            db.close()

        response = client.get("/api/v1/admin/users", headers=headers)

        assert response.status_code == 200
        data = response.json()
        emails = {item["email"] for item in data}
        assert "global-jury@example.com" in emails
        assert "local-jury@example.com" not in emails
        assert all("password_hash" not in item for item in data)
    finally:
        _clear_overrides()


def test_super_admin_user_list_tolerates_legacy_invalid_email_row(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, UserRole.SUPER_ADMIN, "super@example.com")
        _seed_user(db_session_factory, "legacy-local@example.test", UserRole.SUPER_ADMIN, None)

        response = client.get("/api/v1/admin/users", headers=headers)

        assert response.status_code == 200
        emails = {item["email"] for item in response.json()}
        assert "legacy-local@example.test" in emails
        assert all("password_hash" not in item for item in response.json())
    finally:
        _clear_overrides()


def test_admin_cannot_deactivate_self(client):
    db_session_factory = _session_factory()
    try:
        headers, user_id = _headers_for_role(
            db_session_factory,
            UserRole.SUPER_ADMIN,
            "super@example.com",
        )
        response = client.patch(
            f"/api/v1/admin/users/{user_id}/status",
            json={"is_active": False},
            headers=headers,
        )

        assert response.status_code == 403
    finally:
        _clear_overrides()


def test_local_admin_cannot_manage_global_scoped_user(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            UserRole.TEAM_ADMIN_LOCAL,
            "local-admin@example.com",
            ProgramTrack.LOCAL_REGIONAL,
        )
        db = db_session_factory()
        try:
            target = User(
                full_name="Global Inventor",
                email="global-inventor@example.com",
                password_hash="secret",
                role=UserRole.INVENTOR,
                program_track=ProgramTrack.NATIONAL_INTERNATIONAL,
                is_active=True,
            )
            db.add(target)
            db.commit()
            db.refresh(target)
            target_id = target.id
        finally:
            db.close()

        response = client.patch(
            f"/api/v1/admin/users/{target_id}/status",
            json={"is_active": False},
            headers=headers,
        )

        assert response.status_code == 403
    finally:
        _clear_overrides()


def test_global_admin_can_deactivate_scoped_inventor(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            UserRole.TEAM_ADMIN_GLOBAL,
            "global-admin@example.com",
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        db = db_session_factory()
        try:
            target = User(
                full_name="Scoped Inventor",
                email="scoped-inventor@example.com",
                password_hash="secret",
                role=UserRole.INVENTOR,
                program_track=ProgramTrack.NATIONAL_INTERNATIONAL,
                is_active=True,
            )
            db.add(target)
            db.commit()
            db.refresh(target)
            target_id = target.id
        finally:
            db.close()

        response = client.patch(
            f"/api/v1/admin/users/{target_id}/status",
            json={"is_active": False},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["is_active"] is False
    finally:
        _clear_overrides()


def test_super_admin_can_update_user_details(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, UserRole.SUPER_ADMIN, "super@example.com")
        db = db_session_factory()
        try:
            target = User(
                full_name="Old Name",
                email="old@example.com",
                password_hash="secret",
                role=UserRole.INVENTOR,
                program_track=ProgramTrack.K12,
                is_active=True,
            )
            db.add(target)
            db.commit()
            db.refresh(target)
            target_id = target.id
        finally:
            db.close()

        response = client.patch(
            f"/api/v1/admin/users/{target_id}",
            json={
                "full_name": "New Name",
                "email": "new@example.com",
                "phone": "9998887777",
                "role": "JURY",
                "program_track": "NATIONAL_INTERNATIONAL",
                "is_active": False,
            },
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["full_name"] == "New Name"
        assert data["email"] == "new@example.com"
        assert data["phone"] == "9998887777"
        assert data["role"] == "JURY"
        assert data["program_track"] == "NATIONAL_INTERNATIONAL"
        assert data["is_active"] is False
    finally:
        _clear_overrides()


def test_local_admin_cannot_update_user_outside_scope(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            UserRole.TEAM_ADMIN_LOCAL,
            "local-admin@example.com",
            ProgramTrack.LOCAL_REGIONAL,
        )
        db = db_session_factory()
        try:
            target = User(
                full_name="Scoped Inventor",
                email="scoped@example.com",
                password_hash="secret",
                role=UserRole.INVENTOR,
                program_track=ProgramTrack.LOCAL_REGIONAL,
                is_active=True,
            )
            db.add(target)
            db.commit()
            db.refresh(target)
            target_id = target.id
        finally:
            db.close()

        response = client.patch(
            f"/api/v1/admin/users/{target_id}",
            json={"program_track": "NATIONAL_INTERNATIONAL"},
            headers=headers,
        )

        assert response.status_code == 403
    finally:
        _clear_overrides()


def test_super_admin_summary_includes_all_role_counts(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, UserRole.SUPER_ADMIN, "super@example.com")
        _seed_user(db_session_factory, "global-admin@example.com", UserRole.TEAM_ADMIN_GLOBAL, ProgramTrack.NATIONAL_INTERNATIONAL)
        _seed_user(db_session_factory, "local-admin@example.com", UserRole.TEAM_ADMIN_LOCAL, ProgramTrack.LOCAL_REGIONAL)
        _seed_user(db_session_factory, "jury@example.com", UserRole.JURY, ProgramTrack.NATIONAL_INTERNATIONAL)
        _seed_user(db_session_factory, "inventor@example.com", UserRole.INVENTOR, ProgramTrack.K12, is_active=False)

        response = client.get("/api/v1/admin/users/summary", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total_users"] == 5
        assert data["active_users"] == 4
        assert data["inactive_users"] == 1
        assert data["by_role"]["SUPER_ADMIN"] == 1
        assert data["by_role"]["TEAM_ADMIN_GLOBAL"] == 1
        assert data["by_role"]["TEAM_ADMIN_LOCAL"] == 1
        assert data["by_role"]["JURY"] == 1
        assert data["by_role"]["INVENTOR"] == 1
    finally:
        _clear_overrides()


def test_super_admin_summary_includes_program_track_breakdown(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, UserRole.SUPER_ADMIN, "super@example.com")
        _seed_user(db_session_factory, "global-jury@example.com", UserRole.JURY, ProgramTrack.NATIONAL_INTERNATIONAL)
        _seed_user(db_session_factory, "local-jury@example.com", UserRole.JURY, ProgramTrack.LOCAL_REGIONAL)
        _seed_user(db_session_factory, "k12-inventor@example.com", UserRole.INVENTOR, ProgramTrack.K12)
        _seed_user(db_session_factory, "unassigned-inventor@example.com", UserRole.INVENTOR, None)

        response = client.get("/api/v1/admin/users/summary", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["by_program_track"]["NATIONAL_INTERNATIONAL"] == 1
        assert data["by_program_track"]["LOCAL_REGIONAL"] == 1
        assert data["by_program_track"]["K12"] == 1
        assert data["by_program_track"]["UNASSIGNED"] == 2
        assert data["scoped_role_counts"]["JURY"]["NATIONAL_INTERNATIONAL"] == 1
        assert data["scoped_role_counts"]["INVENTOR"]["K12"] == 1
    finally:
        _clear_overrides()


def test_global_admin_summary_only_includes_national_international_users(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            UserRole.TEAM_ADMIN_GLOBAL,
            "global-admin@example.com",
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        _seed_user(db_session_factory, "global-jury@example.com", UserRole.JURY, ProgramTrack.NATIONAL_INTERNATIONAL)
        _seed_user(db_session_factory, "global-inventor@example.com", UserRole.INVENTOR, ProgramTrack.NATIONAL_INTERNATIONAL, is_active=False)
        _seed_user(db_session_factory, "local-jury@example.com", UserRole.JURY, ProgramTrack.LOCAL_REGIONAL)
        _seed_user(db_session_factory, "k12-inventor@example.com", UserRole.INVENTOR, ProgramTrack.K12)

        response = client.get("/api/v1/admin/users/summary", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total_users"] == 2
        assert data["active_users"] == 1
        assert data["inactive_users"] == 1
        assert data["by_role"] == {"JURY": 1, "INVENTOR": 1}
        assert data["by_program_track"] == {"NATIONAL_INTERNATIONAL": 2}
    finally:
        _clear_overrides()


def test_global_admin_summary_does_not_expose_local_or_k12_counts(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            UserRole.TEAM_ADMIN_GLOBAL,
            "global-admin@example.com",
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        _seed_user(db_session_factory, "local-jury@example.com", UserRole.JURY, ProgramTrack.LOCAL_REGIONAL)
        _seed_user(db_session_factory, "k12-inventor@example.com", UserRole.INVENTOR, ProgramTrack.K12)

        response = client.get("/api/v1/admin/users/summary", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert "LOCAL_REGIONAL" not in data["by_program_track"]
        assert "K12" not in data["by_program_track"]
        assert "LOCAL_REGIONAL" not in data["scoped_role_counts"]["JURY"]
        assert "K12" not in data["scoped_role_counts"]["INVENTOR"]
        assert "SUPER_ADMIN" not in data["by_role"]
        assert "TEAM_ADMIN_LOCAL" not in data["by_role"]
    finally:
        _clear_overrides()


def test_local_admin_summary_only_includes_local_and_k12_users(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            UserRole.TEAM_ADMIN_LOCAL,
            "local-admin@example.com",
            ProgramTrack.LOCAL_REGIONAL,
        )
        _seed_user(db_session_factory, "local-jury@example.com", UserRole.JURY, ProgramTrack.LOCAL_REGIONAL)
        _seed_user(db_session_factory, "k12-jury@example.com", UserRole.JURY, ProgramTrack.K12, is_active=False)
        _seed_user(db_session_factory, "local-inventor@example.com", UserRole.INVENTOR, ProgramTrack.LOCAL_REGIONAL)
        _seed_user(db_session_factory, "global-inventor@example.com", UserRole.INVENTOR, ProgramTrack.NATIONAL_INTERNATIONAL)

        response = client.get("/api/v1/admin/users/summary", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total_users"] == 3
        assert data["active_users"] == 2
        assert data["inactive_users"] == 1
        assert data["by_role"] == {"JURY": 2, "INVENTOR": 1}
        assert data["by_program_track"] == {"LOCAL_REGIONAL": 2, "K12": 1}
        assert data["scoped_role_counts"]["JURY"]["LOCAL_REGIONAL"] == 1
        assert data["scoped_role_counts"]["JURY"]["K12"] == 1
        assert data["scoped_role_counts"]["INVENTOR"]["LOCAL_REGIONAL"] == 1
    finally:
        _clear_overrides()


def test_local_admin_summary_does_not_expose_national_international_counts(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            UserRole.TEAM_ADMIN_LOCAL,
            "local-admin@example.com",
            ProgramTrack.LOCAL_REGIONAL,
        )
        _seed_user(db_session_factory, "global-jury@example.com", UserRole.JURY, ProgramTrack.NATIONAL_INTERNATIONAL)

        response = client.get("/api/v1/admin/users/summary", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert "NATIONAL_INTERNATIONAL" not in data["by_program_track"]
        assert "NATIONAL_INTERNATIONAL" not in data["scoped_role_counts"]["JURY"]
        assert "TEAM_ADMIN_GLOBAL" not in data["by_role"]
        assert "SUPER_ADMIN" not in data["by_role"]
    finally:
        _clear_overrides()


def test_jury_cannot_access_user_summary(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, UserRole.JURY, "jury@example.com")
        response = client.get("/api/v1/admin/users/summary", headers=headers)

        assert response.status_code == 403
    finally:
        _clear_overrides()


def test_inventor_cannot_access_user_summary(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, UserRole.INVENTOR, "inventor@example.com")
        response = client.get("/api/v1/admin/users/summary", headers=headers)

        assert response.status_code == 403
    finally:
        _clear_overrides()


def test_user_summary_does_not_include_password_hash(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, UserRole.SUPER_ADMIN, "super@example.com")
        _seed_user(db_session_factory, "inventor@example.com", UserRole.INVENTOR, ProgramTrack.K12)

        response = client.get("/api/v1/admin/users/summary", headers=headers)

        assert response.status_code == 200
        assert "password_hash" not in str(response.json())
    finally:
        _clear_overrides()


# ─── Email notification tests ────────────────────────────────────────────────

def test_email_notification_sent_on_user_creation(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, UserRole.SUPER_ADMIN, "super@example.com")
        with patch("app.routers.admin.notify_user_created") as mock_notify:
            response = client.post(
                "/api/v1/admin/users",
                json=_user_payload(email="notified@example.com", role="INVENTOR", password="TestPass123!"),
                headers=headers,
            )

        assert response.status_code == 201
        mock_notify.assert_called_once()
        created_user, plain_password = mock_notify.call_args[0]
        assert created_user.email == "notified@example.com"
        assert plain_password == "TestPass123!"
    finally:
        _clear_overrides()


def test_email_failure_does_not_prevent_user_creation(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, UserRole.SUPER_ADMIN, "super@example.com")
        with patch(
            "app.routers.admin.notify_user_created",
            side_effect=Exception("Simulated SMTP failure"),
        ):
            response = client.post(
                "/api/v1/admin/users",
                json=_user_payload(email="smtp-fail@example.com", role="INVENTOR"),
                headers=headers,
            )

        assert response.status_code == 201
        assert response.json()["email"] == "smtp-fail@example.com"
        assert "password_hash" not in response.json()
    finally:
        _clear_overrides()


def test_email_notification_includes_role_and_email(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, UserRole.SUPER_ADMIN, "super@example.com")
        with patch("app.routers.admin.notify_user_created") as mock_notify:
            response = client.post(
                "/api/v1/admin/users",
                json=_user_payload(email="rolecheck@example.com", role="JURY"),
                headers=headers,
            )

        assert response.status_code == 201
        created_user, _ = mock_notify.call_args[0]
        assert created_user.email == "rolecheck@example.com"
        assert created_user.role == UserRole.JURY
    finally:
        _clear_overrides()


def test_email_notification_receives_plain_password_not_hash(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, UserRole.SUPER_ADMIN, "super@example.com")
        with patch("app.routers.admin.notify_user_created") as mock_notify:
            response = client.post(
                "/api/v1/admin/users",
                json=_user_payload(email="hashcheck@example.com", password="PlainPass1!", role="INVENTOR"),
                headers=headers,
            )

        assert response.status_code == 201
        _, plain_password = mock_notify.call_args[0]
        # Notification receives the plain-text password, not the hash
        assert plain_password == "PlainPass1!"
        assert "password_hash" not in response.json()
    finally:
        _clear_overrides()
