from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from app.core.config import get_settings
from app.core.job_store import get_job_store
from app.models.jobs import JobStatus
from app.models.schemas import (
    ReviewBuildFromFileRequest,
    ReviewCompleteRequest,
    ReviewDraftResponse,
)
from app.services.pdf.review import (
    build_reviewed_pdf,
    delete_review_draft,
    load_review_draft,
)
from app.services.translator import DocumentProcessingError

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/{job_id}", response_model=ReviewDraftResponse)
def get_review_draft(job_id: str) -> ReviewDraftResponse:
    job = get_job_store().get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="translation job not found",
        )
    if job.file_type != "pdf_layout":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="review is available only for layout PDF jobs",
        )

    draft = load_review_draft(get_settings(), job_id)
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="review draft not found",
        )

    return ReviewDraftResponse(
        job_id=draft.job_id,
        file_type=draft.file_type,
        source_pdf_path=draft.source_pdf_path,
        original_filename=draft.original_filename,
        target_lang=draft.target_lang,
        blocks=draft.blocks,
    )


@router.post("/{job_id}/complete")
def complete_review(job_id: str, request: ReviewCompleteRequest) -> dict[str, str]:
    job_store = get_job_store()
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="translation job not found",
        )
    if job.file_type != "pdf_layout":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="review is available only for layout PDF jobs",
        )
    if job.status != JobStatus.NEEDS_REVIEW:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="translation job is not awaiting review",
        )

    settings = get_settings()
    draft = load_review_draft(settings, job_id)
    if draft is None or draft.job_id != job_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="review draft not found",
        )

    job_store.update_job(job_id, status=JobStatus.REBUILDING_PDF, progress=90, error=None)
    try:
        result = build_reviewed_pdf(settings, draft, request.blocks)
    except ValueError as exc:
        job_store.update_job(job_id, status=JobStatus.NEEDS_REVIEW, progress=85, error=None)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except DocumentProcessingError as exc:
        job_store.update_job(
            job_id,
            status=JobStatus.FAILED,
            progress=100,
            error="failed to process PDF layout file",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed to process PDF layout file",
        ) from exc

    job_store.update_job(
        job_id,
        status=JobStatus.COMPLETED,
        progress=100,
        result_file=result.file_path.as_posix(),
        error=None,
    )
    delete_review_draft(settings, job_id)
    return {
        "job_id": job_id,
        "status": JobStatus.COMPLETED,
        "result_file": result.file_path.as_posix(),
    }


@router.post("/build-from-file")
def build_from_review_file(request: ReviewBuildFromFileRequest) -> dict[str, str]:
    review = request.review
    if review.version != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unsupported review file version",
        )
    if not review.blocks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="review file is invalid",
        )
    if not Path(review.source_pdf_path).is_file():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="original PDF not found",
        )

    try:
        result = build_reviewed_pdf(get_settings(), review, [])
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except DocumentProcessingError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed to process PDF layout file",
        ) from exc

    return {
        "status": result.status,
        "result_file": result.file_path.as_posix(),
    }
