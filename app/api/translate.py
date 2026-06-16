import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.core.config import get_settings
from app.models.schemas import LanguageCode, TranslateResponse
from app.services.translator import (
    DocumentProcessingError,
    TranslationProviderError,
    translate_docx_file,
)

router = APIRouter(prefix="/translate", tags=["translate"])
logger = logging.getLogger(__name__)
DOCX_CONTENT_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",
}


@router.post("/", response_model=TranslateResponse)
async def translate_docx(
    file: UploadFile = File(...),
    source_lang: LanguageCode = Form(...),
    target_lang: LanguageCode = Form(...),
) -> TranslateResponse:
    if source_lang == target_lang:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_lang and target_lang must be different",
        )

    _validate_docx_file(file)

    settings = get_settings()
    upload_dir = settings.upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)

    content = await file.read()
    if len(content) > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="file is too large",
        )

    safe_name = _build_upload_name(file.filename or "document.docx")
    upload_path = upload_dir / safe_name
    upload_path.write_bytes(content)
    logger.info("translation status=uploaded file=%s size=%s", safe_name, len(content))

    try:
        result = await translate_docx_file(
            source_path=upload_path,
            original_filename=file.filename or safe_name,
            source_lang=source_lang,
            target_lang=target_lang,
            settings=settings,
        )
    except TranslationProviderError as exc:
        logger.warning("translation status=failed file=%s reason=provider", safe_name)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="translation provider failed",
        ) from exc
    except DocumentProcessingError as exc:
        logger.warning("translation status=failed file=%s reason=document_processing", safe_name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed to process DOCX file",
        ) from exc

    return TranslateResponse(
        status=result.status,
        file_name=result.file_name,
        file_path=result.file_path.as_posix(),
        estimated_characters=result.estimated_characters,
        estimated_tokens=result.estimated_tokens,
    )


def _validate_docx_file(file: UploadFile) -> None:
    filename = file.filename or ""
    if not filename.lower().endswith(".docx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="only DOCX files are supported",
        )

    content_type = getattr(file, "content_type", None)
    if content_type and content_type not in DOCX_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid DOCX content type",
        )


def _build_upload_name(filename: str) -> str:
    suffix = Path(filename).suffix.lower() or ".docx"
    stem = Path(filename).stem or "document"
    return f"{stem}_{uuid4().hex}{suffix}"
