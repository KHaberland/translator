from enum import StrEnum

from pydantic import BaseModel


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


class TranslateResponse(BaseModel):
    status: str
    file_name: str
    file_path: str
    estimated_characters: int
    estimated_tokens: int


class TranslateJobResponse(BaseModel):
    job_id: str
    status: str


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
