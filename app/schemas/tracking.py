from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class PublicTrackRequest(BaseModel):
    application_id: str
    phone_or_email: str


class TimelineItem(BaseModel):
    stage: str
    label: str
    status: str  # "completed" | "current" | "upcoming"


class PublicTrackResponse(BaseModel):
    application_id: str
    idea_title: str
    current_status: str
    current_stage: Optional[str] = None
    current_pathway_stage: Optional[str] = None
    next_action: Optional[str] = None
    admin_message: Optional[str] = None
    created_at: datetime
    timeline: List[TimelineItem]
