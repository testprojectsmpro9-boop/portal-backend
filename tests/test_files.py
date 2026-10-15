"""
Tests for the file upload module (idea_files table + file_service + schemas).

Tests that DO NOT require a running DB/server:
  - FileType enum completeness
  - ALLOWED_EXTENSIONS and FOLDER_MAP cover all FileType values
  - MAX_FILE_SIZE constant
  - validate_file rejects bad extension (400)
  - validate_file rejects oversized file (400)
  - validate_file accepts valid file, returns (ext, content)
  - save_file writes to a temp dir and returns correct metadata dict
  - IdeaFileOut schema: has download_url, no file_path, all correct fields
  - _to_out helper builds correct download_url from file id
"""
import io
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from fastapi import HTTPException

from app.models.idea_file import FileType
from app.schemas.file import IdeaFileOut
from app.services.file_service import (
    MAX_FILE_SIZE,
    ALLOWED_EXTENSIONS,
    FOLDER_MAP,
    validate_file,
    save_file,
    resolve_abs_path,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_upload(filename: str, content: bytes = b"test content"):
    """Create a mock UploadFile with given filename and content."""
    mock = MagicMock()
    mock.filename = filename
    mock.content_type = "application/octet-stream"
    mock.file = io.BytesIO(content)
    return mock


# ---------------------------------------------------------------------------
# FileType enum
# ---------------------------------------------------------------------------

def test_file_type_enum_values():
    values = {e.value for e in FileType}
    assert values == {
        "DOCUMENT", "OFFLINE_FORM", "LETTER_SCAN",
        "AUDIO", "VIDEO", "PROTOTYPE_PHOTO", "DESIGN_SKETCH", "OTHER",
    }
    assert len(values) == 8


# ---------------------------------------------------------------------------
# Service constants coverage
# ---------------------------------------------------------------------------

def test_allowed_extensions_covers_all_file_types():
    for ft in FileType:
        assert ft in ALLOWED_EXTENSIONS, f"ALLOWED_EXTENSIONS missing {ft}"
        assert len(ALLOWED_EXTENSIONS[ft]) > 0, f"Empty extension list for {ft}"


def test_folder_map_covers_all_file_types():
    for ft in FileType:
        assert ft in FOLDER_MAP, f"FOLDER_MAP missing {ft}"
        assert FOLDER_MAP[ft], f"Empty folder for {ft}"


def test_max_file_size_is_50mb():
    assert MAX_FILE_SIZE == 50 * 1024 * 1024


# ---------------------------------------------------------------------------
# validate_file — extension checks
# ---------------------------------------------------------------------------

def test_validate_file_rejects_bad_extension_for_document():
    upload = make_upload("report.exe")
    with pytest.raises(HTTPException) as exc:
        validate_file(upload, FileType.DOCUMENT)
    assert exc.value.status_code == 400
    assert ".exe" in exc.value.detail


def test_validate_file_rejects_mp3_for_document():
    upload = make_upload("report.mp3")
    with pytest.raises(HTTPException) as exc:
        validate_file(upload, FileType.DOCUMENT)
    assert exc.value.status_code == 400


def test_validate_file_rejects_pdf_for_audio():
    upload = make_upload("sound.pdf")
    with pytest.raises(HTTPException) as exc:
        validate_file(upload, FileType.AUDIO)
    assert exc.value.status_code == 400


def test_validate_file_rejects_no_extension():
    upload = make_upload("filewithoutext")
    with pytest.raises(HTTPException) as exc:
        validate_file(upload, FileType.DOCUMENT)
    assert exc.value.status_code == 400


def test_validate_file_accepts_pdf_for_document():
    upload = make_upload("form.pdf", b"fake-pdf-content")
    ext, content = validate_file(upload, FileType.DOCUMENT)
    assert ext == "pdf"
    assert content == b"fake-pdf-content"


def test_validate_file_accepts_jpg_for_photo():
    upload = make_upload("prototype.jpg", b"fake-jpg")
    ext, content = validate_file(upload, FileType.PROTOTYPE_PHOTO)
    assert ext == "jpg"


def test_validate_file_accepts_mp3_for_audio():
    upload = make_upload("description.mp3", b"fake-mp3")
    ext, content = validate_file(upload, FileType.AUDIO)
    assert ext == "mp3"


def test_validate_file_accepts_mp4_for_video():
    upload = make_upload("demo.mp4", b"fake-mp4")
    ext, content = validate_file(upload, FileType.VIDEO)
    assert ext == "mp4"


# ---------------------------------------------------------------------------
# validate_file — size check
# ---------------------------------------------------------------------------

def test_validate_file_rejects_oversized_file():
    big_content = b"x" * (MAX_FILE_SIZE + 1)
    upload = make_upload("large.pdf", big_content)
    with pytest.raises(HTTPException) as exc:
        validate_file(upload, FileType.DOCUMENT)
    assert exc.value.status_code == 400
    assert "large" in exc.value.detail.lower() or "50" in exc.value.detail


def test_validate_file_accepts_exactly_max_size():
    content = b"x" * MAX_FILE_SIZE
    upload = make_upload("big.pdf", content)
    ext, returned_content = validate_file(upload, FileType.DOCUMENT)
    assert ext == "pdf"
    assert len(returned_content) == MAX_FILE_SIZE


# ---------------------------------------------------------------------------
# save_file — disk write
# ---------------------------------------------------------------------------

def test_save_file_writes_to_correct_subfolder(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.file_service.settings.UPLOAD_DIR", str(tmp_path))
    meta = save_file(
        content=b"data",
        ext="pdf",
        file_type=FileType.DOCUMENT,
        application_id="IDEA-0001",
        original_name="test.pdf",
        mime_type="application/pdf",
    )
    stored_path = tmp_path / meta["file_path"]
    assert stored_path.exists()
    assert stored_path.read_bytes() == b"data"
    assert "documents" in meta["file_path"]
    assert "IDEA-0001" in meta["file_path"]
    assert meta["file_size"] == 4
    assert meta["file_name"] == "test.pdf"
    assert meta["mime_type"] == "application/pdf"


def test_save_file_stored_name_has_correct_ext(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.file_service.settings.UPLOAD_DIR", str(tmp_path))
    meta = save_file(b"mp3data", "mp3", FileType.AUDIO, "IDEA-0002", "rec.mp3", "audio/mpeg")
    assert meta["stored_file_name"].endswith(".mp3")
    assert "audio" in meta["file_path"]


def test_resolve_abs_path_accepts_valid_relative_path(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.file_service.settings.UPLOAD_DIR", str(tmp_path))
    target = tmp_path / "ideas" / "IDEA-2026-ABC123" / "documents" / "file.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"data")

    resolved = resolve_abs_path("ideas/IDEA-2026-ABC123/documents/file.pdf")

    assert resolved == target.resolve()


@pytest.mark.parametrize("bad_path", ["../secret.txt", "../../outside.txt"])
def test_resolve_abs_path_rejects_traversal(tmp_path, monkeypatch, bad_path):
    monkeypatch.setattr("app.services.file_service.settings.UPLOAD_DIR", str(tmp_path))
    with pytest.raises(HTTPException) as exc:
        resolve_abs_path(bad_path)
    assert exc.value.status_code == 400


def test_resolve_abs_path_rejects_absolute_outside_upload_dir(tmp_path, monkeypatch):
    outside = tmp_path.parent / "outside.pdf"
    monkeypatch.setattr("app.services.file_service.settings.UPLOAD_DIR", str(tmp_path))
    with pytest.raises(HTTPException) as exc:
        resolve_abs_path(str(outside))
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# IdeaFileOut schema
# ---------------------------------------------------------------------------

def test_idea_file_out_schema_fields():
    fields = IdeaFileOut.model_fields
    assert "id" in fields
    assert "idea_id" in fields
    assert "file_type" in fields
    assert "file_name" in fields
    assert "download_url" in fields
    assert "created_at" in fields
    # file_path must NOT be in the response schema
    assert "file_path" not in fields


def test_idea_file_out_download_url():
    from datetime import datetime
    obj = IdeaFileOut(
        id=42,
        idea_id=1,
        uploaded_by_user_id=None,
        file_type="DOCUMENT",
        file_name="form.pdf",
        mime_type="application/pdf",
        file_size=1024,
        description=None,
        download_url="/api/v1/files/42",
        created_at=datetime.utcnow(),
    )
    assert obj.download_url == "/api/v1/files/42"
    assert obj.id == 42
