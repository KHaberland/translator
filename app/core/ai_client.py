import asyncio
import json
from collections.abc import Sequence

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from app.core.config import Settings
from app.models.schemas import DocumentBlock, LANGUAGE_NAMES, LanguageCode


class AIClientError(RuntimeError):
    """Raised when the translation provider cannot return a valid result."""


class OpenAICompatibleClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise AIClientError("OPENAI_API_KEY is not configured")

        kwargs: dict[str, object] = {
            "api_key": settings.openai_api_key,
            "timeout": settings.openai_timeout_seconds,
        }
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url

        self._client = AsyncOpenAI(**kwargs)
        self._model = settings.openai_model
        self._max_retries = max(0, settings.openai_max_retries)

    async def translate_blocks(
        self,
        blocks: Sequence[DocumentBlock],
        source_lang: LanguageCode,
        target_lang: LanguageCode,
    ) -> dict[str, str]:
        if not blocks:
            return {}

        payload = [{"id": block.block_id, "text": block.text} for block in blocks]
        response = await self._request_translation(payload, source_lang, target_lang)

        content = response.choices[0].message.content
        if not content:
            raise AIClientError("AI API returned an empty response")

        return _parse_translation_response(content, blocks)

    async def _request_translation(
        self,
        payload: list[dict[str, str]],
        source_lang: LanguageCode,
        target_lang: LanguageCode,
    ) -> object:
        for attempt in range(self._max_retries + 1):
            try:
                return await self._client.chat.completions.create(
                    model=self._model,
                    temperature=0,
                    response_format={"type": "json_object"},
                    messages=[
                        {
                            "role": "system",
                            "content": _build_system_prompt(source_lang, target_lang),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(payload, ensure_ascii=False),
                        },
                    ],
                )
            except (APIConnectionError, APITimeoutError) as exc:
                if attempt >= self._max_retries:
                    raise AIClientError("AI API request failed") from exc
            except APIStatusError as exc:
                if attempt >= self._max_retries or not _is_retryable_status(exc):
                    raise AIClientError("AI API request failed") from exc

            await asyncio.sleep(2**attempt)

        raise AIClientError("AI API request failed")


def _build_system_prompt(source_lang: LanguageCode, target_lang: LanguageCode) -> str:
    source_name = LANGUAGE_NAMES[source_lang]
    target_name = LANGUAGE_NAMES[target_lang]
    return (
        f"Translate from {source_name} ({source_lang}) to "
        f"{target_name} ({target_lang}). Preserve meaning, terminology, tone, "
        "numbers, tags, codes, and formatting markers. Return only valid JSON "
        'as {"translations":[{"id":"...","translation":"..."}]} with the '
        "same ids. Do not translate code, formulas, standards names, or "
        "product identifiers."
    )


def _parse_translation_response(
    content: str,
    source_blocks: Sequence[DocumentBlock],
) -> dict[str, str]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AIClientError("AI API returned invalid JSON") from exc

    translations = data.get("translations") if isinstance(data, dict) else data
    if not isinstance(translations, list):
        raise AIClientError("AI API response must be a translations array")

    expected_ids = {block.block_id for block in source_blocks}
    result: dict[str, str] = {}

    for item in translations:
        if not isinstance(item, dict):
            raise AIClientError("AI API returned an invalid translation item")

        block_id = item.get("id")
        text = item.get("translation")
        if not isinstance(block_id, str) or not isinstance(text, str):
            raise AIClientError("AI API translation item has invalid fields")

        result[block_id] = text

    if set(result) != expected_ids:
        raise AIClientError("AI API response ids do not match source ids")

    return result


def _is_retryable_status(exc: APIStatusError) -> bool:
    return exc.status_code in {408, 409, 429} or exc.status_code >= 500


class MockAIClient:
    async def translate_blocks(
        self,
        blocks: Sequence[DocumentBlock],
        source_lang: LanguageCode,
        target_lang: LanguageCode,
    ) -> dict[str, str]:
        return {
            block.block_id: f"{block.text} [{target_lang}]"
            for block in blocks
        }


def get_translation_client(settings: Settings) -> OpenAICompatibleClient | MockAIClient:
    if settings.mock_ai_enabled:
        return MockAIClient()

    return OpenAICompatibleClient(settings)
