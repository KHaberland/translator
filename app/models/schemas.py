from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class LanguageCode(StrEnum):
    RU = "ru"
    EN = "en"
    LV = "lv"
    LT = "lt"
    ET = "et"


LANGUAGE_NAMES: dict[LanguageCode, str] = {
    LanguageCode.RU: "Russian",
    LanguageCode.EN: "English",
    LanguageCode.LV: "Latvian",
    LanguageCode.LT: "Lithuanian",
    LanguageCode.ET: "Estonian",
}


class DocumentBlock(BaseModel):
    block_id: str
    text: str
    location: str
    translatable: bool = True
    reason: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class TranslateResponse(BaseModel):
    status: str
    file_name: str
    file_path: str
    estimated_characters: int
    estimated_tokens: int


class EstimateResponse(BaseModel):
    file_name: str
    source_lang: str
    target_lang: str
    translatable_blocks: int
    skipped_blocks: int
    estimated_characters: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_total_tokens: int
    estimated_cost_usd: float
    budget_usd: float
    budget_status: str


class TranslateJobResponse(BaseModel):
    job_id: str
    status: str


class PdfTranslateJobResponse(TranslateJobResponse):
    file_type: Literal["pdf"]


class PdfLayoutTranslateJobResponse(TranslateJobResponse):
    file_type: Literal["pdf_layout"]


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: int
    result_file: str | None = None
    error: str | None = None


class ProgressEvent(BaseModel):
    job_id: str
    stage: str
    progress: int
    message: str


class ReviewDraftBlock(BaseModel):
    block_id: str
    page: int
    source_text: str
    translated_text: str
    bbox: tuple[float, float, float, float]
    font_size: float = Field(gt=0)
    font_name: str | None = None
    color: tuple[float, float, float] | None = None
    translatable: bool = True
    keep_original: bool = False

    @field_validator("color")
    @classmethod
    def validate_color(
        cls,
        value: tuple[float, float, float] | None,
    ) -> tuple[float, float, float] | None:
        if value is not None and any(component < 0 or component > 1 for component in value):
            raise ValueError("color values must be between 0 and 1")
        return value


class ReviewDraft(BaseModel):
    job_id: str
    file_type: Literal["pdf_layout"] = "pdf_layout"
    source_pdf_path: str
    original_filename: str
    target_lang: LanguageCode
    blocks: list[ReviewDraftBlock]


class ReviewFile(ReviewDraft):
    version: int = 1


class ReviewBlockUpdate(BaseModel):
    block_id: str
    translated_text: str | None = None
    font_size: float | None = Field(default=None, gt=0)
    color: tuple[float, float, float] | None = None
    keep_original: bool = False

    @field_validator("color")
    @classmethod
    def validate_color(
        cls,
        value: tuple[float, float, float] | None,
    ) -> tuple[float, float, float] | None:
        if value is not None and any(component < 0 or component > 1 for component in value):
            raise ValueError("color values must be between 0 and 1")
        return value


class ReviewDraftResponse(BaseModel):
    job_id: str
    file_type: Literal["pdf_layout"]
    source_pdf_path: str
    original_filename: str
    target_lang: LanguageCode
    blocks: list[ReviewDraftBlock]


class ReviewCompleteRequest(BaseModel):
    blocks: list[ReviewBlockUpdate]


class ReviewBuildFromFileRequest(BaseModel):
    review: ReviewFile
