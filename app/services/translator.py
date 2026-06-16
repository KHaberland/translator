import logging
from dataclasses import dataclass
from pathlib import Path

from app.core.ai_client import AIClientError, get_translation_client
from app.core.config import Settings
from app.models.schemas import DocumentBlock, LanguageCode
from app.services.builder import build_translated_docx
from app.services.cost_estimator import estimate_translation_cost
from app.services.docx_parser import extract_docx_blocks
from app.services.segmenter import build_translation_batches
from app.services.translation_cache import TranslationCache


logger = logging.getLogger(__name__)


class DocumentProcessingError(RuntimeError):
    """Raised when a DOCX file cannot be parsed or rebuilt."""


class TranslationProviderError(RuntimeError):
    """Raised when the external translation provider fails."""


@dataclass(frozen=True)
class TranslationResult:
    status: str
    file_name: str
    file_path: Path
    estimated_characters: int
    estimated_tokens: int


async def translate_docx_file(
    source_path: Path,
    original_filename: str,
    source_lang: LanguageCode,
    target_lang: LanguageCode,
    settings: Settings,
) -> TranslationResult:
    _log_status("parsing", source_path.name)
    try:
        blocks = extract_docx_blocks(source_path)
    except Exception as exc:
        _log_status("failed", source_path.name, reason="parse")
        raise DocumentProcessingError("failed to parse DOCX file") from exc

    _log_status("estimating", source_path.name)
    translation_cache = TranslationCache(source_lang, target_lang)
    unique_blocks, duplicate_block_ids = _deduplicate_translatable_blocks(
        blocks,
        translation_cache,
    )
    cost_estimate = estimate_translation_cost(unique_blocks)
    try:
        batches = build_translation_batches(
            unique_blocks,
            max_batch_chars=settings.max_batch_chars,
            max_batch_blocks=settings.max_batch_blocks,
        )
    except ValueError as exc:
        _log_status("failed", source_path.name, reason="segment")
        raise DocumentProcessingError("failed to segment DOCX file") from exc

    _log_status(
        "estimating",
        source_path.name,
        blocks=len(blocks),
        translatable_blocks=len(unique_blocks),
        duplicate_blocks=len(duplicate_block_ids),
        batches=len(batches),
        characters=cost_estimate.translatable_characters,
        tokens=cost_estimate.estimated_tokens,
    )

    translations: dict[str, str] = {}
    if batches:
        _log_status("translating", source_path.name)
        try:
            client = get_translation_client(settings)
            for batch_index, batch in enumerate(batches, start=1):
                logger.debug(
                    "translation batch=%s blocks=%s characters=%s",
                    batch_index,
                    len(batch),
                    sum(len(block.text) for block in batch),
                )
                batch_translations = await client.translate_blocks(
                    batch,
                    source_lang,
                    target_lang,
                )
                translations.update(batch_translations)
                _remember_batch_translations(batch, batch_translations, translation_cache)
        except AIClientError as exc:
            _log_status("failed", source_path.name, reason="provider")
            raise TranslationProviderError("failed to translate DOCX file") from exc

    _apply_cached_duplicate_translations(
        blocks,
        translations,
        duplicate_block_ids,
        translation_cache,
    )

    output_name = _build_output_name(original_filename, target_lang)
    output_path = settings.output_dir / output_name

    _log_status("building", source_path.name)
    try:
        build_translated_docx(source_path, output_path, translations)
    except Exception as exc:
        _log_status("failed", source_path.name, reason="build")
        raise DocumentProcessingError("failed to build translated DOCX file") from exc

    _log_status("completed", source_path.name)
    return TranslationResult(
        status="completed",
        file_name=output_name,
        file_path=output_path,
        estimated_characters=cost_estimate.translatable_characters,
        estimated_tokens=cost_estimate.estimated_tokens,
    )


def _build_output_name(filename: str, target_lang: LanguageCode) -> str:
    path = Path(filename)
    stem = _sanitize_filename_part(path.stem or "document")
    return f"{stem}_translated_to_{target_lang}.docx"


def _sanitize_filename_part(value: str) -> str:
    sanitized = "".join(
        "_" if character in '<>:"/\\|?*' or ord(character) < 32 else character
        for character in value
    ).strip("._ ")
    return sanitized or "document"


def _log_status(status: str, file_name: str, **fields: object) -> None:
    details = " ".join(f"{key}={value}" for key, value in fields.items())
    message = "translation status=%s file=%s"
    if details:
        message = f"{message} {details}"

    logger.info(message, status, file_name)


def _deduplicate_translatable_blocks(
    blocks: list[DocumentBlock],
    translation_cache: TranslationCache,
) -> tuple[list[DocumentBlock], dict[str, str]]:
    unique_blocks: list[DocumentBlock] = []
    duplicate_block_ids: dict[str, str] = {}

    for block in blocks:
        if not block.translatable:
            continue

        original_block_id = translation_cache.original_block_id_for(block)
        if original_block_id:
            duplicate_block_ids[block.block_id] = original_block_id
            continue

        unique_blocks.append(block)

    return unique_blocks, duplicate_block_ids


def _remember_batch_translations(
    batch: list[DocumentBlock],
    batch_translations: dict[str, str],
    translation_cache: TranslationCache,
) -> None:
    block_by_id = {block.block_id: block for block in batch}
    for block_id, translated_text in batch_translations.items():
        block = block_by_id.get(block_id)
        if block is not None:
            translation_cache.remember_translation(block.text, translated_text)


def _apply_cached_duplicate_translations(
    blocks: list[DocumentBlock],
    translations: dict[str, str],
    duplicate_block_ids: dict[str, str],
    translation_cache: TranslationCache,
) -> None:
    block_by_id = {block.block_id: block for block in blocks}
    for duplicate_block_id, original_block_id in duplicate_block_ids.items():
        duplicate_block = block_by_id.get(duplicate_block_id)
        if duplicate_block is None:
            continue

        translated_text = (
            translation_cache.translation_for(duplicate_block.text)
            or translations.get(original_block_id)
        )
        if translated_text is not None:
            translations[duplicate_block.block_id] = translated_text
