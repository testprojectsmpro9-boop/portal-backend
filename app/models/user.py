import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum as SAEnum
from app.database import Base


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    TEAM_ADMIN_GLOBAL = "TEAM_ADMIN_GLOBAL"
    TEAM_ADMIN_LOCAL = "TEAM_ADMIN_LOCAL"
    JURY = "JURY"
    INVENTOR = "INVENTOR"
    # Read-only admin roles (added migration 0024) — see app/utils/dependencies.py
    # for the FULL_ADMIN / VIEW_ADMIN / ADMIN_READ / ADMIN_WRITE role groupings.
    VIEW_ADMIN_LOCAL = "VIEW_ADMIN_LOCAL"
    VIEW_ADMIN_GLOBAL = "VIEW_ADMIN_GLOBAL"
    VIEW_ADMIN_BOTH = "VIEW_ADMIN_BOTH"


class ProgramTrack(str, enum.Enum):
    NATIONAL_INTERNATIONAL = "NATIONAL_INTERNATIONAL"
    LOCAL_REGIONAL = "LOCAL_REGIONAL"
    K12 = "K12"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    phone = Column(String(20), nullable=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.INVENTOR)
    program_track = Column(SAEnum(ProgramTrack), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    must_change_password = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
