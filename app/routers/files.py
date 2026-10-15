"""
File upload, list, and download endpoints.

Routes mounted in main.py:
  idea_files_router → prefix /api/v1/ideas   (handles /{idea_id}/files)
  files_router      → prefix /api/v1/files   (handles /{file_id} download)
"""
import mimetypes
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, status
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.models.idea import Idea, IdeaVisibilityScope
from app.models.idea_file import IdeaFile, FileType
from app.models.user import User, UserRole, ProgramTrack
from app.schemas.file import IdeaFileOut
from app.services.file_service import validate_file, save_file, resolve_abs_path
from app.services.audit_log_service import record_audit_log
from app.services.file_access_log_service import record_file_access_log
from app.utils.dependencies import get_current_user

idea_files_router = APIRouter(prefix="/ideas", tags=["files"])
files_router = APIRouter(prefix="/files", tags=["files"])

_FILE_TYPE_CHOICES = ", ".join(ft.value for ft in FileType)
_INLINE_PREVIEW_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "text/plain",
}
_INLINE_PREVIEW_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "webp", "txt"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_idea_or_404(idea_id: int, db: Session) -> Idea:
    idea = db.query(Idea).filter(Idea.id == idea_id).first()
    if not idea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Idea {idea_id} not found")
    return idea


def _scope_filter(query, current_user: User):
    """
    Apply admin team scope filter — mirrors logic in admin router.
    TEAM_ADMIN_GLOBAL: program_track=NATIONAL_INTERNATIONAL OR visibility in (GLOBAL_TEAM, ALL_TEAMS)
    TEAM_ADMIN_LOCAL : program_track in LOCAL_REGIONAL/K12 OR visibility in (LOCAL_TEAM, K12_TEAM, ALL_TEAMS)
    """
    if current_user.role in (UserRole.TEAM_ADMIN_GLOBAL, UserRole.VIEW_ADMIN_GLOBAL):
        return query.filter(
            or_(
                Idea.program_track == ProgramTrack.NATIONAL_INTERNATIONAL,
                Idea.visibility_scope.in_([IdeaVisibilityScope.GLOBAL_TEAM, IdeaVisibilityScope.ALL_TEAMS]),
            )
        )
    if current_user.role in (UserRole.TEAM_ADMIN_LOCAL, UserRole.VIEW_ADMIN_LOCAL):
        return query.filter(
            or_(
                Idea.program_track.in_([ProgramTrack.LOCAL_REGIONAL, ProgramTrack.K12]),
                Idea.visibility_scope.in_([
                    IdeaVisibilityScope.LOCAL_TEAM,
                    IdeaVisibilityScope.K12_TEAM,
                    IdeaVisibilityScope.ALL_TEAMS,
                ]),
            )
        )
    return query.filter(False)


def _assert_idea_access(idea: Idea, current_user: User, db: Session) -> None:
    """
    Raise 403 if current_user has no access to this idea's files.

    SUPER_ADMIN         → all ideas
    TEAM_ADMIN_GLOBAL   → ideas in global scope
    TEAM_ADMIN_LOCAL    → ideas in local/K12 scope
    INVENTOR            → own idea (email match or inventor_id link)
    JURY                → TODO: needs jury_assignments table (blocked for now)
    """
    role = current_user.role

    if role in (UserRole.SUPER_ADMIN, UserRole.VIEW_ADMIN_BOTH):
        return

    if role in (
        UserRole.TEAM_ADMIN_GLOBAL,
        UserRole.TEAM_ADMIN_LOCAL,
        UserRole.VIEW_ADMIN_GLOBAL,
        UserRole.VIEW_ADMIN_LOCAL,
    ):
        scoped = _scope_filter(db.query(Idea).filter(Idea.id == idea.id), current_user).first()
        if not scoped:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. Idea is outside your program track scope.",
            )
        return

    if role == UserRole.INVENTOR:
        if current_user.email == idea.email or current_user.id == idea.inventor_id:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. You can only access files for your own idea.",
        )

    if role == UserRole.JURY:
        from app.models.jury import JuryAssignment, ReviewStatus
        _inactive = (ReviewStatus.CANCELLED, ReviewStatus.REASSIGNED)
        assignment = db.query(JuryAssignment).filter(
            JuryAssignment.idea_id == idea.id,
            JuryAssignment.jury_user_id == current_user.id,
            JuryAssignment.review_status.notin_(_inactive),
        ).first()
        if not assignment:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not assigned to review this idea's files.",
            )
        return

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


def _to_out(f: IdeaFile) -> IdeaFileOut:
    """Convert DB IdeaFile → IdeaFileOut (excludes raw file_path, adds safe download_url)."""
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


def _media_type_for(file_record: IdeaFile) -> str:
    guessed, _ = mimetypes.guess_type(file_record.file_name or file_record.file_path or "")
    return file_record.mime_type or guessed or "application/octet-stream"


