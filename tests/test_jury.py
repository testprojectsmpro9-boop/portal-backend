"""
Tests for Jury Assignment + Evaluation module.

All tests are unit tests — no DB required.
Tests cover:
  - ReviewStatus enum completeness (5 values)
  - Recommendation enum completeness (5 values)
  - AssignJuryRequest: min 1 jury validated
  - AssignJuryRequest: max 3 jury validated
  - AssignJuryRequest: exactly 3 jury accepted
  - AssignJuryRequest: due_date optional
  - EvaluationCreate: problem_clarity_score range 0–10
  - EvaluationCreate: novelty_score range 0–20
  - EvaluationCreate: feasibility_score range 0–20
  - EvaluationCreate: impact_score range 0–20
  - EvaluationCreate: scalability_score range 0–10
  - EvaluationCreate: prototype_readiness_score range 0–10
  - EvaluationCreate: practical_usefulness_score range 0–10
  - EvaluationCreate: score below 0 rejected
  - Total score calculation: max possible = 100
  - Total score calculation: partial scores sum correctly
  - _get_active_assignment raises 403 for unassigned idea
  - JuryProfileOut schema has all required fields
  - JuryAssignmentOut schema has all required fields
  - EvaluationOut schema has total_score field
  - EvaluationOut schema does NOT expose jury_user password or private data
  - EvaluationSummary schema has all required fields
  - ReviewSummaryItem schema fields
  - Admin jury router routes registered
  - Jury router routes registered
  - EvaluationCreate: boundary values accepted (exactly 10, exactly 20, 0)
"""
import pytest
from unittest.mock import MagicMock
from pydantic import ValidationError
from fastapi import HTTPException

from app.models.jury import ReviewStatus, JuryAssignment
from app.models.evaluation import Recommendation
from app.schemas.jury import (
    AssignJuryRequest, JuryProfileOut, JuryAssignmentOut,
)
from app.schemas.evaluation import EvaluationCreate, EvaluationOut, EvaluationSummary, ReviewSummaryItem
from app.routers.jury import _get_active_assignment, router as jury_router
from app.routers.admin_jury import router as admin_jury_router


# ---------------------------------------------------------------------------
# Enum completeness
# ---------------------------------------------------------------------------

def test_review_status_values():
    values = {s.value for s in ReviewStatus}
    assert values == {"PENDING", "IN_PROGRESS", "COMPLETED", "REASSIGNED", "CANCELLED"}
    assert len(values) == 5


def test_recommendation_values():
    values = {r.value for r in Recommendation}
    assert values == {
        "SHORTLIST", "REJECT", "NEEDS_MORE_INFORMATION",
        "PROTOTYPE_REQUIRED", "NEEDS_IMPROVEMENT",
    }
    assert len(values) == 5


# ---------------------------------------------------------------------------
# AssignJuryRequest validation
# ---------------------------------------------------------------------------

def test_assign_jury_min_one():
    with pytest.raises(ValidationError) as exc:
        AssignJuryRequest(jury_user_ids=[])
    assert "1 jury" in str(exc.value).lower() or "at least" in str(exc.value).lower()


def test_assign_jury_max_three():
    with pytest.raises(ValidationError) as exc:
        AssignJuryRequest(jury_user_ids=[1, 2, 3, 4])
    assert "3" in str(exc.value)


def test_assign_jury_exactly_three_accepted():
    obj = AssignJuryRequest(jury_user_ids=[1, 2, 3])
    assert len(obj.jury_user_ids) == 3


def test_assign_jury_one_accepted():
    obj = AssignJuryRequest(jury_user_ids=[42])
    assert obj.jury_user_ids == [42]


def test_assign_jury_due_date_optional():
    obj = AssignJuryRequest(jury_user_ids=[1])
    assert obj.due_date is None


# ---------------------------------------------------------------------------
# EvaluationCreate score range validation
# ---------------------------------------------------------------------------

def _valid_payload(**overrides):
    base = {
        "problem_clarity_score": 8.0,
        "novelty_score": 15.0,
        "feasibility_score": 15.0,
        "impact_score": 15.0,
        "scalability_score": 8.0,
        "prototype_readiness_score": 7.0,
        "practical_usefulness_score": 8.0,
        "recommendation": "SHORTLIST",
    }
    base.update(overrides)
    return base


def test_evaluation_create_valid():
    obj = EvaluationCreate(**_valid_payload())
    assert obj.recommendation == "SHORTLIST"


def test_problem_clarity_above_10_rejected():
    with pytest.raises(ValidationError):
        EvaluationCreate(**_valid_payload(problem_clarity_score=10.1))


def test_novelty_above_20_rejected():
    with pytest.raises(ValidationError):
        EvaluationCreate(**_valid_payload(novelty_score=20.1))


def test_feasibility_above_20_rejected():
    with pytest.raises(ValidationError):
        EvaluationCreate(**_valid_payload(feasibility_score=20.1))


def test_impact_above_20_rejected():
    with pytest.raises(ValidationError):
        EvaluationCreate(**_valid_payload(impact_score=20.1))


def test_scalability_above_10_rejected():
    with pytest.raises(ValidationError):
        EvaluationCreate(**_valid_payload(scalability_score=10.1))


def test_prototype_readiness_above_10_rejected():
    with pytest.raises(ValidationError):
        EvaluationCreate(**_valid_payload(prototype_readiness_score=10.1))


def test_practical_usefulness_above_10_rejected():
    with pytest.raises(ValidationError):
        EvaluationCreate(**_valid_payload(practical_usefulness_score=10.1))


def test_score_below_zero_rejected():
    with pytest.raises(ValidationError):
        EvaluationCreate(**_valid_payload(problem_clarity_score=-0.1))


