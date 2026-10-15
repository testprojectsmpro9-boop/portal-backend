"""
Inventor Dashboard APIs.

All endpoints require INVENTOR role.
Inventor can only access ideas linked to their email or inventor_id.

Routes (all under /api/v1/inventor):
  GET  /my-ideas                          list own ideas
  GET  /ideas/{idea_id}                   get single own idea
  GET  /ideas/{idea_id}/timeline          visual pipeline timeline
  GET  /ideas/{idea_id}/files             list own idea's files
  POST /ideas/{idea_id}/upload            upload file for own idea
  GET  /ideas/{idea_id}/messages          list public messages (is_internal=False)
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.models.idea import Idea
from app.models.idea_file import IdeaFile, FileType
from app.models.message import Message, MessageType
from app.models.user import User
from app.schemas.idea import IdeaOut
from app.schemas.file import IdeaFileOut
from app.schemas.message import MessageOut, InventorMessageCreate
from app.schemas.tracking import TimelineItem
from app.services.file_service import validate_file, save_file
from app.services.timeline_service import build_timeline
from app.utils.dependencies import require_inventor

router = APIRouter(prefix="/inventor", tags=["inventor"])

_FILE_TYPE_CHOICES = ", ".join(ft.value for ft in FileType)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _assert_owns(idea: Idea, current_user: User) -> None:
    """Raise 403 if inventor doesn't own this idea."""
    if current_user.email == idea.email or current_user.id == idea.inventor_id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access denied. You can only access your own ideas.",
    )


def _get_idea_or_404(idea_id: int, db: Session) -> Idea:
    idea = db.query(Idea).filter(Idea.id == idea_id).first()
    if not idea:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Idea {idea_id} not found.",
        )
    return idea


def _file_to_out(f: IdeaFile) -> IdeaFileOut:
    return IdeaFileOut(
        id=f.id,
        idea_id=f.idea_id,
        uploaded_by_user_id=f.uploaded_by_user_id,
        file_type=f.file_type.value if f.file_type else "",
        file_name=f.file_name,
        mime_type=f.mime_type,
        file_size=f.file_size,
        description=f.description,
        download_url=f"/api/v1/files/{f.id}",
        created_at=f.created_at,
    )


# ---------------------------------------------------------------------------
# GET /inventor/my-ideas
# ---------------------------------------------------------------------------

@router.get(
    "/my-ideas",
    response_model=List[IdeaOut],
    summary="List all ideas submitted by the logged-in inventor",
)
def list_my_ideas(
    current_user: User = Depends(require_inventor),
    db: Session = Depends(get_db),
):
    ideas = (
        db.query(Idea)
        .filter(
            (Idea.email == current_user.email) | (Idea.inventor_id == current_user.id)
        )
        .order_by(Idea.created_at.desc())
        .all()
    )
    return ideas


# ---------------------------------------------------------------------------
# GET /inventor/ideas/{idea_id}
# ---------------------------------------------------------------------------

@router.get(
    "/ideas/{idea_id}",
    response_model=IdeaOut,
    summary="Get details of a single own idea",
)
def get_my_idea(
    idea_id: int,
    current_user: User = Depends(require_inventor),
    db: Session = Depends(get_db),
):
    idea = _get_idea_or_404(idea_id, db)
    _assert_owns(idea, current_user)
    return idea


# ---------------------------------------------------------------------------
# GET /inventor/ideas/{idea_id}/timeline
# ---------------------------------------------------------------------------

@router.get(
    "/ideas/{idea_id}/timeline",
    response_model=List[TimelineItem],
    summary="Visual pipeline timeline for own idea",
)
def get_my_idea_timeline(
    idea_id: int,
    current_user: User = Depends(require_inventor),
    db: Session = Depends(get_db),
):
    idea = _get_idea_or_404(idea_id, db)
    _assert_owns(idea, current_user)
    return build_timeline(idea)


# ---------------------------------------------------------------------------
# GET /inventor/ideas/{idea_id}/files
# ---------------------------------------------------------------------------

