from pathlib import Path
from time import time

from app.core.config import Settings
from app.models.schemas import (
    LanguageCode,
    ReviewBlockUpdate,
    ReviewDraft,
    ReviewDraftBlock,
)
from app.services.pdf.layout_builder import build_translated_pdf
from app.services.pdf.layout_parser import PDFTextBlock, extract_pdf_layout_blocks
from app.services.pdf.translator import (
    _layout_progress_callback,
    pdf_text_blocks_to_document_blocks,
)
from app.services.translator import (
    DocumentProcessingError,
    ProgressCallback,
    TranslationResult,
    _build_output_name,
    _report_progress,
    translate_document_blocks,
)


REVIEW_DRAFTS_DIR = "review_drafts"


async def create_pdf_layout_review_draft(
    job_id: str,
    source_path: Path,
    original_filename: str,
    source_lang: LanguageCode,
    target_lang: LanguageCode,
    settings: Settings,
    progress_callback: ProgressCallback | None = None,
) -> ReviewDraft:
    _report_progress(progress_callback, "extracting_layout", 10, "Extracting PDF layout")
    try:
        layout_blocks = extract_pdf_layout_blocks(source_path)
    except Exception as exc:
        _report_progress(progress_callback, "failed", 100, "Failed to extract PDF layout")
        raise DocumentProcessingError("failed to parse PDF layout file") from exc

    _report_progress(progress_callback, "extracting_text", 20, "Extracting text")
    block_result = await translate_document_blocks(
        blocks=pdf_text_blocks_to_document_blocks(layout_blocks),
        document_name=source_path.name,
        source_lang=source_lang,
        target_lang=target_lang,
        settings=settings,
        document_type="PDF layout",
        progress_callback=_layout_progress_callback(progress_callback),
    )
    draft = ReviewDraft(
        job_id=job_id,
        source_pdf_path=source_path.as_posix(),
        original_filename=original_filename,
        target_lang=target_lang,
        blocks=[
            _draft_block(block, block_result.translations.get(block.block_id))
            for block in layout_blocks
        ],
    )
    save_review_draft(settings, draft)
    _report_progress(progress_callback, "needs_review", 85, "Review draft is ready")
    return draft


def save_review_draft(settings: Settings, draft: ReviewDraft) -> None:
    cleanup_review_drafts(settings)
    path = review_draft_path(settings, draft.job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(draft.model_dump_json(indent=2), encoding="utf-8")


def load_review_draft(settings: Settings, job_id: str) -> ReviewDraft | None:
    path = review_draft_path(settings, job_id)
    if not path.is_file():
        return None
    return ReviewDraft.model_validate_json(path.read_text(encoding="utf-8"))


def delete_review_draft(settings: Settings, job_id: str) -> None:
    review_draft_path(settings, job_id).unlink(missing_ok=True)


def review_draft_path(settings: Settings, job_id: str) -> Path:
    return settings.tmp_dir / REVIEW_DRAFTS_DIR / f"{job_id}.json"


def cleanup_review_drafts(settings: Settings) -> None:
    draft_dir = settings.tmp_dir / REVIEW_DRAFTS_DIR
    if not draft_dir.is_dir():
        return

    cutoff = time() - settings.job_ttl_seconds
    for draft_path in draft_dir.glob("*.json"):
        try:
            if draft_path.stat().st_mtime < cutoff:
                draft_path.unlink()
        except OSError:
            continue


def build_reviewed_pdf(
    settings: Settings,
    draft: ReviewDraft,
    updates: list[ReviewBlockUpdate],
) -> TranslationResult:
    blocks_by_id = {block.block_id: block for block in draft.blocks}
    unknown_ids = sorted(
        {update.block_id for update in updates if update.block_id not in blocks_by_id}
    )
    if unknown_ids:
        raise ValueError(f"unknown block_id: {', '.join(unknown_ids)}")

    merged_blocks = _merge_review_updates(draft.blocks, updates)
    pdf_blocks = [_pdf_text_block(block) for block in merged_blocks]
    translations = {
        block.block_id: _review_text(block)
        for block in merged_blocks
        if _review_text(block).strip()
    }
    if len(translations) != len(merged_blocks):
        raise ValueError("translated_text must not be empty")

    output_name = _build_output_name(draft.original_filename, draft.target_lang, ".pdf")
    output_path = settings.output_dir / output_name
    try:
        build_translated_pdf(
            source_pdf_path=Path(draft.source_pdf_path),
            output_pdf_path=output_path,
            blocks=pdf_blocks,
            translations=translations,
        )
    except Exception as exc:
        raise DocumentProcessingError("failed to build translated PDF layout file") from exc

    return TranslationResult(
        status="completed",
        file_name=output_name,
        file_path=output_path,
        estimated_characters=0,
        estimated_tokens=0,
    )


def _draft_block(block: PDFTextBlock, translated_text: str | None) -> ReviewDraftBlock:
    return ReviewDraftBlock(
        block_id=block.block_id,
        page=block.page,
        source_text=block.text,
        translated_text=translated_text or block.text,
        bbox=block.bbox,
        font_size=max(block.font_size, 1.0),
        font_name=block.font_name,
        color=block.color,
        translatable=block.translatable,
        keep_original=not block.translatable,
    )


def _merge_review_updates(
    draft_blocks: list[ReviewDraftBlock],
    updates: list[ReviewBlockUpdate],
) -> list[ReviewDraftBlock]:
    updates_by_id = {update.block_id: update for update in updates}
    merged_blocks: list[ReviewDraftBlock] = []
    for block in draft_blocks:
        update = updates_by_id.get(block.block_id)
        if update is None:
            merged_blocks.append(block)
            continue

        merged_blocks.append(
            block.model_copy(
                update={
                    "translated_text": (
                        block.translated_text
                        if update.translated_text is None
                        else update.translated_text
                    ),
                    "font_size": update.font_size or block.font_size,
                    "color": update.color if update.color is not None else block.color,
                    "keep_original": update.keep_original or not block.translatable,
                }
            )
        )
    return merged_blocks


def _pdf_text_block(block: ReviewDraftBlock) -> PDFTextBlock:
    return PDFTextBlock(
        block_id=block.block_id,
        text=block.source_text,
        page=block.page,
        bbox=block.bbox,
        font_size=block.font_size,
        font_name=block.font_name,
        translatable=block.translatable,
        color=block.color,
    )


def _review_text(block: ReviewDraftBlock) -> str:
    if block.keep_original or not block.translatable:
        return block.source_text
    return block.translated_text