def _is_inline_preview_supported(file_record: IdeaFile) -> bool:
    media_type = _media_type_for(file_record).split(";", 1)[0].lower()
    ext_source = file_record.file_name or file_record.file_path or ""
    ext = ext_source.rsplit(".", 1)[-1].lower() if "." in ext_source else ""
    return media_type in _INLINE_PREVIEW_MIME_TYPES or ext in _INLINE_PREVIEW_EXTENSIONS


def _get_accessible_file_or_404(
    file_id: int,
    current_user: User,
    db: Session,
) -> tuple[IdeaFile, Idea, Path]:
    file_record = db.query(IdeaFile).filter(IdeaFile.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    idea = _get_idea_or_404(file_record.idea_id, db)
    _assert_idea_access(idea, current_user, db)

    abs_path = resolve_abs_path(file_record.file_path)
    if not abs_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File record exists but content is missing from storage.",
        )
    return file_record, idea, abs_path


# ---------------------------------------------------------------------------
# Upload
# POST /api/v1/ideas/{idea_id}/files
# ---------------------------------------------------------------------------

@idea_files_router.post(
    "/{idea_id}/files",
    response_model=IdeaFileOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file attachment to an idea",
    description=(
        f"Upload a file linked to an idea. `file_type` must be one of: {_FILE_TYPE_CHOICES}. "
        "Max file size: 50 MB. Allowed extensions depend on file_type (see service constants)."
    ),
)
def upload_file(
    idea_id: int,
    request: Request,
    file: UploadFile = File(..., description="File to upload"),
    file_type: str = Form(..., description=f"One of: {_FILE_TYPE_CHOICES}"),
    description: Optional[str] = Form(None, description="Optional description of this attachment"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Validate file_type enum
    try:
        ft = FileType(file_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file_type '{file_type}'. Valid: {[v.value for v in FileType]}",
        )

    if current_user.role in (
        UserRole.VIEW_ADMIN_LOCAL,
        UserRole.VIEW_ADMIN_GLOBAL,
        UserRole.VIEW_ADMIN_BOTH,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="View-only admin accounts cannot upload files.",
        )

    idea = _get_idea_or_404(idea_id, db)
    _assert_idea_access(idea, current_user, db)

    # Validate extension + read content (raises 400 on failure)
    ext, content = validate_file(file, ft)

    # Write to disk
    meta = save_file(
        content=content,
        ext=ext,
        file_type=ft,
        application_id=idea.application_id,
        original_name=file.filename or "upload",
        mime_type=file.content_type,
    )

    # Persist metadata
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
    db.flush()
    record_audit_log(
        db,
        actor=current_user,
        action="idea_file_uploaded",
        entity_type="idea_file",
        entity_id=idea_file.id,
        entity_display_id=idea.application_id,
        new_values={
            "idea_id": idea.id,
            "file_name": idea_file.file_name,
            "file_type": idea_file.file_type.value if idea_file.file_type else None,
            "mime_type": idea_file.mime_type,
            "file_size": idea_file.file_size,
            "description": idea_file.description,
        },
        request=request,
    )
    db.commit()
    db.refresh(idea_file)

    return _to_out(idea_file)


# ---------------------------------------------------------------------------
# List files for an idea
# GET /api/v1/ideas/{idea_id}/files
# ---------------------------------------------------------------------------

@idea_files_router.get(
    "/{idea_id}/files",
    response_model=List[IdeaFileOut],
    summary="List all file attachments for an idea",
)
def list_files(
    idea_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    idea = _get_idea_or_404(idea_id, db)
    _assert_idea_access(idea, current_user, db)

    files = (
        db.query(IdeaFile)
        .filter(IdeaFile.idea_id == idea.id)
        .order_by(IdeaFile.created_at.desc())
        .all()
    )
    return [_to_out(f) for f in files]


# ---------------------------------------------------------------------------
# Download / view a file
# GET /api/v1/files/{file_id}
# ---------------------------------------------------------------------------

@files_router.get(
    "/{file_id}",
    summary="Download or view a file attachment",
    description="Returns the raw file. Requires authentication and scope access to the linked idea.",
)
def download_file(
    file_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    file_record, idea, abs_path = _get_accessible_file_or_404(file_id, current_user, db)
    record_file_access_log(
        db,
        file_record=file_record,
        idea=idea,
        user=current_user,
        action="DOWNLOAD",
        request=request,
    )
    db.commit()

    return FileResponse(
        path=str(abs_path),
        filename=file_record.file_name,
        media_type=_media_type_for(file_record),
        content_disposition_type="attachment",
    )


@files_router.get(
    "/{file_id}/view",
    summary="Preview a file attachment inline when supported",
    description="Returns the raw file with inline disposition for PDF, image, and text files when safe.",
)
def view_file(
    file_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    file_record, idea, abs_path = _get_accessible_file_or_404(file_id, current_user, db)
    record_file_access_log(
        db,
        file_record=file_record,
        idea=idea,
        user=current_user,
        action="VIEW",
        request=request,
    )
    db.commit()

    return FileResponse(
        path=str(abs_path),
        filename=file_record.file_name,
        media_type=_media_type_for(file_record),
        content_disposition_type="inline" if _is_inline_preview_supported(file_record) else "attachment",
    )
