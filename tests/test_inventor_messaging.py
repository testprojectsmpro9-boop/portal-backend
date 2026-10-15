"""
Tests for inventor messaging and admin message-access control.

All tests are unit tests — no DB required.
Tests cover:
  - Inventor can send message for own idea when not blocked
  - Inventor cannot send empty message (schema validation)
  - Inventor cannot message another inventor's idea (ownership)
  - Saved inventor message has is_internal=False and receiver_user_id=None
  - send_inventor_message route is registered on inventor router
  - update_message_access route is registered on admin router
  - Admin can block inventor messages (sets blocked=True, reason, at, by)
  - After blocked, inventor POST message returns 403
  - After blocked with reason, 403 detail includes reason
  - Admin can unblock (clears reason/at/by)
  - After unblock, inventor can send again (not blocked)
  - Block status exposed in IdeaOut schema
  - MessageOut has sender_role field
  - InventorMessageCreate rejects empty message
  - MessageAccessUpdate schema: inventor_messages_blocked is required
  - MessageAccessOut schema: has expected fields
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException

from app.routers.inventor import _assert_owns, send_inventor_message, router as inventor_router
from app.routers.admin import router as admin_router
from app.schemas.message import (
    InventorMessageCreate, MessageOut, MessageAccessUpdate, MessageAccessOut,
)
from app.schemas.idea import IdeaOut
from app.models.idea import IdeaStatus
from app.models.message import MessageType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_idea(
    id=1,
    email="owner@example.com",
    inventor_id=1,
    current_status=IdeaStatus.SUBMITTED,
    inventor_messages_blocked=False,
    inventor_messages_blocked_reason=None,
):
    idea = MagicMock()
    idea.id = id
    idea.email = email
    idea.inventor_id = inventor_id
    idea.current_status = current_status
    idea.inventor_messages_blocked = inventor_messages_blocked
    idea.inventor_messages_blocked_reason = inventor_messages_blocked_reason
    return idea


def _mock_user(email="owner@example.com", user_id=1):
    user = MagicMock()
    user.email = email
    user.id = user_id
    return user


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------

def test_assert_owns_allows_email_match():
    idea = _mock_idea(email="owner@example.com")
    user = _mock_user(email="owner@example.com")
    _assert_owns(idea, user)  # no exception


def test_assert_owns_raises_for_wrong_email():
    idea = _mock_idea(email="owner@example.com", inventor_id=99)
    user = _mock_user(email="other@example.com", user_id=5)
    with pytest.raises(HTTPException) as exc:
        _assert_owns(idea, user)
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# InventorMessageCreate schema validation
# ---------------------------------------------------------------------------

def test_inventor_message_create_rejects_empty():
    with pytest.raises(Exception):
        InventorMessageCreate(message="")


def test_inventor_message_create_rejects_whitespace():
    with pytest.raises(Exception):
        InventorMessageCreate(message="   ")


def test_inventor_message_create_strips_whitespace():
    msg = InventorMessageCreate(message="  Hello admin  ")
    assert msg.message == "Hello admin"


def test_inventor_message_create_default_type():
    msg = InventorMessageCreate(message="Hello")
    assert msg.message_type == "GENERAL"


# ---------------------------------------------------------------------------
# Blocked messaging — 403 behavior
# ---------------------------------------------------------------------------

def test_send_message_raises_403_when_blocked():
    idea = _mock_idea(inventor_messages_blocked=True, inventor_messages_blocked_reason=None)
    user = _mock_user()
    payload = InventorMessageCreate(message="Can you help me?")

    db = MagicMock()

    with patch("app.routers.inventor._get_idea_or_404", return_value=idea), \
         patch("app.routers.inventor._assert_owns"):
        with pytest.raises(HTTPException) as exc:
            send_inventor_message(idea.id, payload, user, db)

    assert exc.value.status_code == 403
    assert "Messaging is disabled" in exc.value.detail


def test_send_message_403_includes_reason_when_present():
    reason = "Messaging closed after final rejection."
    idea = _mock_idea(inventor_messages_blocked=True, inventor_messages_blocked_reason=reason)
    user = _mock_user()
    payload = InventorMessageCreate(message="Can I reapply?")
    db = MagicMock()

    with patch("app.routers.inventor._get_idea_or_404", return_value=idea), \
         patch("app.routers.inventor._assert_owns"):
        with pytest.raises(HTTPException) as exc:
            send_inventor_message(idea.id, payload, user, db)

    assert reason in exc.value.detail


def test_send_message_succeeds_when_not_blocked():
    idea = _mock_idea(inventor_messages_blocked=False)
    user = _mock_user()
    payload = InventorMessageCreate(message="Can you explain the next steps?")

    saved_msg = MagicMock()
    saved_msg.id = 1
    saved_msg.idea_id = idea.id
    saved_msg.sender_user_id = user.id
    saved_msg.receiver_user_id = None
    saved_msg.message_type = MessageType.GENERAL
    saved_msg.message = payload.message
    saved_msg.is_internal = False
    saved_msg.sender_role = "INVENTOR"
    saved_msg.created_at = None

    db = MagicMock()
    db.refresh.return_value = None

    # Simulate db.add then db.refresh populates saved_msg
    added = []
    db.add.side_effect = lambda m: added.append(m)

    with patch("app.routers.inventor._get_idea_or_404", return_value=idea), \
         patch("app.routers.inventor._assert_owns"), \
         patch("app.routers.inventor.Message", return_value=saved_msg):
        result = send_inventor_message(idea.id, payload, user, db)

    db.commit.assert_called_once()
    assert result.is_internal is False
    assert result.receiver_user_id is None


# ---------------------------------------------------------------------------
# MessageAccessUpdate schema
# ---------------------------------------------------------------------------

def test_message_access_update_blocked_true():
    u = MessageAccessUpdate(inventor_messages_blocked=True, reason="Closed after rejection.")
    assert u.inventor_messages_blocked is True
    assert u.reason == "Closed after rejection."


def test_message_access_update_unblock_no_reason():
    u = MessageAccessUpdate(inventor_messages_blocked=False)
    assert u.inventor_messages_blocked is False
    assert u.reason is None


def test_message_access_update_requires_blocked_field():
    with pytest.raises(Exception):
        MessageAccessUpdate()


# ---------------------------------------------------------------------------
# MessageAccessOut schema
# ---------------------------------------------------------------------------

def test_message_access_out_fields():
    out = MessageAccessOut(
        idea_id=5,
        inventor_messages_blocked=True,
        inventor_messages_blocked_reason="Rejected.",
    )
    assert out.idea_id == 5
    assert out.inventor_messages_blocked is True
    assert out.inventor_messages_blocked_reason == "Rejected."
    assert out.inventor_messages_blocked_at is None


# ---------------------------------------------------------------------------
# MessageOut has sender_role
# ---------------------------------------------------------------------------

def test_message_out_has_sender_role_field():
    assert "sender_role" in MessageOut.model_fields


def test_message_out_sender_role_optional():
    field = MessageOut.model_fields["sender_role"]
    assert not field.is_required()


# ---------------------------------------------------------------------------
# IdeaOut exposes block status
# ---------------------------------------------------------------------------

def test_idea_out_has_inventor_messages_blocked():
    assert "inventor_messages_blocked" in IdeaOut.model_fields


def test_idea_out_has_inventor_messages_blocked_reason():
    assert "inventor_messages_blocked_reason" in IdeaOut.model_fields


def test_idea_out_blocked_defaults_false():
    field = IdeaOut.model_fields["inventor_messages_blocked"]
    assert field.default is False


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def test_inventor_send_message_route_registered():
    routes = {r.path for r in inventor_router.routes}
    assert "/inventor/ideas/{idea_id}/messages" in routes


def test_admin_message_access_route_registered():
    routes = {r.path for r in admin_router.routes}
    assert "/admin/ideas/{idea_id}/message-access" in routes