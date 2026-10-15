from app.models.idea import Idea, IdeaStatus, IdeaCategory, SourceType
from app.routers.ideas import _coerce_category


def test_idea_status_count():
    statuses = list(IdeaStatus)
    assert len(statuses) == 20


def test_key_idea_statuses():
    assert IdeaStatus.SUBMITTED.value == "SUBMITTED"
    assert IdeaStatus.CLOSED.value == "CLOSED"
    assert IdeaStatus.SELECTED_FOR_LOCAL_SHOWCASE.value == "SELECTED_FOR_LOCAL_SHOWCASE"
    assert IdeaStatus.RECOGNITION_FUNDING_PATENT_SUPPORT.value == "RECOGNITION_FUNDING_PATENT_SUPPORT"


def test_idea_model_tablename():
    assert Idea.__tablename__ == "ideas"


def test_idea_model_columns():
    columns = [c.name for c in Idea.__table__.columns]
    required = [
        "id", "application_id", "inventor_id", "applicant_name", "email",
        "program_track", "source_type", "idea_title", "problem_statement",
        "solution_description", "category", "current_status",
        "is_public_tracking_enabled", "team_name", "team_member_count",
        "team_member_names", "created_at", "updated_at"
    ]
    for col in required:
        assert col in columns, f"Missing column: {col}"


def test_idea_category_column_uses_database_enum_names():
    enum_values = set(Idea.__table__.c.category.type.enums)
    assert IdeaCategory.WATER.name in enum_values
    assert IdeaCategory.WASTE_MANAGEMENT.name in enum_values
    assert IdeaCategory.WATER.value not in enum_values


def test_idea_category_input_labels_are_coerced_to_enum_members():
    assert _coerce_category("Water") == IdeaCategory.WATER
    assert _coerce_category("WATER") == IdeaCategory.WATER
    assert _coerce_category("WASTE_MANAGEMENT") == IdeaCategory.WASTE_MANAGEMENT
    assert _coerce_category("Waste Management") == IdeaCategory.WASTE_MANAGEMENT
    assert _coerce_category("Technology") == IdeaCategory.AI_SOFTWARE
    assert _coerce_category("Community Development") == IdeaCategory.SOCIAL_INNOVATION
    assert _coerce_category("Other") == IdeaCategory.OTHERS
    assert _coerce_category("Unknown category") == IdeaCategory.OTHERS


def test_source_type_values():
    assert SourceType.ONLINE_FORM.value == "ONLINE_FORM"
    assert SourceType.OFFLINE_FORM.value == "OFFLINE_FORM"
    assert SourceType.WHATSAPP_IMPORT.value == "WHATSAPP_IMPORT"
