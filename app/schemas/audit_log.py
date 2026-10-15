from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class AuditLogRead(BaseModel):
    id: int
    actor_user_id: Optional[int] = None
    actor_role: Optional[str] = None
    action: str
    entity_type: str
    entity_id: Optional[str] = None
    entity_display_id: Optional[str] = None
    old_values: Optional[dict[str, Any]] = None
    new_values: Optional[dict[str, Any]] = None
    ip_address: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
