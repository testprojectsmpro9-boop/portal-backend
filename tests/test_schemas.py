from app.schemas.auth import LoginRequest, TokenResponse, TokenData
from app.schemas.user import UserCreate, UserOut
from app.schemas.idea import IdeaCreate, IdeaOut
from app.schemas.intake import IntakeSubmissionCreate, IntakeSubmissionUpdate


def test_login_request_schema():
    req = LoginRequest(email="test@example.com", password="secret")
    assert req.email == "test@example.com"
    assert req.password == "secret"


def test_token_response_schema():
    resp = TokenResponse(
        access_token="tok",
        token_type="bearer",
        user={"id": 1, "full_name": "Test", "email": "t@t.com",
              "role": "INVENTOR", "program_track": None}
    )
    assert resp.access_token == "tok"
    assert resp.token_type == "bearer"


def test_user_create_schema():
    user = UserCreate(
        full_name="Test User",
        email="test@example.com",
        password="password123",
        role="INVENTOR"
    )
    assert user.full_name == "Test User"
    assert user.email == "test@example.com"


def test_idea_create_schema():
    idea = IdeaCreate(
        applicant_name="John Doe",
        email="john@example.com",
        program_track="NATIONAL_INTERNATIONAL",
        idea_title="My Idea",
        source_type="ONLINE_FORM"
    )
    assert idea.applicant_name == "John Doe"
    assert idea.program_track == "NATIONAL_INTERNATIONAL"


def test_idea_create_normalizes_legacy_prototype_status():
    idea = IdeaCreate(
        applicant_name="John Doe",
        email="john@example.com",
        program_track="NATIONAL_INTERNATIONAL",
        idea_title="My Idea",
        source_type="ONLINE_FORM",
        prototype_status="Only an idea / concept",
    )
    assert idea.prototype_status == "IDEA_STAGE"


def test_intake_create_normalizes_legacy_prototype_status():
    intake = IntakeSubmissionCreate(
        source_type="OFFLINE_FORM",
        applicant_name="Test Applicant",
        raw_title="My Invention",
        prototype_status="Basic prototype available",
    )
    assert intake.prototype_status == "BASIC_PROTOTYPE"


def test_intake_update_normalizes_legacy_prototype_status():
    update = IntakeSubmissionUpdate(
        prototype_status="Working model ready for demonstration",
    )
    assert update.prototype_status == "WORKING_PROTOTYPE"


def test_idea_create_accepts_team_fields():
    idea = IdeaCreate(
        applicant_name="Team Lead",
        email="team@example.com",
        program_track="NATIONAL_INTERNATIONAL",
        idea_title="Team Idea",
        source_type="ONLINE_FORM",
        team_name="Solar Team",
        team_member_count=2,
        team_member_names=["Team Lead", "Member Two"],
    )
    assert idea.team_name == "Solar Team"
    assert idea.team_member_count == 2
    assert idea.team_member_names == ["Team Lead", "Member Two"]
