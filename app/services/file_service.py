import os
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.config import settings
from app.models.idea_file import FileType


MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

ALLOWED_EXTENSIONS: dict = {
    FileType.DOCUMENT: ["pdf", "doc", "docx"],
    FileType.OFFLINE_FORM: ["pdf", "doc", "docx"],
    FileType.LETTER_SCAN: ["pdf", "jpg", "jpeg", "png"],
    FileType.AUDIO: ["mp3", "wav", "m4a"],
    FileType.VIDEO: ["mp4", "mov", "webm"],
    FileType.PROTOTYPE_PHOTO: ["jpg", "jpeg", "png", "webp"],
    FileType.DESIGN_SKETCH: ["jpg", "jpeg", "png", "webp"],
    FileType.OTHER: [
        "pdf", "doc", "docx", "jpg", "jpeg", "png", "webp",
        "mp3", "wav", "m4a", "mp4", "mov", "webm",
    ],
}

FOLDER_MAP: dict = {
    FileType.DOCUMENT: "documents",
    FileType.OFFLINE_FORM: "documents",
    FileType.LETTER_SCAN: "documents",
    FileType.AUDIO: "audio",
    FileType.VIDEO: "video",
    FileType.PROTOTYPE_PHOTO: "photos",
    FileType.DESIGN_SKETCH: "sketches",
    FileType.OTHER: "others",
}


def validate_file(upload: UploadFile, file_type: FileType) -> tuple[str, bytes]:
    """
    Validate file extension and size.
    Returns (extension, content_bytes) on success.
    Raises HTTPException 400 on failure.
    """
    original_name = upload.filename or "upload"
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""

    allowed = ALLOWED_EXTENSIONS.get(file_type, [])
    if not ext or ext not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Extension '.{ext}' not allowed for file_type={file_type.value}. "
                f"Allowed extensions: {allowed}"
            ),
        )

    content = upload.file.read()
    if len(content) > MAX_FILE_SIZE:
        max_mb = MAX_FILE_SIZE // (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum allowed size: {max_mb}MB.",
        )

    return ext, content


def save_file(
    content: bytes,
    ext: str,
    file_type: FileType,
    application_id: str,
    original_name: str,
    mime_type: str | None,
) -> dict:
    """
    Save content bytes to disk under uploads/ideas/{application_id}/{subfolder}/.
    Returns metadata dict for DB insertion.
    """
    subfolder = FOLDER_MAP[file_type]
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    safe_original_name = Path(original_name or "upload").name or "upload"
    upload_root = Path(settings.UPLOAD_DIR).resolve()

    rel_dir = os.path.join("ideas", application_id, subfolder)
    abs_dir = (upload_root / rel_dir).resolve()
    if not _is_relative_to(abs_dir, upload_root):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid storage path.",
        )
    abs_dir.mkdir(parents=True, exist_ok=True)

    target_path = (abs_dir / stored_name).resolve()
    if not _is_relative_to(target_path, upload_root):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid storage path.",
        )
    target_path.write_bytes(content)

    return {
        "file_name": safe_original_name,
        "stored_file_name": stored_name,
        "file_path": (Path(rel_dir) / stored_name).as_posix(),
        "mime_type": mime_type,
        "file_size": len(content),
    }


def save_intake_file(
    content: bytes,
    ext: str,
    file_type: FileType,
    intake_id: str,
    original_name: str,
    mime_type: str | None,
) -> dict:
    """
    Save content bytes to disk under uploads/intake/{intake_id}/{subfolder}/.
    Returns metadata dict for DB insertion.
    """
    subfolder = FOLDER_MAP[file_type]
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    safe_original_name = Path(original_name or "upload").name or "upload"
    upload_root = Path(settings.UPLOAD_DIR).resolve()

    rel_dir = os.path.join("intake", intake_id, subfolder)
    abs_dir = (upload_root / rel_dir).resolve()
    if not _is_relative_to(abs_dir, upload_root):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid storage path.",
        )
    abs_dir.mkdir(parents=True, exist_ok=True)

    target_path = (abs_dir / stored_name).resolve()
    if not _is_relative_to(target_path, upload_root):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid storage path.",
        )
    target_path.write_bytes(content)

    return {
        "file_name": safe_original_name,
        "stored_file_name": stored_name,
        "file_path": (Path(rel_dir) / stored_name).as_posix(),
        "mime_type": mime_type,
        "file_size": len(content),
    }


def resolve_abs_path(rel_file_path: str) -> Path:
    """Reconstruct absolute disk path from the relative path stored in DB."""
    upload_root = Path(settings.UPLOAD_DIR).resolve()
    target_path = (upload_root / rel_file_path).resolve()
    if not _is_relative_to(target_path, upload_root):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file path.",
        )
    return target_path


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
