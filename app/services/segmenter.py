from collections.abc import Iterable

from app.models.schemas import DocumentBlock


def build_translation_batches(
    blocks: Iterable[DocumentBlock],
    max_batch_chars: int,
    max_batch_blocks: int,
) -> list[list[DocumentBlock]]:
    if max_batch_chars <= 0:
        raise ValueError("max_batch_chars must be greater than zero")
    if max_batch_blocks <= 0:
        raise ValueError("max_batch_blocks must be greater than zero")

    translatable_blocks = [block for block in blocks if block.translatable]
    batches: list[list[DocumentBlock]] = []
    current_batch: list[DocumentBlock] = []
    current_chars = 0

    for block in translatable_blocks:
        block_chars = len(block.text)
        if block_chars > max_batch_chars:
            raise ValueError(f"block {block.block_id} exceeds max_batch_chars")

        would_exceed_chars = current_chars + block_chars > max_batch_chars
        would_exceed_blocks = len(current_batch) >= max_batch_blocks

        if current_batch and (would_exceed_chars or would_exceed_blocks):
            batches.append(current_batch)
            current_batch = []
            current_chars = 0

        current_batch.append(block)
        current_chars += block_chars

    if current_batch:
        batches.append(current_batch)

    return batches
