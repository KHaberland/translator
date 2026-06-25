from collections.abc import Sequence
from pathlib import Path

from app.core.config import Settings
from app.models.schemas import DocumentBlock, LanguageCode
from app.services.pdf.layout_builder import build_translated_pdf
from app.services.pdf.layout_parser import PDFTextBlock, extract_pdf_layout_blocks
from app.services.translator import (
    DocumentProcessingError,
    ProgressCallback,
    TranslationResult,
    _build_output_name,
    _report_progress,
    translate_document_blocks,
)


async def translate_pdf_layout_file(
    source_path: Path,
    original_filename: str,
    source_lang: LanguageCode,
    target_lang: LanguageCode,
    settings: Settings,
    progress_callback: ProgressCallback | None = None,
) -> TranslationResult:
    _report_progress(progress_callback, "extracting_layout", 10, "Extracting PDF layout")
    try:
        layout_blocks = extract_pdf_layout_blocks(source_path)
    except Exception as exc:
        _report_progress(progress_callback, "failed", 100, "Failed to extract PDF layout")
        raise DocumentProcessingError("failed to parse PDF layout file") from exc

    _report_progress(progress_callback, "extracting_text", 20, "Extracting text")
    document_blocks = pdf_text_blocks_to_document_blocks(layout_blocks)
    block_result = await translate_document_blocks(
        blocks=document_blocks,
        document_name=source_path.name,
        source_lang=source_lang,
        target_lang=target_lang,
        settings=settings,
        document_type="PDF layout",
        progress_callback=_layout_progress_callback(progress_callback),
    )

    output_name = _build_output_name(original_filename, target_lang, ".pdf")
    output_path = settings.output_dir / output_name

    _report_progress(progress_callback, "rebuilding_pdf", 90, "Rebuilding PDF")
    try:
        build_translated_pdf(
            source_pdf_path=source_path,
            output_pdf_path=output_path,
            blocks=layout_blocks,
            translations=block_result.translations,
        )
    except Exception as exc:
        _report_progress(progress_callback, "failed", 100, "Failed to rebuild PDF")
        raise DocumentProcessingError("failed to build translated PDF layout file") from exc

    _report_progress(progress_callback, "completed", 100, "Completed")
    return TranslationResult(
        status="completed",
        file_name=output_name,
        file_path=output_path,
        estimated_characters=block_result.estimated_characters,
        estimated_tokens=block_result.estimated_tokens,
    )


def pdf_text_blocks_to_document_blocks(
    blocks: Sequence[PDFTextBlock],
) -> list[DocumentBlock]:
    return [
        DocumentBlock(
            block_id=block.block_id,
            text=block.text,
            location=f"pdf_layout:{block.block_id}",
            translatable=block.translatable,
        )
        for block in blocks
    ]


async def translate_pdf_text_blocks(
    blocks: list[PDFTextBlock],
    document_name: str,
    source_lang: LanguageCode,
    target_lang: LanguageCode,
    settings: Settings,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, str]:
    document_blocks = pdf_text_blocks_to_document_blocks(blocks)
    result = await translate_document_blocks(
        blocks=document_blocks,
        document_name=document_name,
        source_lang=source_lang,
        target_lang=target_lang,
        settings=settings,
        document_type="PDF layout",
        progress_callback=progress_callback,
    )
    return result.translations


def _layout_progress_callback(
    progress_callback: ProgressCallback | None,
) -> ProgressCallback | None:
    if progress_callback is None:
        return None

    def report(status: str, progress: int, message: str | None) -> None:
        if status == "estimating":
            _report_progress(progress_callback, "extracting_text", progress, message)
            return

        _report_progress(progress_callback, status, progress, message)

    return report
