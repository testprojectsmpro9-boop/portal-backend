from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class IdeaFileOut(BaseModel):
    id: int
    idea_id: int
    uploaded_by_user_id: Optional[int] = None
    file_type: str
    file_name: str
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    description: Optional[str] = None
    # file_path intentionally excluded — never expose raw server paths publicly
    # clients access files via download_url only
    download_url: str
    created_at: datetime

    model_config = {"from_attributes": False}


class IntakeFileOut(BaseModel):
    id: int
    intake_id: str
    intake_submission_id: int
    uploaded_by_user_id: Optional[int] = None
    file_type: str
    file_name: str
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    description: Optional[str] = None
    download_url: str
    created_at: datetime

    model_config = {"from_attributes": False}


class FileAccessLogRead(BaseModel):
    id: int
    file_id: int
    idea_id: int
    application_id: str
    user_id: int
    user_email: Optional[str] = None
    user_role: Optional[str] = None
    action: str
    original_filename: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
