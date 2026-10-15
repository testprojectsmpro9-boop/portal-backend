from pydantic import BaseModel, field_validator
from typing import Optional, List
from datetime import datetime


class JuryProfileCreate(BaseModel):
    user_id: int
    expertise_field: Optional[str] = None
    sub_field: Optional[str] = None
    qualification: Optional[str] = None
    organization: Optional[str] = None
    experience_years: Optional[int] = None
    max_review_capacity: int = 10
    is_available: bool = True


class JuryProfileUpdate(BaseModel):
    expertise_field: Optional[str] = None
    sub_field: Optional[str] = None
    qualification: Optional[str] = None
    organization: Optional[str] = None
    experience_years: Optional[int] = None
    max_review_capacity: Optional[int] = None
    is_available: Optional[bool] = None


class JuryProfileOut(BaseModel):
    id: int
    user_id: int
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    program_track: Optional[str] = None
    is_active: Optional[bool] = None
    expertise_field: Optional[str] = None
    sub_field: Optional[str] = None
    qualification: Optional[str] = None
    organization: Optional[str] = None
    experience_years: Optional[int] = None
    max_review_capacity: int
    is_available: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AssignJuryRequest(BaseModel):
    jury_user_ids: List[int]
    due_date: Optional[datetime] = None

    @field_validator("jury_user_ids")
    @classmethod
    def validate_jury_count(cls, v: List[int]) -> List[int]:
        if len(v) < 1:
            raise ValueError("At least 1 jury member must be assigned.")
        if len(v) > 3:
            raise ValueError("Maximum 3 jury members can be assigned to one idea.")
        return v


class JuryAssignmentOut(BaseModel):
    id: int
    idea_id: int
    jury_user_id: int
    assigned_by_user_id: int
    review_status: str
    assigned_at: datetime
    due_date: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class JuryAssignmentStatusUpdate(BaseModel):
    status: str
    note: Optional[str] = None
