from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app.core.job_store import get_job_store
from app.models.jobs import JobStatus

router = APIRouter(prefix="/download", tags=["download"])

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


@router.get("/{job_id}")
def get_translation_download(job_id: str) -> FileResponse:
    job = get_job_store().get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="translation job not found",
        )

    if job.status != JobStatus.COMPLETED or job.result_file is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="translation result is not ready",
        )

    result_path = Path(job.result_file)
    if not result_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="translation result file not found",
        )

    return FileResponse(
        result_path,
        media_type=DOCX_MEDIA_TYPE,
        filename=result_path.name,
    )
