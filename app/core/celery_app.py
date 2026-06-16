from celery import Celery

from app.core.config import get_settings


settings = get_settings()

celery_app = Celery(
    "translator_mvp",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["workers.translation_worker"],
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
)