def test_boundary_zero_accepted():
    obj = EvaluationCreate(**_valid_payload(
        problem_clarity_score=0,
        novelty_score=0,
        feasibility_score=0,
        impact_score=0,
        scalability_score=0,
        prototype_readiness_score=0,
        practical_usefulness_score=0,
    ))
    assert obj.problem_clarity_score == 0


def test_boundary_max_accepted():
    obj = EvaluationCreate(**_valid_payload(
        problem_clarity_score=10,
        novelty_score=20,
        feasibility_score=20,
        impact_score=20,
        scalability_score=10,
        prototype_readiness_score=10,
        practical_usefulness_score=10,
    ))
    assert obj.novelty_score == 20


# ---------------------------------------------------------------------------
# Total score calculation (done in router — test logic directly)
# ---------------------------------------------------------------------------

def _calc_total(payload: EvaluationCreate) -> float:
    return round(
        payload.problem_clarity_score
        + payload.novelty_score
        + payload.feasibility_score
        + payload.impact_score
        + payload.scalability_score
        + payload.prototype_readiness_score
        + payload.practical_usefulness_score,
        2,
    )


def test_total_score_max_is_100():
    payload = EvaluationCreate(**_valid_payload(
        problem_clarity_score=10,
        novelty_score=20,
        feasibility_score=20,
        impact_score=20,
        scalability_score=10,
        prototype_readiness_score=10,
        practical_usefulness_score=10,
    ))
    assert _calc_total(payload) == 100.0


def test_total_score_partial():
    payload = EvaluationCreate(**_valid_payload(
        problem_clarity_score=5,
        novelty_score=10,
        feasibility_score=10,
        impact_score=10,
        scalability_score=5,
        prototype_readiness_score=5,
        practical_usefulness_score=5,
    ))
    assert _calc_total(payload) == 50.0


def test_total_score_zero():
    payload = EvaluationCreate(**_valid_payload(
        problem_clarity_score=0,
        novelty_score=0,
        feasibility_score=0,
        impact_score=0,
        scalability_score=0,
        prototype_readiness_score=0,
        practical_usefulness_score=0,
    ))
    assert _calc_total(payload) == 0.0


# ---------------------------------------------------------------------------
# _get_active_assignment raises 403 for unassigned
# ---------------------------------------------------------------------------

def test_get_active_assignment_raises_403_when_not_assigned():
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.first.return_value = None  # no assignment found

    with pytest.raises(HTTPException) as exc:
        _get_active_assignment(idea_id=1, jury_user_id=99, db=mock_db)
    assert exc.value.status_code == 403


def test_get_active_assignment_returns_assignment_when_exists():
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_assignment = MagicMock(spec=JuryAssignment)
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.first.return_value = mock_assignment

    result = _get_active_assignment(idea_id=1, jury_user_id=5, db=mock_db)
    assert result is mock_assignment


# ---------------------------------------------------------------------------
# Schema field checks
# ---------------------------------------------------------------------------

def test_jury_profile_out_fields():
    fields = set(JuryProfileOut.model_fields.keys())
    required = {"id", "user_id", "max_review_capacity", "is_available", "created_at", "updated_at"}
    assert required.issubset(fields)


def test_jury_assignment_out_fields():
    fields = set(JuryAssignmentOut.model_fields.keys())
    required = {"id", "idea_id", "jury_user_id", "assigned_by_user_id", "review_status", "assigned_at"}
    assert required.issubset(fields)


def test_evaluation_out_has_total_score():
    assert "total_score" in EvaluationOut.model_fields


def test_evaluation_out_does_not_expose_password():
    assert "password_hash" not in EvaluationOut.model_fields
    assert "password" not in EvaluationOut.model_fields


def test_evaluation_summary_fields():
    fields = set(EvaluationSummary.model_fields.keys())
    required = {
        "idea_id", "assigned_jury_count", "completed_review_count",
        "pending_review_count", "recommendations", "reviews",
    }
    assert required.issubset(fields)


def test_review_summary_item_fields():
    fields = set(ReviewSummaryItem.model_fields.keys())
    assert {"jury_user_id", "review_status", "total_score", "recommendation"}.issubset(fields)


# ---------------------------------------------------------------------------
# Router route registration
# ---------------------------------------------------------------------------

def _admin_routes():
    return {r.path for r in admin_jury_router.routes}


def _jury_routes():
    return {r.path for r in jury_router.routes}


def test_admin_jury_create_profile_route():
    assert "/admin/jury-profiles" in _admin_routes()


def test_admin_jury_list_profiles_route():
    assert "/admin/jury-profiles" in _admin_routes()


def test_admin_jury_assign_route():
    assert "/admin/ideas/{idea_id}/assign-jury" in _admin_routes()


def test_admin_jury_list_assignments_route():
    assert "/admin/ideas/{idea_id}/jury-assignments" in _admin_routes()


def test_admin_jury_all_assignments_route():
    assert "/admin/jury-assignments" in _admin_routes()


def test_admin_evaluation_summary_route():
    assert "/admin/ideas/{idea_id}/evaluation-summary" in _admin_routes()


def test_jury_assigned_ideas_route():
    assert "/jury/assigned-ideas" in _jury_routes()


def test_jury_get_idea_route():
    assert "/jury/ideas/{idea_id}" in _jury_routes()


def test_jury_files_route():
    assert "/jury/ideas/{idea_id}/files" in _jury_routes()


def test_jury_review_route():
    assert "/jury/ideas/{idea_id}/review" in _jury_routes()


def test_jury_my_reviews_route():
    assert "/jury/my-reviews" in _jury_routes()
