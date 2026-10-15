from typing import Callable, TypeVar

T = TypeVar("T")


def paginate_query(query, limit: int, offset: int, transform: Callable[[T], object] | None = None) -> dict:
    total = query.count()
    rows = query.offset(offset).limit(limit).all()
    items = [transform(row) for row in rows] if transform else rows
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
