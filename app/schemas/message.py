from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime


class MessageCreate(BaseModel):
    message: str
    message_type: str = "GENERAL"
    receiver_user_id: Optional[int] = None
    is_internal: bool = False


class InventorMessageCreate(BaseModel):
    """Restricted message create for inventor — is_internal always False, receiver always None."""
    message: str
    message_type: str = "GENERAL"

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Message cannot be empty.")
        return v.strip()


class MessageOut(BaseModel):
    id: int
    idea_id: int
    sender_user_id: Optional[int] = None
    receiver_user_id: Optional[int] = None
    message_type: str
    message: str
    is_internal: bool
    sender_role: Optional[str] = None  # "INVENTOR", "SUPER_ADMIN", "TEAM_ADMIN_GLOBAL", etc.
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageAccessUpdate(BaseModel):
    inventor_messages_blocked: bool
    reason: Optional[str] = None


class MessageAccessOut(BaseModel):
    idea_id: int
    inventor_messages_blocked: bool
    inventor_messages_blocked_reason: Optional[str] = None
    inventor_messages_blocked_at: Optional[datetime] = None
    inventor_messages_blocked_by_user_id: Optional[int] = None

    model_config = {"from_attributes": True}