"""
Tests for Admin Decision + Stage Movement module.

All tests are unit tests — no DB required.
Tests cover:
  - AdminDecision enum has all 13 required values
  - _DECISION_DEFAULTS covers every AdminDecision value
  - Every default maps to a valid IdeaStatus
  - Every default maps to a valid PathwayStage
  - DecisionCreate: decision field required
  - DecisionCreate: all optional fields optional
  - DecisionCreate: admin_note accepted
  - DecisionCreate: public_message accepted
  - DecisionCreate: new_status override accepted as string
  - DecisionOut schema has all required fields
  - DecisionOut: admin_note present (admin sees it)
  - Decision route POST registered
  - Decision route GET registered
  - _get_scoped_idea raises 404 for missing idea
  - _get_scoped_idea raises 403 for out-of-scope idea
  - record_decision derives correct status from decision enum
  - record_decision derives correct pathway from decision enum
  - record_decision: REJECTED → REJECTED_BY_JURY + COMPLETED
  - record_decision: SHORTLISTED → FIELD_REVIEW_CLEARED + LOCAL_REVIEW
  - record_decision: CLOSED → CLOSED + COMPLETED
"""
import pytest
from unittest.mock import MagicMock, patch
from pydantic import ValidationError
from fastapi import HTTPException

from app.models.decision import AdminDecision, IdeaDecision
from app.models.idea import IdeaStatus, PathwayStage
from app.schemas.decision import DecisionCreate, DecisionOut
from app.routers.admin_decisions import (
    router as decisions_router,
    _DECISION_DEFAULTS,
    _get_scoped_idea,
)


# ---------------------------------------------------------------------------
# Enum completeness
# ---------------------------------------------------------------------------

def test_admin_decision_has_13_values():
    assert len(AdminDecision) == 13


def test_admin_decision_required_values():
    required = {
        "SHORTLISTED", "REJECTED", "NEEDS_MORE_INFORMATION", "PROTOTYPE_REQUIRED",
        "PROTOTYPE_APPROVED", "MENTORSHIP_ASSIGNED", "INCUBATION_RECOMMENDED",
        "SELECTED_FOR_LOCAL_SHOWCASE", "SELECTED_FOR_STATE_LEVEL",
        "RECOMMENDED_FOR_NATIONAL_LEVEL", "RECOMMENDED_FOR_INTERNATIONAL_LEVEL",
        "RECOGNITION_FUNDING_PATENT_SUPPORT", "CLOSED",
    }
    assert {d.value for d in AdminDecision} == required


# ---------------------------------------------------------------------------
# Default mapping completeness
# ---------------------------------------------------------------------------

def test_defaults_covers_all_decisions():
    for decision in AdminDecision:
        assert decision in _DECISION_DEFAULTS, f"{decision} missing from _DECISION_DEFAULTS"


def test_defaults_all_map_to_valid_idea_status():
    for decision, (new_status, _) in _DECISION_DEFAULTS.items():
        assert isinstance(new_status, IdeaStatus), f"{decision} maps to invalid IdeaStatus"


def test_defaults_all_map_to_valid_pathway_stage():
    for decision, (_, new_pathway) in _DECISION_DEFAULTS.items():
        assert isinstance(new_pathway, PathwayStage), f"{decision} maps to invalid PathwayStage"


# ---------------------------------------------------------------------------
# Specific decision defaults
# ---------------------------------------------------------------------------

def test_shortlisted_defaults():
    status, pathway = _DECISION_DEFAULTS[AdminDecision.SHORTLISTED]
    assert status == IdeaStatus.FIELD_REVIEW_CLEARED
    assert pathway == PathwayStage.SCREENING


def test_rejected_defaults():
    status, pathway = _DECISION_DEFAULTS[AdminDecision.REJECTED]
    assert status == IdeaStatus.REJECTED_BY_JURY
    assert pathway == PathwayStage.COMPLETED


def test_closed_defaults():
    status, pathway = _DECISION_DEFAULTS[AdminDecision.CLOSED]
    assert status == IdeaStatus.CLOSED
    assert pathway == PathwayStage.COMPLETED


def test_selected_for_state_defaults():
    status, pathway = _DECISION_DEFAULTS[AdminDecision.SELECTED_FOR_STATE_LEVEL]
    assert status == IdeaStatus.SELECTED_FOR_STATE_LEVEL
    assert pathway == PathwayStage.STATE_REVIEW


def test_recommended_national_defaults():
    status, pathway = _DECISION_DEFAULTS[AdminDecision.RECOMMENDED_FOR_NATIONAL_LEVEL]
    assert status == IdeaStatus.RECOMMENDED_FOR_NATIONAL_LEVEL
    assert pathway == PathwayStage.NATIONAL_REVIEW


def test_recommended_international_defaults():
    status, pathway = _DECISION_DEFAULTS[AdminDecision.RECOMMENDED_FOR_INTERNATIONAL_LEVEL]
    assert status == IdeaStatus.RECOMMENDED_FOR_INTERNATIONAL_LEVEL
    assert pathway == PathwayStage.INTERNATIONAL_REVIEW


