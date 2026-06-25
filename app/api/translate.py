import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.core.config import get_settings
from app.core.job_store import get_job_store
from app.models.jobs import TranslationJob
from app.models.schemas import (
    LanguageCode,
    PdfLayoutTranslateJobResponse,
    PdfTranslateJobResponse,
    TranslateJobResponse,
    TranslateResponse,
)
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
PDF_CONTENT_TYPE = "application/pdf"


@router.post("/", response_model=TranslateJobResponse)
async def translate_docx(
    file: UploadFile = File(...),
    source_lang: LanguageCode = Form(...),
    target_lang: LanguageCode = Form(...),
) -> TranslateJobResponse:
    if source_lang == target_lang:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_lang and target_lang must be different",
        )

    _validate_docx_file(file)

    settings = get_settings()
    content = await file.read()
    upload_path = _save_uploaded_file(
        content=content,
        filename=file.filename or "document.docx",
        max_file_size_bytes=settings.max_file_size_bytes,
    )

    job_id = uuid4().hex
    job = TranslationJob(
        job_id=job_id,
        source_lang=source_lang,
        target_lang=target_lang,
        original_filename=file.filename or upload_path.name,
        upload_path=upload_path.as_posix(),
    )

    try:
        get_job_store().create_job(job)
        _enqueue_translation_job(job_id)
    except Exception as exc:
        logger.warning("translation status=failed file=%s reason=queue", upload_path.name)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="translation queue is unavailable",
        ) from exc

    logger.info("translation status=queued job_id=%s file=%s", job_id, upload_path.name)
    return TranslateJobResponse(job_id=job_id, status=job.status)


@router.post("/pdf", response_model=PdfTranslateJobResponse)
async def translate_pdf(
    file: UploadFile = File(...),
    source_lang: LanguageCode = Form(...),
    target_lang: LanguageCode = Form(...),
) -> PdfTranslateJobResponse:
    if source_lang == target_lang:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_lang and target_lang must be different",
        )

    _validate_pdf_file(file)

    settings = get_settings()
    content = await file.read()
    upload_path = _save_uploaded_file(
        content=content,
        filename=file.filename or "document.pdf",
        max_file_size_bytes=settings.max_file_size_bytes,
    )

    job_id = uuid4().hex
    job = TranslationJob(
        job_id=job_id,
        source_lang=source_lang,
        target_lang=target_lang,
        original_filename=file.filename or upload_path.name,
        upload_path=upload_path.as_posix(),
        file_type="pdf",
    )

    try:
        get_job_store().create_job(job)
        _enqueue_pdf_translation_job(job_id)
    except Exception as exc:
        logger.warning("translation status=failed file=%s reason=queue", upload_path.name)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="translation queue is unavailable",
        ) from exc

    logger.info("translation status=queued job_id=%s file=%s", job_id, upload_path.name)
    return PdfTranslateJobResponse(
        job_id=job_id,
        status=job.status,
        file_type=job.file_type,
    )


@router.post("/pdf-layout", response_model=PdfLayoutTranslateJobResponse)
async def translate_pdf_layout(
    file: UploadFile = File(...),
    source_lang: LanguageCode = Form(...),
    target_lang: LanguageCode = Form(...),
) -> PdfLayoutTranslateJobResponse:
    if source_lang == target_lang:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_lang and target_lang must be different",
        )

    _validate_pdf_file(file)

    settings = get_settings()
    content = await file.read()
    upload_path = _save_uploaded_file(
        content=content,
        filename=file.filename or "document.pdf",
        max_file_size_bytes=settings.max_file_size_bytes,
    )

    job_id = uuid4().hex
    job = TranslationJob(
        job_id=job_id,
        source_lang=source_lang,
        target_lang=target_lang,
        original_filename=file.filename or upload_path.name,
        upload_path=upload_path.as_posix(),
        file_type="pdf_layout",
    )

    try:
        get_job_store().create_job(job)
        _enqueue_pdf_layout_translation_job(job_id)
    except Exception as exc:
        logger.warning("translation status=failed file=%s reason=queue", upload_path.name)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="translation queue is unavailable",
        ) from exc

    logger.info("translation status=queued job_id=%s file=%s", job_id, upload_path.name)
    return PdfLayoutTranslateJobResponse(
        job_id=job_id,
        status=job.status,
        file_type=job.file_type,
    )


@router.post("/sync", response_model=TranslateResponse)
async def translate_docx_sync(
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
    content = await file.read()
    upload_path = _save_uploaded_file(
        content=content,
        filename=file.filename or "document.docx",
        max_file_size_bytes=settings.max_file_size_bytes,
    )

    try:
        result = await translate_docx_file(
            source_path=upload_path,
            original_filename=file.filename or upload_path.name,
            source_lang=source_lang,
            target_lang=target_lang,
            settings=settings,
        )
    except TranslationProviderError as exc:
        logger.warning("translation status=failed file=%s reason=provider", upload_path.name)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="translation provider failed",
        ) from exc
    except DocumentProcessingError as exc:
        logger.warning("translation status=failed file=%s reason=document_processing", upload_path.name)
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


def _validate_pdf_file(file: UploadFile) -> None:
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="only PDF files are supported",
        )

    content_type = getattr(file, "content_type", None)
    if content_type != PDF_CONTENT_TYPE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid PDF content type",
        )


def _build_upload_name(filename: str) -> str:
    suffix = Path(filename).suffix.lower() or ".docx"
    stem = Path(filename).stem or "document"
    return f"{stem}_{uuid4().hex}{suffix}"


def _save_uploaded_file(
    content: bytes,
    filename: str,
    max_file_size_bytes: int,
) -> Path:
    if len(content) > max_file_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="file is too large",
        )

    upload_dir = get_settings().upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_path = upload_dir / _build_upload_name(filename)
    upload_path.write_bytes(content)
    logger.info("translation status=uploaded file=%s size=%s", upload_path.name, len(content))
    return upload_path


def _enqueue_translation_job(job_id: str) -> None:
    from workers.translation_worker import run_translation_job

    run_translation_job.delay(job_id)


def _enqueue_pdf_translation_job(job_id: str) -> None:
    from workers.translation_worker import run_pdf_translation_job

    run_pdf_translation_job.delay(job_id)


def _enqueue_pdf_layout_translation_job(job_id: str) -> None:
    from workers.translation_worker import run_pdf_layout_translation_job

    run_pdf_layout_translation_job.delay(job_id)
