import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.core.ai_client import AIClientError, get_translation_client
from app.core.cache import RedisTranslationCache, build_cache_key, get_translation_cache
from app.core.config import Settings
from app.models.schemas import DocumentBlock, LanguageCode
from app.services.builder import build_translated_docx
from app.services.cost_estimator import estimate_translation_cost
from app.services.docx_parser import extract_docx_blocks
from app.services.pdf.builder import build_pdf
from app.services.pdf.parser import extract_pdf_blocks
from app.services.segmenter import build_translation_batches
from app.services.translation_cache import TranslationCache
from app.services.translation_memory import SQLiteTranslationMemory, get_translation_memory


logger = logging.getLogger(__name__)
ProgressCallback = Callable[[str, int, str | None], None]


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


@dataclass
class BlocksTranslationResult:
    translations: dict[str, str]
    translated_blocks: list[DocumentBlock]
    estimated_characters: int
    estimated_tokens: int


async def translate_docx_file(
    source_path: Path,
    original_filename: str,
    source_lang: LanguageCode,
    target_lang: LanguageCode,
    settings: Settings,
    progress_callback: ProgressCallback | None = None,
) -> TranslationResult:
    _report_progress(progress_callback, "parsing", 10, "Parsing document")
    _log_status("parsing", source_path.name)
    try:
        blocks = extract_docx_blocks(source_path)
    except Exception as exc:
        _report_progress(progress_callback, "failed", 100, "Failed to parse document")
        _log_status("failed", source_path.name, reason="parse")
        raise DocumentProcessingError("failed to parse DOCX file") from exc

    block_result = await translate_document_blocks(
        blocks=blocks,
        document_name=source_path.name,
        source_lang=source_lang,
        target_lang=target_lang,
        settings=settings,
        document_type="DOCX",
        progress_callback=progress_callback,
    )

    output_name = _build_output_name(original_filename, target_lang, ".docx")
    output_path = settings.output_dir / output_name

    _report_progress(progress_callback, "building", 90, "Building document")
    _log_status("building", source_path.name)
    try:
        build_translated_docx(source_path, output_path, block_result.translations)
    except Exception as exc:
        _report_progress(progress_callback, "failed", 100, "Failed to build document")
        _log_status("failed", source_path.name, reason="build")
        raise DocumentProcessingError("failed to build translated DOCX file") from exc

    _report_progress(progress_callback, "completed", 100, "Completed")
    _log_status("completed", source_path.name)
    return TranslationResult(
        status="completed",
        file_name=output_name,
        file_path=output_path,
        estimated_characters=block_result.estimated_characters,
        estimated_tokens=block_result.estimated_tokens,
    )


async def translate_pdf_file(
    source_path: Path,
    original_filename: str,
    source_lang: LanguageCode,
    target_lang: LanguageCode,
    settings: Settings,
    progress_callback: ProgressCallback | None = None,
) -> TranslationResult:
    _report_progress(progress_callback, "parsing", 10, "Parsing document")
    _log_status("parsing", source_path.name)
    try:
        blocks = extract_pdf_blocks(source_path)
    except Exception as exc:
        _report_progress(progress_callback, "failed", 100, "Failed to parse document")
        _log_status("failed", source_path.name, reason="parse")
        raise DocumentProcessingError("failed to parse PDF file") from exc

    block_result = await translate_document_blocks(
        blocks=blocks,
        document_name=source_path.name,
        source_lang=source_lang,
        target_lang=target_lang,
        settings=settings,
        document_type="PDF",
        progress_callback=progress_callback,
    )

    output_name = _build_output_name(original_filename, target_lang, ".pdf")
    output_path = settings.output_dir / output_name

    _report_progress(progress_callback, "building", 90, "Building document")
    _log_status("building", source_path.name)
    try:
        build_pdf(block_result.translated_blocks, output_path.as_posix())
    except Exception as exc:
        _report_progress(progress_callback, "failed", 100, "Failed to build document")
        _log_status("failed", source_path.name, reason="build")
        raise DocumentProcessingError("failed to build translated PDF file") from exc

    _report_progress(progress_callback, "completed", 100, "Completed")
    _log_status("completed", source_path.name)
    return TranslationResult(
        status="completed",
        file_name=output_name,
        file_path=output_path,
        estimated_characters=block_result.estimated_characters,
        estimated_tokens=block_result.estimated_tokens,
    )


