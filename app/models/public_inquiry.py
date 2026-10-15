import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class PublicInquiryType(str, enum.Enum):
    CONTACT = "CONTACT"
    COLLABORATION = "COLLABORATION"
    MEMBERSHIP = "MEMBERSHIP"
    REGISTER_INTEREST = "REGISTER_INTEREST"
    SCHOOL_PARTNERSHIP = "SCHOOL_PARTNERSHIP"
    OTHER = "OTHER"


class PublicInquiry(Base):
    __tablename__ = "public_inquiries"

    id = Column(Integer, primary_key=True, index=True)
    inquiry_type = Column(SAEnum(PublicInquiryType), nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True, index=True)
    phone = Column(String(20), nullable=True)
    organization = Column(String(255), nullable=True)
    interest_area = Column(String(255), nullable=True)
    message = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, default="NEW", index=True)
    source_page = Column(String(255), nullable=True)
    program_track = Column(String(50), nullable=True, index=True)
    visibility_scope = Column(String(50), nullable=True, index=True)
    source_program = Column(String(50), nullable=True, index=True)
    assigned_team_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    assigned_team_user = relationship("User", foreign_keys=[assigned_team_user_id])

    @property
    def assigned_team_user_name(self):
        return self.assigned_team_user.full_name if self.assigned_team_user else None

    @property
    def assigned_team_user_email(self):
        return self.assigned_team_user.email if self.assigned_team_user else None

    @property
    def assigned_team_user_role(self):
        return self.assigned_team_user.role.value if self.assigned_team_user and self.assigned_team_user.role else None
