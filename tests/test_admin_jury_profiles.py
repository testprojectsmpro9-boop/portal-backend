from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.jury import JuryProfile
from app.models.user import ProgramTrack, User, UserRole
from app.utils.security import create_access_token


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine, tables=[User.__table__, JuryProfile.__table__])

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


def _seed_user(db_session_factory, email, role, program_track=None, is_active=True):
    db = db_session_factory()
    try:
        user = User(
            full_name=email.split("@")[0],
            email=email,
            phone="9999999999",
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


def _headers_for_role(db_session_factory, role, email, program_track=None):
    user_id = _seed_user(db_session_factory, email, role, program_track)
    token = create_access_token({"user_id": user_id, "email": email, "role": role.value})
    return {"Authorization": f"Bearer {token}"}, user_id


def _seed_profile(db_session_factory, user_id, expertise_field="Engineering"):
    db = db_session_factory()
    try:
        profile = JuryProfile(
            user_id=user_id,
            expertise_field=expertise_field,
            sub_field="Prototype",
            qualification="M.Tech",
            organization="NMF",
            experience_years=8,
            max_review_capacity=10,
            is_available=True,
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
        return profile.id
    finally:
        db.close()


def _profile_payload(user_id, **overrides):
    data = {
        "user_id": user_id,
        "expertise_field": "Engineering",
        "sub_field": "Prototype",
        "qualification": "M.Tech",
        "organization": "NMF",
        "experience_years": 8,
        "max_review_capacity": 10,
        "is_available": True,
    }
    data.update(overrides)
    return data


def test_super_admin_can_create_jury_profile_for_scoped_jury_user(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, UserRole.SUPER_ADMIN, "super@example.com")
        jury_id = _seed_user(
            db_session_factory,
            "global-jury@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )

        response = client.post("/api/v1/admin/jury-profiles", json=_profile_payload(jury_id), headers=headers)

        assert response.status_code == 201
        data = response.json()
        assert data["user_id"] == jury_id
        assert data["email"] == "global-jury@example.com"
        assert data["program_track"] == "NATIONAL_INTERNATIONAL"
        assert "password_hash" not in data
    finally:
        _clear_overrides()


def test_global_admin_can_create_profile_for_national_international_jury(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            UserRole.TEAM_ADMIN_GLOBAL,
            "global-admin@example.com",
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        jury_id = _seed_user(
            db_session_factory,
            "global-jury@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )

        response = client.post("/api/v1/admin/jury-profiles", json=_profile_payload(jury_id), headers=headers)

        assert response.status_code == 201
        assert response.json()["program_track"] == "NATIONAL_INTERNATIONAL"
    finally:
        _clear_overrides()


def test_global_admin_cannot_create_profile_for_local_or_k12_jury(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            UserRole.TEAM_ADMIN_GLOBAL,
            "global-admin@example.com",
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        local_jury_id = _seed_user(
            db_session_factory,
            "local-jury@example.com",
            UserRole.JURY,
            ProgramTrack.LOCAL_REGIONAL,
        )
        k12_jury_id = _seed_user(db_session_factory, "k12-jury@example.com", UserRole.JURY, ProgramTrack.K12)

        local_response = client.post(
            "/api/v1/admin/jury-profiles",
            json=_profile_payload(local_jury_id),
            headers=headers,
        )
        k12_response = client.post(
            "/api/v1/admin/jury-profiles",
            json=_profile_payload(k12_jury_id),
            headers=headers,
        )

        assert local_response.status_code == 403
        assert k12_response.status_code == 403
    finally:
        _clear_overrides()


def test_local_admin_can_create_profile_for_local_jury(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            UserRole.TEAM_ADMIN_LOCAL,
            "local-admin@example.com",
            ProgramTrack.LOCAL_REGIONAL,
        )
        jury_id = _seed_user(
            db_session_factory,
            "local-jury@example.com",
            UserRole.JURY,
            ProgramTrack.LOCAL_REGIONAL,
        )

        response = client.post("/api/v1/admin/jury-profiles", json=_profile_payload(jury_id), headers=headers)

        assert response.status_code == 201
        assert response.json()["program_track"] == "LOCAL_REGIONAL"
    finally:
        _clear_overrides()


def test_local_admin_can_create_profile_for_k12_jury(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            UserRole.TEAM_ADMIN_LOCAL,
            "local-admin@example.com",
            ProgramTrack.LOCAL_REGIONAL,
        )
        jury_id = _seed_user(db_session_factory, "k12-jury@example.com", UserRole.JURY, ProgramTrack.K12)

        response = client.post("/api/v1/admin/jury-profiles", json=_profile_payload(jury_id), headers=headers)

        assert response.status_code == 201
        assert response.json()["program_track"] == "K12"
    finally:
        _clear_overrides()


def test_local_admin_cannot_create_profile_for_national_international_jury(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            UserRole.TEAM_ADMIN_LOCAL,
            "local-admin@example.com",
            ProgramTrack.LOCAL_REGIONAL,
        )
        jury_id = _seed_user(
            db_session_factory,
            "global-jury@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )

        response = client.post("/api/v1/admin/jury-profiles", json=_profile_payload(jury_id), headers=headers)

        assert response.status_code == 403
    finally:
        _clear_overrides()


def test_cannot_create_jury_profile_for_inventor_user(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, UserRole.SUPER_ADMIN, "super@example.com")
        inventor_id = _seed_user(
            db_session_factory,
            "inventor@example.com",
            UserRole.INVENTOR,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )

        response = client.post("/api/v1/admin/jury-profiles", json=_profile_payload(inventor_id), headers=headers)

        assert response.status_code == 400
    finally:
        _clear_overrides()


def test_cannot_create_duplicate_jury_profile(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, UserRole.SUPER_ADMIN, "super@example.com")
        jury_id = _seed_user(
            db_session_factory,
            "jury@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        _seed_profile(db_session_factory, jury_id)

        response = client.post("/api/v1/admin/jury-profiles", json=_profile_payload(jury_id), headers=headers)

        assert response.status_code == 400
    finally:
        _clear_overrides()


def test_scoped_list_hides_out_of_scope_profiles(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            UserRole.TEAM_ADMIN_GLOBAL,
            "global-admin@example.com",
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        global_jury_id = _seed_user(
            db_session_factory,
            "global-jury@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        local_jury_id = _seed_user(
            db_session_factory,
            "local-jury@example.com",
            UserRole.JURY,
            ProgramTrack.LOCAL_REGIONAL,
        )
        _seed_profile(db_session_factory, global_jury_id, "Global")
        _seed_profile(db_session_factory, local_jury_id, "Local")

        response = client.get("/api/v1/admin/jury-profiles", headers=headers)

        assert response.status_code == 200
        data = response.json()
        emails = {item["email"] for item in data}
        assert emails == {"global-jury@example.com"}
        assert all(item["program_track"] == "NATIONAL_INTERNATIONAL" for item in data)
    finally:
        _clear_overrides()


def test_jury_profile_responses_do_not_expose_password_hash(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(db_session_factory, UserRole.SUPER_ADMIN, "super@example.com")
        jury_id = _seed_user(
            db_session_factory,
            "jury@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        _seed_profile(db_session_factory, jury_id)

        list_response = client.get("/api/v1/admin/jury-profiles", headers=headers)
        get_response = client.get(f"/api/v1/admin/jury-profiles/{jury_id}", headers=headers)

        assert list_response.status_code == 200
        assert get_response.status_code == 200
        assert "password_hash" not in str(list_response.json())
        assert "password_hash" not in str(get_response.json())
    finally:
        _clear_overrides()


def test_jury_and_inventor_cannot_create_jury_profiles(client):
    db_session_factory = _session_factory()
    try:
        jury_headers, _ = _headers_for_role(db_session_factory, UserRole.JURY, "jury-admin@example.com")
        inventor_headers, _ = _headers_for_role(db_session_factory, UserRole.INVENTOR, "inventor-admin@example.com")
        target_jury_id = _seed_user(
            db_session_factory,
            "target-jury@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )

        jury_response = client.post(
            "/api/v1/admin/jury-profiles",
            json=_profile_payload(target_jury_id),
            headers=jury_headers,
        )
        inventor_response = client.post(
            "/api/v1/admin/jury-profiles",
            json=_profile_payload(target_jury_id),
            headers=inventor_headers,
        )

        assert jury_response.status_code == 403
        assert inventor_response.status_code == 403
    finally:
        _clear_overrides()


def test_global_admin_can_update_scoped_jury_profile(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            UserRole.TEAM_ADMIN_GLOBAL,
            "global-admin@example.com",
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        jury_id = _seed_user(
            db_session_factory,
            "global-jury@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        _seed_profile(db_session_factory, jury_id)

        response = client.patch(
            f"/api/v1/admin/jury-profiles/{jury_id}",
            json={"expertise_field": "AI", "is_available": False},
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["expertise_field"] == "AI"
        assert data["is_available"] is False
    finally:
        _clear_overrides()


def test_local_admin_cannot_update_national_international_jury_profile(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            UserRole.TEAM_ADMIN_LOCAL,
            "local-admin@example.com",
            ProgramTrack.LOCAL_REGIONAL,
        )
        jury_id = _seed_user(
            db_session_factory,
            "global-jury@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        _seed_profile(db_session_factory, jury_id)

        response = client.patch(
            f"/api/v1/admin/jury-profiles/{jury_id}",
            json={"expertise_field": "AI"},
            headers=headers,
        )

        assert response.status_code == 404
    finally:
        _clear_overrides()


def test_super_admin_can_delete_jury_profile(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            UserRole.SUPER_ADMIN,
            "super@example.com",
        )
        jury_id = _seed_user(
            db_session_factory,
            "delete-jury@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        _seed_profile(db_session_factory, jury_id)

        response = client.delete(f"/api/v1/admin/jury-profiles/{jury_id}", headers=headers)

        assert response.status_code == 204
        db = db_session_factory()
        try:
            assert db.query(JuryProfile).filter(JuryProfile.user_id == jury_id).first() is None
        finally:
            db.close()
    finally:
        _clear_overrides()


def test_local_admin_cannot_delete_out_of_scope_jury_profile(client):
    db_session_factory = _session_factory()
    try:
        headers, _ = _headers_for_role(
            db_session_factory,
            UserRole.TEAM_ADMIN_LOCAL,
            "local-admin@example.com",
            ProgramTrack.LOCAL_REGIONAL,
        )
        jury_id = _seed_user(
            db_session_factory,
            "global-jury-delete@example.com",
            UserRole.JURY,
            ProgramTrack.NATIONAL_INTERNATIONAL,
        )
        _seed_profile(db_session_factory, jury_id)

        response = client.delete(f"/api/v1/admin/jury-profiles/{jury_id}", headers=headers)

        assert response.status_code == 404
    finally:
        _clear_overrides()
