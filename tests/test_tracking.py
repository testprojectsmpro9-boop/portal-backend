"""
Tests for Public Tracking API.

All tests are unit tests — no DB required.
Tests cover:
  - _verify_ownership: correct email matches
  - _verify_ownership: correct phone matches
  - _verify_ownership: wrong value rejected
  - _verify_ownership: case-insensitive email match
  - _build_response: excludes private fields (no email, no phone, no inventor_id)
  - _build_response: includes timeline
  - build_timeline: SUBMITTED → stage 0 is "current", rest "upcoming"
  - build_timeline: UNDER_VERIFICATION → stage 1 is "current", stage 0 "completed"
  - build_timeline: SELECTED_FOR_STATE_LEVEL → STATE_LEVEL is "current"
  - build_timeline: correct number of stages (13)
  - build_timeline: pathway_stage takes precedence when further along
  - PublicTrackRequest schema: requires application_id and phone_or_email
  - PublicTrackResponse schema: has all required fields
  - TimelineItem schema: has stage, label, status
"""
import pytest
from unittest.mock import MagicMock
from datetime import datetime

from app.models.idea import IdeaStatus, PathwayStage
from app.schemas.tracking import PublicTrackRequest, PublicTrackResponse, TimelineItem
from app.routers.tracking import _verify_ownership, _build_response
from app.services.timeline_service import (
    build_timeline, STAGE_ORDER, _current_stage_index, _TERMINAL_REJECTED,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_idea(
    application_id="IDEA-0001",
    idea_title="Test Invention",
    email="inventor@example.com",
    phone="9876543210",
    current_status=IdeaStatus.SUBMITTED,
    current_stage=None,
    current_pathway_stage=None,
    next_action=None,
    admin_message=None,
    is_public_tracking_enabled=True,
    created_at=None,
):
    idea = MagicMock()
    idea.application_id = application_id
    idea.idea_title = idea_title
    idea.email = email
    idea.phone = phone
    idea.current_status = current_status
    idea.current_stage = current_stage
    idea.current_pathway_stage = current_pathway_stage
    idea.next_action = next_action
    idea.admin_message = admin_message
    idea.is_public_tracking_enabled = is_public_tracking_enabled
    idea.created_at = created_at or datetime.utcnow()
    return idea


# ---------------------------------------------------------------------------
# _verify_ownership
# ---------------------------------------------------------------------------

def test_verify_ownership_correct_email():
    idea = _mock_idea(email="inventor@example.com")
    assert _verify_ownership(idea, "inventor@example.com") is True


def test_verify_ownership_email_case_insensitive():
    idea = _mock_idea(email="Inventor@Example.COM")
    assert _verify_ownership(idea, "inventor@example.com") is True


def test_verify_ownership_correct_phone():
    idea = _mock_idea(phone="9876543210")
    assert _verify_ownership(idea, "9876543210") is True


def test_verify_ownership_wrong_value():
    idea = _mock_idea(email="inventor@example.com", phone="9876543210")
    assert _verify_ownership(idea, "wrong@example.com") is False
    assert _verify_ownership(idea, "0000000000") is False


def test_verify_ownership_phone_with_spaces():
    idea = _mock_idea(phone="  9876543210  ")
    assert _verify_ownership(idea, "9876543210") is True


def test_verify_ownership_none_phone():
    idea = _mock_idea(phone=None, email="a@b.com")
    assert _verify_ownership(idea, "9876543210") is False
    assert _verify_ownership(idea, "a@b.com") is True


# ---------------------------------------------------------------------------
# _build_response — private field exclusion
# ---------------------------------------------------------------------------

def test_build_response_excludes_private_fields():
    idea = _mock_idea()
    resp = _build_response(idea)
    data = resp.model_dump()
    # Must not contain any inventor-identifying private data
    assert "email" not in data
    assert "phone" not in data
    assert "inventor_id" not in data
    assert "password_hash" not in data


def test_build_response_includes_required_fields():
    idea = _mock_idea(
        application_id="IDEA-0042",
        idea_title="Solar Drip",
        current_status=IdeaStatus.UNDER_VERIFICATION,
    )
    resp = _build_response(idea)
    assert resp.application_id == "IDEA-0042"
    assert resp.idea_title == "Solar Drip"
    assert resp.current_status == "UNDER_VERIFICATION"
    assert isinstance(resp.timeline, list)
    assert len(resp.timeline) == 13


def test_build_response_timeline_is_list_of_timeline_items():
    idea = _mock_idea()
    resp = _build_response(idea)
    for item in resp.timeline:
        assert isinstance(item, TimelineItem)
        assert item.status in ("completed", "current", "upcoming")


# ---------------------------------------------------------------------------
# build_timeline — stage ordering
# ---------------------------------------------------------------------------

def test_build_timeline_submitted_is_current():
    idea = _mock_idea(current_status=IdeaStatus.SUBMITTED)
    tl = build_timeline(idea)
    assert tl[0].stage == "SUBMITTED"
    assert tl[0].status == "current"
    assert all(t.status == "upcoming" for t in tl[1:])


def test_build_timeline_under_verification_marks_stage1_current():
    idea = _mock_idea(current_status=IdeaStatus.UNDER_VERIFICATION)
    tl = build_timeline(idea)
    assert tl[0].status == "completed"
    assert tl[1].stage == "ADMIN_VERIFICATION"
    assert tl[1].status == "current"
    assert all(t.status == "upcoming" for t in tl[2:])


def test_build_timeline_state_level_correct():
    idea = _mock_idea(current_status=IdeaStatus.SELECTED_FOR_STATE_LEVEL)
    tl = build_timeline(idea)
    idx = STAGE_ORDER.index("STATE_LEVEL")
    assert tl[idx].status == "current"
    assert all(t.status == "completed" for t in tl[:idx])
    assert all(t.status == "upcoming" for t in tl[idx + 1:])


def test_build_timeline_total_stages():
    # Normal (non-rejected) flow always returns 13 stages
    idea = _mock_idea()
    tl = build_timeline(idea)
    assert len(tl) == 13


def test_build_timeline_prototype_required_unchanged():
    """Existing flow: PROTOTYPE_REQUIRED must not be broken by rejected-path changes."""
    idea = _mock_idea(current_status=IdeaStatus.PROTOTYPE_REQUIRED)
    tl = build_timeline(idea)
    assert len(tl) == 13
    idx = STAGE_ORDER.index("PROTOTYPE")
    assert tl[idx].status == "current"
    assert all(t.status == "completed" for t in tl[:idx])
    assert all(t.status == "upcoming" for t in tl[idx + 1:])


# ---------------------------------------------------------------------------
# Terminal rejected / closed timeline tests
# ---------------------------------------------------------------------------

def test_rejected_by_jury_does_not_mark_recognition_current():
    """
    REJECTED_BY_JURY + pathway=COMPLETED must NOT produce RECOGNITION as current.
    Primary bug: _PATHWAY_INDEX[COMPLETED] = 11 caused max() to pick RECOGNITION.
    """
    idea = _mock_idea(
        current_status=IdeaStatus.REJECTED_BY_JURY,
        current_pathway_stage=PathwayStage.COMPLETED,
    )
    tl = build_timeline(idea)
    assert not any(t.stage == "RECOGNITION" and t.status == "current" for t in tl), (
        "RECOGNITION must never be 'current' for REJECTED_BY_JURY"
    )


def test_rejected_by_jury_shows_rejected_closed_current():
    """REJECTED_BY_JURY timeline must end with REJECTED_CLOSED as 'current'."""
    idea = _mock_idea(
        current_status=IdeaStatus.REJECTED_BY_JURY,
        current_pathway_stage=PathwayStage.COMPLETED,
    )
    tl = build_timeline(idea)
    terminal = tl[-1]
    assert terminal.stage == "REJECTED_CLOSED"
    assert terminal.label == "Rejected / Closed"
    assert terminal.status == "current"
    jury_item = next(t for t in tl if t.stage == "FIELD_JURY_REVIEW")
    assert jury_item.status == "completed"
    assert not any(t.status == "upcoming" for t in tl)


def test_recognition_funding_marks_recognition_current():
    """Only RECOGNITION_FUNDING_PATENT_SUPPORT should mark RECOGNITION as current."""
    idea = _mock_idea(
        current_status=IdeaStatus.RECOGNITION_FUNDING_PATENT_SUPPORT,
        current_pathway_stage=PathwayStage.COMPLETED,
    )
    tl = build_timeline(idea)
    assert len(tl) == 13
    idx = STAGE_ORDER.index("RECOGNITION")
    assert tl[idx].status == "current"
    assert not any(t.stage == "REJECTED_CLOSED" for t in tl)


def test_closed_shows_rejected_closed_terminal():
    """CLOSED must produce a REJECTED_CLOSED terminal item, not RECOGNITION as current."""
    idea = _mock_idea(
        current_status=IdeaStatus.CLOSED,
        current_pathway_stage=PathwayStage.COMPLETED,
    )
    tl = build_timeline(idea)
    terminal = tl[-1]
    assert terminal.stage == "REJECTED_CLOSED"
    assert terminal.status == "current"
    assert not any(t.stage == "RECOGNITION" and t.status == "current" for t in tl)
    assert not any(t.status == "upcoming" for t in tl)


def test_current_stage_index_rejected_by_jury_ignores_pathway():
    """_current_stage_index must return 3 (FIELD_JURY_REVIEW) for REJECTED_BY_JURY
    even when pathway=COMPLETED (which mapped to 11 in the old buggy code)."""
    idea = _mock_idea(
        current_status=IdeaStatus.REJECTED_BY_JURY,
        current_pathway_stage=PathwayStage.COMPLETED,
    )
    idx = _current_stage_index(idea)
    assert idx == 3, f"Expected 3 (FIELD_JURY_REVIEW), got {idx}"


def test_build_timeline_pathway_stage_overrides_when_further():
    # Status says SUBMITTED (idx 0) but pathway says NATIONAL_REVIEW (idx 9)
    idea = _mock_idea(
        current_status=IdeaStatus.SUBMITTED,
        current_pathway_stage=PathwayStage.NATIONAL_REVIEW,
    )
    idx = _current_stage_index(idea)
    assert idx == 9  # pathway wins


def test_build_timeline_pathway_stage_ignored_when_behind():
    # Status says STATE_LEVEL (idx 8) but pathway says SCREENING (idx 1)
    idea = _mock_idea(
        current_status=IdeaStatus.SELECTED_FOR_STATE_LEVEL,
        current_pathway_stage=PathwayStage.SCREENING,
    )
    idx = _current_stage_index(idea)
    assert idx == 8  # status wins


def test_build_timeline_all_stages_have_labels():
    idea = _mock_idea()
    tl = build_timeline(idea)
    for item in tl:
        assert item.label  # non-empty


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

def test_public_track_request_requires_fields():
    fields = PublicTrackRequest.model_fields
    required = [n for n, f in fields.items() if f.is_required()]
    assert "application_id" in required
    assert "phone_or_email" in required


def test_public_track_response_has_timeline():
    assert "timeline" in PublicTrackResponse.model_fields


def test_timeline_item_schema():
    item = TimelineItem(stage="SUBMITTED", label="Submitted", status="current")
    assert item.stage == "SUBMITTED"
    assert item.label == "Submitted"
    assert item.status == "current"
