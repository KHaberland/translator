from fastapi import APIRouter, HTTPException, status

from app.core.job_store import get_job_store
from app.models.schemas import JobStatusResponse

router = APIRouter(prefix="/status", tags=["status"])


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_translation_status(job_id: str) -> JobStatusResponse:
    job = get_job_store().get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="translation job not found",
        )

    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        result_file=job.result_file,
        error=job.error,
    )
