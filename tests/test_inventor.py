"""
Tests for Inventor Dashboard module.

All tests are unit tests — no DB required.
Tests cover:
  - _assert_owns: allows access when email matches
  - _assert_owns: allows access when inventor_id matches
  - _assert_owns: raises 403 when neither matches
  - build_timeline: correct for PROTOTYPE_REQUIRED
  - build_timeline: correct for MENTOR_ASSIGNED
  - build_timeline: correct for INCUBATION_RECOMMENDED
  - MessageOut schema: has is_internal field
  - MessageOut schema: has idea_id and message fields
  - MessageCreate schema: is_internal defaults to False
  - MessageCreate schema: message_type defaults to GENERAL
  - Inventor router: list_my_ideas route is registered
  - Inventor router: get_my_idea route is registered
  - Inventor router: timeline route is registered
  - Inventor router: files route is registered
  - Inventor router: upload route is registered
  - Inventor router: messages route is registered
"""
import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
from datetime import datetime

from app.models.idea import IdeaStatus, PathwayStage
from app.schemas.message import MessageCreate, MessageOut
from app.services.timeline_service import build_timeline, STAGE_ORDER
from app.routers.inventor import _assert_owns, router as inventor_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_idea(email="owner@example.com", inventor_id=1, current_status=IdeaStatus.SUBMITTED, current_pathway_stage=None):
    idea = MagicMock()
    idea.email = email
    idea.inventor_id = inventor_id
    idea.current_status = current_status
    idea.current_pathway_stage = current_pathway_stage
    return idea


def _mock_user(email="owner@example.com", user_id=1):
    user = MagicMock()
    user.email = email
    user.id = user_id
    return user


# ---------------------------------------------------------------------------
# _assert_owns
# ---------------------------------------------------------------------------

def test_assert_owns_email_match():
    idea = _mock_idea(email="owner@example.com")
    user = _mock_user(email="owner@example.com")
    _assert_owns(idea, user)  # must not raise


def test_assert_owns_inventor_id_match():
    idea = _mock_idea(email="other@example.com", inventor_id=42)
    user = _mock_user(email="different@example.com", user_id=42)
    _assert_owns(idea, user)  # must not raise


def test_assert_owns_both_mismatch_raises_403():
    idea = _mock_idea(email="owner@example.com", inventor_id=1)
    user = _mock_user(email="attacker@example.com", user_id=999)
    with pytest.raises(HTTPException) as exc:
        _assert_owns(idea, user)
    assert exc.value.status_code == 403


def test_assert_owns_wrong_email_wrong_id():
    idea = _mock_idea(email="a@example.com", inventor_id=10)
    user = _mock_user(email="b@example.com", user_id=20)
    with pytest.raises(HTTPException):
        _assert_owns(idea, user)


# ---------------------------------------------------------------------------
# Timeline stages for mid-pipeline statuses
# ---------------------------------------------------------------------------

def test_timeline_prototype_required_stage():
    idea = _mock_idea(current_status=IdeaStatus.PROTOTYPE_REQUIRED)
    tl = build_timeline(idea)
    idx = STAGE_ORDER.index("PROTOTYPE")
    assert tl[idx].status == "current"
    assert all(t.status == "completed" for t in tl[:idx])


def test_timeline_mentor_assigned():
    idea = _mock_idea(current_status=IdeaStatus.MENTOR_ASSIGNED)
    tl = build_timeline(idea)
    idx = STAGE_ORDER.index("MENTORSHIP")
    assert tl[idx].status == "current"


def test_timeline_incubation_recommended():
    idea = _mock_idea(current_status=IdeaStatus.INCUBATION_RECOMMENDED)
    tl = build_timeline(idea)
    idx = STAGE_ORDER.index("INCUBATION")
    assert tl[idx].status == "current"


def test_timeline_national_level():
    idea = _mock_idea(current_status=IdeaStatus.RECOMMENDED_FOR_NATIONAL_LEVEL)
    tl = build_timeline(idea)
    idx = STAGE_ORDER.index("NATIONAL_LEVEL")
    assert tl[idx].status == "current"
    assert all(t.status == "completed" for t in tl[:idx])
    assert all(t.status == "upcoming" for t in tl[idx + 1:])


def test_timeline_admin_verification_pathway():
    idea = _mock_idea(
        current_status=IdeaStatus.UNDER_VERIFICATION,
        current_pathway_stage=PathwayStage.ADMIN_VERIFICATION,
    )
    tl = build_timeline(idea)
    assert tl[0].status == "completed"
    assert tl[1].status == "current"


# ---------------------------------------------------------------------------
# MessageCreate schema
# ---------------------------------------------------------------------------

def test_message_create_defaults():
    obj = MessageCreate(message="Hello inventor")
    assert obj.message_type == "GENERAL"
    assert obj.is_internal is False
    assert obj.receiver_user_id is None


def test_message_create_internal_flag():
    obj = MessageCreate(message="Admin note", is_internal=True)
    assert obj.is_internal is True


def test_message_create_requires_message():
    fields = MessageCreate.model_fields
    required = [n for n, f in fields.items() if f.is_required()]
    assert "message" in required


# ---------------------------------------------------------------------------
# MessageOut schema
# ---------------------------------------------------------------------------

def test_message_out_has_is_internal():
    assert "is_internal" in MessageOut.model_fields


def test_message_out_has_required_fields():
    fields = set(MessageOut.model_fields.keys())
    assert {"id", "idea_id", "message", "is_internal", "created_at"}.issubset(fields)


def test_message_out_from_attributes():
    assert MessageOut.model_config.get("from_attributes") is True


# ---------------------------------------------------------------------------
# Inventor router: verify all routes are registered
# ---------------------------------------------------------------------------

def _route_paths():
    return {r.path for r in inventor_router.routes}


def test_inventor_router_my_ideas_route():
    assert "/inventor/my-ideas" in _route_paths()


def test_inventor_router_get_idea_route():
    assert "/inventor/ideas/{idea_id}" in _route_paths()


def test_inventor_router_timeline_route():
    assert "/inventor/ideas/{idea_id}/timeline" in _route_paths()


def test_inventor_router_files_route():
    assert "/inventor/ideas/{idea_id}/files" in _route_paths()


def test_inventor_router_upload_route():
    assert "/inventor/ideas/{idea_id}/upload" in _route_paths()


def test_inventor_router_messages_route():
    assert "/inventor/ideas/{idea_id}/messages" in _route_paths()
