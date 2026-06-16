from dataclasses import dataclass, field

from app.models.schemas import DocumentBlock, LanguageCode


@dataclass
class TranslationCache:
    source_lang: LanguageCode
    target_lang: LanguageCode
    _original_block_ids: dict[tuple[str, str, str], str] = field(default_factory=dict)
    _translations: dict[tuple[str, str, str], str] = field(default_factory=dict)

    def original_block_id_for(self, block: DocumentBlock) -> str | None:
        if not block.translatable:
            return None

        cache_key = self._key(block.text)
        if cache_key is None:
            return None

        original_block_id = self._original_block_ids.get(cache_key)
        if original_block_id is None:
            self._original_block_ids[cache_key] = block.block_id
            return None

        return original_block_id

    def remember_translation(self, source_text: str, translated_text: str) -> None:
        cache_key = self._key(source_text)
        if cache_key is None:
            return

        self._translations[cache_key] = translated_text

    def translation_for(self, source_text: str) -> str | None:
        cache_key = self._key(source_text)
        if cache_key is None:
            return None

        return self._translations.get(cache_key)

    def _key(self, text: str) -> tuple[str, str, str] | None:
        normalized_text = normalize_translation_cache_text(text)
        if not normalized_text:
            return None

        return (
            self.source_lang.value,
            self.target_lang.value,
            normalized_text,
        )


def normalize_translation_cache_text(text: str) -> str:
    return " ".join(text.strip().split())
