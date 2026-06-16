import json
from datetime import UTC, datetime
from functools import lru_cache
from typing import Protocol

from redis import Redis

from app.core.config import Settings, get_settings
from app.models.jobs import TranslationJob


class JobStore(Protocol):
    def create_job(self, job: TranslationJob) -> None:
        ...

    def get_job(self, job_id: str) -> TranslationJob | None:
        ...

    def update_job(self, job_id: str, **fields: object) -> TranslationJob | None:
        ...


class RedisJobStore:
    def __init__(self, settings: Settings) -> None:
        self._redis = Redis.from_url(settings.redis_url, decode_responses=True)
        self._ttl_seconds = settings.job_ttl_seconds

    def create_job(self, job: TranslationJob) -> None:
        self._redis.setex(
            self._key(job.job_id),
            self._ttl_seconds,
            job.model_dump_json(),
        )

    def get_job(self, job_id: str) -> TranslationJob | None:
        raw_job = self._redis.get(self._key(job_id))
        if raw_job is None:
            return None

        return TranslationJob.model_validate_json(raw_job)

    def update_job(self, job_id: str, **fields: object) -> TranslationJob | None:
        current_job = self.get_job(job_id)
        if current_job is None:
            return None

        updated_job = current_job.model_copy(
            update={
                **fields,
                "updated_at": _now_iso(),
            }
        )
        self.create_job(updated_job)
        return updated_job

    @staticmethod
    def _key(job_id: str) -> str:
        return f"translation_job:{job_id}"


class InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, str] = {}

    def create_job(self, job: TranslationJob) -> None:
        self._jobs[job.job_id] = job.model_dump_json()

    def get_job(self, job_id: str) -> TranslationJob | None:
        raw_job = self._jobs.get(job_id)
        if raw_job is None:
            return None

        return TranslationJob.model_validate_json(raw_job)

    def update_job(self, job_id: str, **fields: object) -> TranslationJob | None:
        current_job = self.get_job(job_id)
        if current_job is None:
            return None

        updated_job = current_job.model_copy(
            update={
                **fields,
                "updated_at": _now_iso(),
            }
        )
        self.create_job(updated_job)
        return updated_job


@lru_cache
def get_job_store() -> JobStore:
    return RedisJobStore(get_settings())


def serialize_job_for_log(job: TranslationJob) -> str:
    return json.dumps(
        {
            "job_id": job.job_id,
            "status": job.status,
            "progress": job.progress,
            "result_file": job.result_file,
            "error": job.error,
        },
        ensure_ascii=False,
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
