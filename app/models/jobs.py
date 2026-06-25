from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.models.schemas import LanguageCode


class JobStatus(StrEnum):
    QUEUED = "queued"
    PARSING = "parsing"
    EXTRACTING_LAYOUT = "extracting_layout"
    EXTRACTING_TEXT = "extracting_text"
    ESTIMATING = "estimating"
    TRANSLATING = "translating"
    BUILDING = "building"
    REBUILDING_PDF = "rebuilding_pdf"
    COMPLETED = "completed"
    FAILED = "failed"


class TranslationJob(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.QUEUED
    progress: int = Field(default=0, ge=0, le=100)
    source_lang: LanguageCode
    target_lang: LanguageCode
    original_filename: str
    upload_path: str
    file_type: Literal["docx", "pdf", "pdf_layout"] = "docx"
    result_file: str | None = None
    error: str | None = None
    created_at: str = Field(default_factory=lambda: _now_iso())
    updated_at: str = Field(default_factory=lambda: _now_iso())


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
