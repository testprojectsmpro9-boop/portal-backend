from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


class PublicInquiryCreate(BaseModel):
    inquiry_type: str
    full_name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    organization: Optional[str] = None
    interest_area: Optional[str] = None
    message: str
    source_page: Optional[str] = None
    program_track: Optional[str] = None
    visibility_scope: Optional[str] = None
    source_program: Optional[str] = None


class PublicInquiryStatusUpdate(BaseModel):
    status: str


class PublicInquiryAssignmentUpdate(BaseModel):
    assigned_team_user_id: Optional[int] = None


class PublicInquiryOut(BaseModel):
    id: int
    inquiry_type: str
    full_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    organization: Optional[str] = None
    interest_area: Optional[str] = None
    message: str
    status: str
    source_page: Optional[str] = None
    program_track: Optional[str] = None
    visibility_scope: Optional[str] = None
    source_program: Optional[str] = None
    assigned_team_user_id: Optional[int] = None
    assigned_team_user_name: Optional[str] = None
    assigned_team_user_email: Optional[str] = None
    assigned_team_user_role: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
