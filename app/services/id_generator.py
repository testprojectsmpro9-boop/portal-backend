import secrets
import string
from datetime import datetime
from typing import Type

from fastapi import HTTPException, status
from sqlalchemy.orm import Session


ALPHABET = string.ascii_uppercase + string.digits
DEFAULT_SUFFIX_LENGTH = 6
DEFAULT_MAX_ATTEMPTS = 10


def _random_suffix(length: int = DEFAULT_SUFFIX_LENGTH) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def generate_unique_year_id(
    db: Session,
    model: Type,
    column_name: str,
    prefix: str,
    suffix_length: int = DEFAULT_SUFFIX_LENGTH,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> str:
    clean_prefix = (prefix or "").strip().upper() or "ID"
    year = datetime.utcnow().year
    column = getattr(model, column_name)

    for _ in range(max_attempts):
        candidate = f"{clean_prefix}-{year}-{_random_suffix(suffix_length)}"
        exists = db.query(model).filter(column == candidate).first()
        if not exists:
            return candidate

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Could not generate a unique reference ID. Please try again.",
    )
