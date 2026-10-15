from pydantic import BaseModel, EmailStr
from typing import Dict, Optional
from datetime import datetime


class UserBase(BaseModel):
    full_name: str
    email: EmailStr
    phone: Optional[str] = None
    role: str = "INVENTOR"
    program_track: Optional[str] = None


class UserCreate(UserBase):
    password: str


class UserOut(UserBase):
    id: int
    is_active: bool
    must_change_password: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminUserCreate(BaseModel):
    full_name: str
    email: EmailStr
    phone: Optional[str] = None
    password: str
    role: str
    program_track: Optional[str] = None
    is_active: bool = True


class AdminUserStatusUpdate(BaseModel):
    is_active: bool


class AdminUserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    program_track: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None
    must_change_password: Optional[bool] = None


class AdminUserRead(BaseModel):
    id: int
    full_name: str
    email: str
    phone: Optional[str] = None
    role: str
    program_track: Optional[str] = None
    is_active: bool
    must_change_password: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminUserSummaryResponse(BaseModel):
    total_users: int
    active_users: int
    inactive_users: int
    by_role: Dict[str, int]
    by_program_track: Dict[str, int]
    scoped_role_counts: Dict[str, Dict[str, int]]
