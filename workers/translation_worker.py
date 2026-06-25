import asyncio
import logging
from pathlib import Path

from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.job_store import get_job_store
from app.core.progress_events import build_progress_event, get_progress_event_store
from app.models.jobs import JobStatus
from app.services.pdf.translator import translate_pdf_layout_file
from app.services.translator import (
    DocumentProcessingError,
    TranslationProviderError,
    translate_docx_file,
    translate_pdf_file,
)

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="workers.translation_worker.run_translation_job",
    max_retries=2,
    default_retry_delay=5,
)
def run_translation_job(self, job_id: str) -> dict[str, str]:
    try:
        process_translation_job(job_id)
    except TranslationProviderError as exc:
        if self.request.retries < self.max_retries:
            _update_job(job_id, status=JobStatus.QUEUED, error=None)
            raise self.retry(exc=exc) from exc

        _mark_failed(job_id, "translation provider failed")
        raise

    return {"job_id": job_id, "status": JobStatus.COMPLETED}


@celery_app.task(
    bind=True,
    name="workers.translation_worker.run_pdf_translation_job",
    max_retries=2,
    default_retry_delay=5,
)
def run_pdf_translation_job(self, job_id: str) -> dict[str, str]:
    try:
        process_pdf_translation_job(job_id)
    except TranslationProviderError as exc:
        if self.request.retries < self.max_retries:
            _update_job(job_id, status=JobStatus.QUEUED, error=None)
            raise self.retry(exc=exc) from exc

        _mark_failed(job_id, "translation provider failed")
        raise

    return {"job_id": job_id, "status": JobStatus.COMPLETED}


@celery_app.task(
    bind=True,
    name="workers.translation_worker.run_pdf_layout_translation_job",
    max_retries=2,
    default_retry_delay=5,
)
def run_pdf_layout_translation_job(self, job_id: str) -> dict[str, str]:
    try:
        process_pdf_layout_translation_job(job_id)
    except TranslationProviderError as exc:
        if self.request.retries < self.max_retries:
            _update_job(job_id, status=JobStatus.QUEUED, error=None)
            raise self.retry(exc=exc) from exc

        _mark_failed(job_id, "translation provider failed")
        raise

    return {"job_id": job_id, "status": JobStatus.COMPLETED}


def process_translation_job(job_id: str) -> None:
    job_store = get_job_store()
    job = job_store.get_job(job_id)
    if job is None:
        logger.warning("translation status=failed job_id=%s reason=missing_job", job_id)
        return

    settings = get_settings()

    try:
        result = asyncio.run(
            translate_docx_file(
                source_path=Path(job.upload_path),
                original_filename=job.original_filename,
                source_lang=job.source_lang,
                target_lang=job.target_lang,
                settings=settings,
                progress_callback=lambda stage, progress, message: _update_job(
                    job_id,
                    status=JobStatus(stage),
                    progress=progress,
                    progress_message=message,
                ),
            )
        )
    except TranslationProviderError:
        raise
    except DocumentProcessingError:
        _mark_failed(job_id, "failed to process DOCX file")
        raise
    except Exception:
        _mark_failed(job_id, "unexpected translation job error")
        raise

    job_store.update_job(
        job_id,
        status=JobStatus.COMPLETED,
        progress=100,
        result_file=result.file_path.as_posix(),
        error=None,
    )


def process_pdf_translation_job(job_id: str) -> None:
    job_store = get_job_store()
    job = job_store.get_job(job_id)
    if job is None:
        logger.warning("translation status=failed job_id=%s reason=missing_job", job_id)
        return

    settings = get_settings()

    try:
        result = asyncio.run(
            translate_pdf_file(
                source_path=Path(job.upload_path),
                original_filename=job.original_filename,
                source_lang=job.source_lang,
                target_lang=job.target_lang,
                settings=settings,
                progress_callback=lambda stage, progress, message: _update_job(
                    job_id,
                    status=JobStatus(stage),
                    progress=progress,
                    progress_message=message,
                ),
            )
        )
    except TranslationProviderError:
        raise
    except DocumentProcessingError:
        _mark_failed(job_id, "failed to process PDF file")
        raise
    except Exception:
        _mark_failed(job_id, "unexpected translation job error")
        raise

    job_store.update_job(
        job_id,
        status=JobStatus.COMPLETED,
        progress=100,
        result_file=result.file_path.as_posix(),
        error=None,
    )


def process_pdf_layout_translation_job(job_id: str) -> None:
    job_store = get_job_store()
    job = job_store.get_job(job_id)
    if job is None:
        logger.warning("translation status=failed job_id=%s reason=missing_job", job_id)
        return

    settings = get_settings()

    try:
        result = asyncio.run(
            translate_pdf_layout_file(
                source_path=Path(job.upload_path),
                original_filename=job.original_filename,
                source_lang=job.source_lang,
                target_lang=job.target_lang,
                settings=settings,
                progress_callback=lambda stage, progress, message: _update_job(
                    job_id,
                    status=JobStatus(stage),
                    progress=progress,
                    progress_message=message,
                ),
            )
        )
    except TranslationProviderError:
        raise
    except DocumentProcessingError:
        _mark_failed(job_id, "failed to process PDF layout file")
        raise
    except Exception:
        _mark_failed(job_id, "unexpected translation job error")
        raise

    job_store.update_job(
        job_id,
        status=JobStatus.COMPLETED,
        progress=100,
        result_file=result.file_path.as_posix(),
        error=None,
    )


def _update_job(job_id: str, **fields: object) -> None:
    progress_message = fields.pop("progress_message", None)
    get_job_store().update_job(job_id, **fields)
    _publish_progress(job_id, fields, progress_message)


def _mark_failed(job_id: str, error: str) -> None:
    fields = {
        "status": JobStatus.FAILED,
        "progress": 100,
        "error": error,
    }
    get_job_store().update_job(
        job_id,
        **fields,
    )
    _publish_progress(job_id, fields, error)


def _publish_progress(
    job_id: str,
    fields: dict[str, object],
    message: object = None,
) -> None:
    status = fields.get("status")
    progress = fields.get("progress")
    if not isinstance(status, JobStatus) or not isinstance(progress, int):
        return

    event = build_progress_event(
        job_id=job_id,
        stage=status.value,
        progress=progress,
        message=message if isinstance(message, str) else None,
    )
    get_progress_event_store().publish(event)