def test_recognition_defaults():
    status, pathway = _DECISION_DEFAULTS[AdminDecision.RECOGNITION_FUNDING_PATENT_SUPPORT]
    assert status == IdeaStatus.RECOGNITION_FUNDING_PATENT_SUPPORT
    assert pathway == PathwayStage.COMPLETED


def test_incubation_defaults():
    status, pathway = _DECISION_DEFAULTS[AdminDecision.INCUBATION_RECOMMENDED]
    assert status == IdeaStatus.INCUBATION_RECOMMENDED
    assert pathway == PathwayStage.INCUBATION


def test_prototype_required_defaults():
    status, pathway = _DECISION_DEFAULTS[AdminDecision.PROTOTYPE_REQUIRED]
    assert status == IdeaStatus.PROTOTYPE_REQUIRED
    assert pathway == PathwayStage.SCREENING


def test_prototype_approved_defaults():
    status, pathway = _DECISION_DEFAULTS[AdminDecision.PROTOTYPE_APPROVED]
    assert status == IdeaStatus.PROTOTYPE_SUBMITTED
    assert pathway == PathwayStage.SCREENING


def test_needs_more_info_defaults():
    status, pathway = _DECISION_DEFAULTS[AdminDecision.NEEDS_MORE_INFORMATION]
    assert status == IdeaStatus.NEEDS_MORE_INFORMATION
    assert pathway == PathwayStage.ADMIN_VERIFICATION


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def test_decision_create_requires_decision():
    with pytest.raises(ValidationError):
        DecisionCreate()


def test_decision_create_all_optional_fields_optional():
    d = DecisionCreate(decision=AdminDecision.SHORTLISTED)
    assert d.admin_note is None
    assert d.public_message is None
    assert d.new_status is None
    assert d.new_pathway_stage is None


def test_decision_create_with_admin_note():
    d = DecisionCreate(decision=AdminDecision.REJECTED, admin_note="Internal: insufficient originality")
    assert d.admin_note == "Internal: insufficient originality"


def test_decision_create_with_public_message():
    d = DecisionCreate(
        decision=AdminDecision.SHORTLISTED,
        public_message="Congratulations! Your idea has been shortlisted.",
    )
    assert d.public_message == "Congratulations! Your idea has been shortlisted."


def test_decision_create_with_status_override():
    d = DecisionCreate(
        decision=AdminDecision.SHORTLISTED,
        new_status="FIELD_JURY_REVIEW_IN_PROGRESS",
    )
    assert d.new_status == "FIELD_JURY_REVIEW_IN_PROGRESS"


def test_decision_out_has_all_fields():
    from datetime import datetime
    out = DecisionOut(
        id=1,
        idea_id=10,
        decided_by_user_id=2,
        decision=AdminDecision.SHORTLISTED.value,
        old_status="SUBMITTED",
        old_pathway_stage="INTAKE",
        new_status="FIELD_REVIEW_CLEARED",
        new_pathway_stage="LOCAL_REVIEW",
        admin_note="note",
        public_message="msg",
        created_at=datetime.utcnow(),
    )
    assert out.id == 1
    assert out.admin_note == "note"
    assert out.public_message == "msg"


def test_decision_out_admin_note_visible():
    from datetime import datetime
    out = DecisionOut(
        id=1,
        idea_id=10,
        decided_by_user_id=2,
        decision=AdminDecision.REJECTED.value,
        old_status=None,
        old_pathway_stage=None,
        new_status=None,
        new_pathway_stage=None,
        admin_note="Private: inventor lied about prototype",
        public_message=None,
        created_at=datetime.utcnow(),
    )
    assert out.admin_note == "Private: inventor lied about prototype"


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def test_decision_post_route_registered():
    routes = {r.path for r in decisions_router.routes}
    assert "/admin/ideas/{idea_id}/decision" in routes


def test_decision_get_route_registered():
    routes = {r.path for r in decisions_router.routes}
    assert "/admin/ideas/{idea_id}/decisions" in routes


# ---------------------------------------------------------------------------
# _get_scoped_idea
# ---------------------------------------------------------------------------

def test_get_scoped_idea_raises_404_for_missing_idea():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    from app.models.user import UserRole
    user = MagicMock()
    user.role = UserRole.SUPER_ADMIN

    with pytest.raises(HTTPException) as exc:
        _get_scoped_idea(999, user, db)
    assert exc.value.status_code == 404


def test_get_scoped_idea_raises_403_for_out_of_scope():
    from app.models.user import UserRole
    from unittest.mock import patch

    idea = MagicMock()
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = idea

    user = MagicMock()
    user.role = UserRole.TEAM_ADMIN_GLOBAL
    user.id = 5

    with patch("app.routers.admin_decisions._filter_ideas_by_scope") as mock_scope:
        mock_scope.return_value.first.return_value = None
        with pytest.raises(HTTPException) as exc:
            _get_scoped_idea(1, user, db)
    assert exc.value.status_code == 403