async def translate_document_blocks(
    blocks: list[DocumentBlock],
    document_name: str,
    source_lang: LanguageCode,
    target_lang: LanguageCode,
    settings: Settings,
    document_type: str,
    progress_callback: ProgressCallback | None = None,
) -> BlocksTranslationResult:
    _report_progress(progress_callback, "estimating", 20, "Estimating translation cost")
    _log_status("estimating", document_name)
    translation_cache = TranslationCache(source_lang, target_lang)
    unique_blocks, duplicate_block_ids = _deduplicate_translatable_blocks(
        blocks,
        translation_cache,
    )
    shared_cache = get_translation_cache(settings)
    translation_memory = get_translation_memory(settings.translation_memory_db_path)
    translations, uncached_blocks = _load_shared_cached_translations(
        unique_blocks,
        source_lang,
        target_lang,
        shared_cache,
        translation_cache,
    )
    memory_translations, untranslated_blocks = _load_memory_translations(
        uncached_blocks,
        source_lang,
        target_lang,
        translation_memory,
        translation_cache,
        shared_cache,
    )
    translations.update(memory_translations)
    cost_estimate = estimate_translation_cost(untranslated_blocks)
    try:
        batches = build_translation_batches(
            untranslated_blocks,
            max_batch_chars=settings.max_batch_chars,
            max_batch_blocks=settings.max_batch_blocks,
        )
    except ValueError as exc:
        _report_progress(progress_callback, "failed", 100, "Failed to segment document")
        _log_status("failed", document_name, reason="segment")
        raise DocumentProcessingError(f"failed to segment {document_type} file") from exc

    _log_status(
        "estimating",
        document_name,
        blocks=len(blocks),
        translatable_blocks=len(untranslated_blocks),
        cached_blocks=len(translations),
        duplicate_blocks=len(duplicate_block_ids),
        batches=len(batches),
        characters=cost_estimate.translatable_characters,
        tokens=cost_estimate.estimated_tokens,
    )

    if batches:
        _report_progress(progress_callback, "translating", 30, "Translating document")
        _log_status("translating", document_name)
        try:
            client = get_translation_client(settings)
            total_batches = len(batches)
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
                    glossary_terms=translation_memory.glossary_terms_for_blocks(
                        batch,
                        source_lang,
                        target_lang,
                    ),
                )
                translations.update(batch_translations)
                _remember_batch_translations(
                    batch,
                    batch_translations,
                    source_lang,
                    target_lang,
                    translation_cache,
                    shared_cache,
                    translation_memory,
                )
                _report_progress(
                    progress_callback,
                    "translating",
                    _translation_progress(batch_index, total_batches),
                    f"Batch {batch_index}/{total_batches} translated",
                )
        except AIClientError as exc:
            _report_progress(progress_callback, "failed", 100, "Translation provider failed")
            _log_status("failed", document_name, reason="provider")
            raise TranslationProviderError(f"failed to translate {document_type} file") from exc

    _apply_cached_duplicate_translations(
        blocks,
        translations,
        duplicate_block_ids,
        translation_cache,
    )

    return BlocksTranslationResult(
        translations=translations,
        translated_blocks=_translated_blocks(blocks, translations),
        estimated_characters=cost_estimate.translatable_characters,
        estimated_tokens=cost_estimate.estimated_tokens,
    )


def _build_output_name(filename: str, target_lang: LanguageCode, extension: str) -> str:
    path = Path(filename)
    stem = _sanitize_filename_part(path.stem or "document")
    return f"{stem}_translated_to_{target_lang}{extension}"


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


def _report_progress(
    progress_callback: ProgressCallback | None,
    status: str,
    progress: int,
    message: str | None = None,
) -> None:
    if progress_callback is not None:
        progress_callback(status, progress, message)


def _translation_progress(batch_index: int, total_batches: int) -> int:
    if total_batches <= 0:
        return 80

    return min(80, 30 + round((batch_index / total_batches) * 50))


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
    source_lang: LanguageCode,
    target_lang: LanguageCode,
    translation_cache: TranslationCache,
    shared_cache: RedisTranslationCache,
    translation_memory: SQLiteTranslationMemory,
) -> None:
    block_by_id = {block.block_id: block for block in batch}
    for block_id, translated_text in batch_translations.items():
        block = block_by_id.get(block_id)
        if block is not None:
            translation_cache.remember_translation(block.text, translated_text)
            shared_cache.set_translation(
                build_cache_key(block.text, source_lang, target_lang),
                translated_text,
            )
            translation_memory.save_translation(
                block.text,
                translated_text,
                source_lang,
                target_lang,
            )


def _load_shared_cached_translations(
    blocks: list[DocumentBlock],
    source_lang: LanguageCode,
    target_lang: LanguageCode,
    shared_cache: RedisTranslationCache,
    translation_cache: TranslationCache,
) -> tuple[dict[str, str], list[DocumentBlock]]:
    translations: dict[str, str] = {}
    uncached_blocks: list[DocumentBlock] = []

    for block in blocks:
        cached_translation = shared_cache.get_translation(
            build_cache_key(block.text, source_lang, target_lang)
        )
        if cached_translation is None:
            uncached_blocks.append(block)
            continue

        translations[block.block_id] = cached_translation
        translation_cache.remember_translation(block.text, cached_translation)

    return translations, uncached_blocks


def _load_memory_translations(
    blocks: list[DocumentBlock],
    source_lang: LanguageCode,
    target_lang: LanguageCode,
    translation_memory: SQLiteTranslationMemory,
    translation_cache: TranslationCache,
    shared_cache: RedisTranslationCache,
) -> tuple[dict[str, str], list[DocumentBlock]]:
    translations: dict[str, str] = {}
    untranslated_blocks: list[DocumentBlock] = []

    for block in blocks:
        memory_translation = translation_memory.lookup_exact(
            block.text,
            source_lang,
            target_lang,
        )
        if memory_translation is None:
            untranslated_blocks.append(block)
            continue

        translations[block.block_id] = memory_translation
        translation_cache.remember_translation(block.text, memory_translation)
        translation_memory.increment_frequency(block.text, source_lang, target_lang)
        shared_cache.set_translation(
            build_cache_key(block.text, source_lang, target_lang),
            memory_translation,
        )

    return translations, untranslated_blocks


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


def _translated_blocks(
    blocks: list[DocumentBlock],
    translations: dict[str, str],
) -> list[DocumentBlock]:
    return [
        block.model_copy(update={"text": translations.get(block.block_id, block.text)})
        for block in blocks
    ]
