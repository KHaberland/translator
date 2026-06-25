from collections.abc import Iterable
from dataclasses import dataclass
from math import ceil

from app.models.schemas import DocumentBlock
from app.services.translation_cache import normalize_translation_cache_text


@dataclass(frozen=True)
class TranslationCostEstimate:
    translatable_characters: int
    estimated_tokens: int


def estimate_translation_cost(blocks: Iterable[DocumentBlock]) -> TranslationCostEstimate:
    characters = estimate_translatable_characters(blocks)
    return TranslationCostEstimate(
        translatable_characters=characters,
        estimated_tokens=estimate_tokens_from_characters(characters),
    )


def unique_translatable_blocks(blocks: Iterable[DocumentBlock]) -> list[DocumentBlock]:
    seen_texts: set[str] = set()
    unique_blocks: list[DocumentBlock] = []
    for block in blocks:
        if not block.translatable:
            continue

        normalized_text = normalize_translation_cache_text(block.text)
        if not normalized_text or normalized_text in seen_texts:
            continue

        seen_texts.add(normalized_text)
        unique_blocks.append(block)

    return unique_blocks


def estimate_translatable_characters(blocks: Iterable[DocumentBlock]) -> int:
    return sum(len(block.text) for block in blocks if block.translatable)


def estimate_tokens_from_characters(characters: int) -> int:
    return max(1, ceil(characters / 4)) if characters else 0
