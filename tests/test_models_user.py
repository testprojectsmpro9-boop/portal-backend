from app.models.user import User, UserRole, ProgramTrack


def test_user_role_enum_values():
    assert UserRole.SUPER_ADMIN.value == "SUPER_ADMIN"
    assert UserRole.TEAM_ADMIN_GLOBAL.value == "TEAM_ADMIN_GLOBAL"
    assert UserRole.TEAM_ADMIN_LOCAL.value == "TEAM_ADMIN_LOCAL"
    assert UserRole.JURY.value == "JURY"
    assert UserRole.INVENTOR.value == "INVENTOR"


def test_program_track_enum_values():
    assert ProgramTrack.NATIONAL_INTERNATIONAL.value == "NATIONAL_INTERNATIONAL"
    assert ProgramTrack.LOCAL_REGIONAL.value == "LOCAL_REGIONAL"
    assert ProgramTrack.K12.value == "K12"


def test_user_model_tablename():
    assert User.__tablename__ == "users"


def test_user_model_columns():
    columns = [c.name for c in User.__table__.columns]
    required = ["id", "full_name", "email", "phone", "password_hash",
                "role", "program_track", "is_active", "must_change_password", "created_at", "updated_at"]
    for col in required:
        assert col in columns, f"Missing column: {col}"
