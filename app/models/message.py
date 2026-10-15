import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import relationship
from app.database import Base


class MessageType(str, enum.Enum):
    STATUS_UPDATE = "STATUS_UPDATE"
    REQUEST_INFO = "REQUEST_INFO"
    RESPONSE = "RESPONSE"
    GENERAL = "GENERAL"
    CONGRATULATIONS = "CONGRATULATIONS"


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    idea_id = Column(Integer, ForeignKey("ideas.id"), nullable=False, index=True)
    sender_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    receiver_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    message_type = Column(
        postgresql.ENUM(MessageType, name="messagetype", create_type=False),
        nullable=False,
        default=MessageType.GENERAL,
    )
    message = Column(Text, nullable=False)
    is_internal = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    idea = relationship("Idea", foreign_keys=[idea_id])
    sender = relationship("User", foreign_keys=[sender_user_id])
    receiver = relationship("User", foreign_keys=[receiver_user_id])

    @property
    def sender_role(self):
        """Role string of the sender user, or None if sender unknown."""
        if self.sender and self.sender.role:
            r = self.sender.role
            return r.value if hasattr(r, "value") else str(r)
        return None
