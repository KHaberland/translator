import json
import logging
from collections.abc import Iterable
from typing import Protocol

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import Settings, get_settings
from app.models.schemas import ProgressEvent


logger = logging.getLogger(__name__)


class RedisStreamClient(Protocol):
    def expire(self, name: str, time: int) -> object:
        ...

    def xadd(
        self,
        name: str,
        fields: dict[str, str],
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> object:
        ...

    def xrange(
        self,
        name: str,
        min: str = "-",
        max: str = "+",
        count: int | None = None,
    ) -> list[tuple[str, dict[str, str]]]:
        ...

    def xread(
        self,
        streams: dict[str, str],
        count: int | None = None,
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        ...


class ProgressEventStore:
    def __init__(
        self,
        settings: Settings,
        redis_client: RedisStreamClient | None = None,
    ) -> None:
        self._redis = redis_client or Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        self._ttl_seconds = settings.job_ttl_seconds
        self._max_events = settings.progress_stream_max_events

    def publish(self, event: ProgressEvent) -> None:
        try:
            self._redis.xadd(
                self._key(event.job_id),
                {"event": event.model_dump_json()},
                maxlen=self._max_events,
                approximate=True,
            )
            self._redis.expire(self._key(event.job_id), self._ttl_seconds)
        except RedisError:
            logger.warning("progress event publish failed", exc_info=True)

    def history(self, job_id: str) -> list[ProgressEvent]:
        return [event for _, event in self.history_with_ids(job_id)]

    def history_with_ids(self, job_id: str) -> list[tuple[str, ProgressEvent]]:
        try:
            entries = self._redis.xrange(self._key(job_id))
        except RedisError:
            logger.warning("progress event history failed", exc_info=True)
            return []

        return list(_events_from_entries(entries))

    def read_after(
        self,
        job_id: str,
        last_event_id: str,
        block_ms: int,
    ) -> tuple[str, list[ProgressEvent]]:
        try:
            streams = self._redis.xread(
                {self._key(job_id): last_event_id},
                count=10,
                block=block_ms,
            )
        except RedisError:
            logger.warning("progress event read failed", exc_info=True)
            return last_event_id, []

        events: list[ProgressEvent] = []
        latest_event_id = last_event_id
        for _, entries in streams:
            for entry_id, fields in entries:
                latest_event_id = entry_id
                event = _event_from_fields(fields)
                if event is not None:
                    events.append(event)

        return latest_event_id, events

    @staticmethod
    def _key(job_id: str) -> str:
        return f"progress_events:{job_id}"


def get_progress_event_store(settings: Settings | None = None) -> ProgressEventStore:
    return ProgressEventStore(settings or get_settings())


def build_progress_event(
    job_id: str,
    stage: str,
    progress: int,
    message: str | None = None,
) -> ProgressEvent:
    return ProgressEvent(
        job_id=job_id,
        stage=stage,
        progress=max(0, min(100, progress)),
        message=message or _default_message(stage),
    )


def _events_from_entries(
    entries: Iterable[tuple[str, dict[str, str]]],
) -> Iterable[tuple[str, ProgressEvent]]:
    for entry_id, fields in entries:
        event = _event_from_fields(fields)
        if event is not None:
            yield entry_id, event


def _event_from_fields(fields: dict[str, str]) -> ProgressEvent | None:
    raw_event = fields.get("event")
    if raw_event is None:
        return None

    try:
        data = json.loads(raw_event)
        return ProgressEvent.model_validate(data)
    except (json.JSONDecodeError, ValueError):
        logger.warning("invalid progress event skipped")
        return None


def _default_message(stage: str) -> str:
    messages = {
        "queued": "Job queued",
        "parsing": "Parsing document",
        "extracting_layout": "Extracting PDF layout",
        "extracting_text": "Extracting text",
        "estimating": "Estimating translation cost",
        "translating": "Translating document",
        "building": "Building document",
        "rebuilding_pdf": "Rebuilding PDF",
        "completed": "Completed",
        "failed": "Failed",
    }
    return messages.get(stage, stage)
