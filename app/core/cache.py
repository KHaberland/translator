import hashlib
import logging
from typing import Protocol

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import Settings
from app.models.schemas import LanguageCode


logger = logging.getLogger(__name__)


class RedisClient(Protocol):
    def get(self, name: str) -> str | None:
        ...

    def set(self, name: str, value: str, ex: int | None = None) -> object:
        ...


class RedisTranslationCache:
    def __init__(self, settings: Settings, redis_client: RedisClient | None = None) -> None:
        self._redis = redis_client or Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        self._ttl_seconds = settings.translation_cache_ttl_seconds

    def get_translation(self, key: str | None) -> str | None:
        if key is None:
            return None

        try:
            value = self._redis.get(key)
        except RedisError:
            logger.warning("translation cache get failed", exc_info=True)
            return None

        return value if isinstance(value, str) else None

    def set_translation(
        self,
        key: str | None,
        value: str,
        ttl: int | None = None,
    ) -> None:
        if key is None or not value:
            return

        try:
            self._redis.set(key, value, ex=ttl or self._ttl_seconds)
        except RedisError:
            logger.warning("translation cache set failed", exc_info=True)


def build_cache_key(
    source_text: str,
    source_lang: LanguageCode,
    target_lang: LanguageCode,
) -> str | None:
    normalized_text = normalize_translation_cache_text(source_text)
    if not normalized_text:
        return None

    digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    return f"translation_cache:{source_lang.value}:{target_lang.value}:{digest}"


def get_translation_cache(settings: Settings) -> RedisTranslationCache:
    return RedisTranslationCache(settings)


def normalize_translation_cache_text(text: str) -> str:
    return " ".join(text.strip().split())