@router.get(
    "/ideas/{idea_id}/files",
    response_model=List[IdeaFileOut],
    summary="List file attachments for own idea",
)
def list_my_idea_files(
    idea_id: int,
    current_user: User = Depends(require_inventor),
    db: Session = Depends(get_db),
):
    idea = _get_idea_or_404(idea_id, db)
    _assert_owns(idea, current_user)
    files = (
        db.query(IdeaFile)
        .filter(IdeaFile.idea_id == idea.id)
        .order_by(IdeaFile.created_at.desc())
        .all()
    )
    return [_file_to_out(f) for f in files]


# ---------------------------------------------------------------------------
# POST /inventor/ideas/{idea_id}/upload
# ---------------------------------------------------------------------------

@router.post(
    "/ideas/{idea_id}/upload",
    response_model=IdeaFileOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file for own idea",
    description=(
        f"Upload a file attachment to your idea. `file_type` must be one of: {_FILE_TYPE_CHOICES}. "
        "Max file size: 50 MB."
    ),
)
def upload_my_idea_file(
    idea_id: int,
    file: UploadFile = File(...),
    file_type: str = Form(..., description=f"One of: {_FILE_TYPE_CHOICES}"),
    description: Optional[str] = Form(None),
    current_user: User = Depends(require_inventor),
    db: Session = Depends(get_db),
):
    try:
        ft = FileType(file_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file_type '{file_type}'. Valid: {[v.value for v in FileType]}",
        )

    idea = _get_idea_or_404(idea_id, db)
    _assert_owns(idea, current_user)

    ext, content = validate_file(file, ft)
    meta = save_file(
        content=content,
        ext=ext,
        file_type=ft,
        application_id=idea.application_id,
        original_name=file.filename or "upload",
        mime_type=file.content_type,
    )

    idea_file = IdeaFile(
        idea_id=idea.id,
        uploaded_by_user_id=current_user.id,
        file_type=ft,
        file_name=meta["file_name"],
        stored_file_name=meta["stored_file_name"],
        file_path=meta["file_path"],
        mime_type=meta["mime_type"],
        file_size=meta["file_size"],
        description=description,
    )
    db.add(idea_file)
    db.commit()
    db.refresh(idea_file)
    return _file_to_out(idea_file)


# ---------------------------------------------------------------------------
# GET /inventor/ideas/{idea_id}/messages
# ---------------------------------------------------------------------------

@router.get(
    "/ideas/{idea_id}/messages",
    response_model=List[MessageOut],
    summary="List public messages for own idea (internal notes hidden)",
    description="Returns only messages where is_internal=False. Internal admin notes are never shown.",
)
def list_my_idea_messages(
    idea_id: int,
    current_user: User = Depends(require_inventor),
    db: Session = Depends(get_db),
):
    idea = _get_idea_or_404(idea_id, db)
    _assert_owns(idea, current_user)
    messages = (
        db.query(Message)
        .filter(Message.idea_id == idea.id, Message.is_internal == False)
        .order_by(Message.created_at.asc())
        .all()
    )
    return messages


# ---------------------------------------------------------------------------
# POST /inventor/ideas/{idea_id}/messages — inventor sends message to admin
# ---------------------------------------------------------------------------

@router.post(
    "/ideas/{idea_id}/messages",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
    summary="Send a message to admin for own idea",
    description=(
        "Inventor sends a text message to admin. "
        "Messages are always public (is_internal=False). "
        "Returns 403 if admin has blocked inventor messaging for this idea."
    ),
)
def send_inventor_message(
    idea_id: int,
    payload: InventorMessageCreate,
    current_user: User = Depends(require_inventor),
    db: Session = Depends(get_db),
):
    idea = _get_idea_or_404(idea_id, db)
    _assert_owns(idea, current_user)

    if idea.inventor_messages_blocked:
        reason = idea.inventor_messages_blocked_reason or ""
        detail = "Messaging is disabled for this application."
        if reason.strip():
            detail = f"{detail} Reason: {reason.strip()}"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )

    try:
        msg_type = MessageType(payload.message_type)
    except ValueError:
        msg_type = MessageType.GENERAL

    msg = Message(
        idea_id=idea.id,
        sender_user_id=current_user.id,
        receiver_user_id=None,
        message_type=msg_type,
        message=payload.message,
        is_internal=False,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg
