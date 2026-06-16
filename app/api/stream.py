import asyncio

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.core.job_store import get_job_store
from app.core.progress_events import (
    ProgressEventStore,
    build_progress_event,
    get_progress_event_store,
)
from app.models.jobs import JobStatus, TranslationJob
from app.models.schemas import ProgressEvent


router = APIRouter(prefix="/stream", tags=["stream"])
TERMINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED}


@router.get("/{job_id}")
async def stream_translation_progress(
    job_id: str,
    request: Request,
) -> StreamingResponse:
    job = get_job_store().get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="translation job not found",
        )

    return StreamingResponse(
        _event_stream(job, request, get_progress_event_store()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _event_stream(
    job: TranslationJob,
    request: Request,
    event_store: ProgressEventStore,
):
    last_event_id = "0-0"
    sent_terminal_event = False

    for event_id, event in event_store.history_with_ids(job.job_id):
        last_event_id = event_id
        sent_terminal_event = _is_terminal_stage(event.stage)
        yield _format_sse(event)
        if sent_terminal_event:
            return

    if job.status in TERMINAL_STATUSES:
        if not sent_terminal_event:
            yield _format_sse(_event_from_job(job))
        return

    while not await request.is_disconnected():
        latest_event_id, events = await asyncio.to_thread(
            event_store.read_after,
            job.job_id,
            last_event_id,
            5000,
        )
        last_event_id = latest_event_id

        if not events:
            yield ": keep-alive\n\n"
            continue

        for event in events:
            yield _format_sse(event)
            if _is_terminal_stage(event.stage):
                return


def _format_sse(event: ProgressEvent) -> str:
    return f"event: progress\ndata: {event.model_dump_json()}\n\n"


def _event_from_job(job: TranslationJob) -> ProgressEvent:
    message = job.error if job.status == JobStatus.FAILED and job.error else None
    return build_progress_event(
        job_id=job.job_id,
        stage=job.status.value,
        progress=job.progress,
        message=message,
    )


def _is_terminal_stage(stage: str) -> bool:
    return stage in {status.value for status in TERMINAL_STATUSES}
