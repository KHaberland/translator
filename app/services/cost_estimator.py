from collections.abc import Iterable
from dataclasses import dataclass
from math import ceil

from app.models.schemas import DocumentBlock


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


def estimate_translatable_characters(blocks: Iterable[DocumentBlock]) -> int:
    return sum(len(block.text) for block in blocks if block.translatable)


def estimate_tokens_from_characters(characters: int) -> int:
    return max(1, ceil(characters / 4)) if characters else 0
