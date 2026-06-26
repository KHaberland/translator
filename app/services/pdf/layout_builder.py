from dataclasses import dataclass
from pathlib import Path

import fitz

from app.services.pdf.fit_engine import fit_text
from app.services.pdf.layout_parser import PDFTextBlock


FONT_NAME = "TranslatorMVP"
FALLBACK_FONT_NAME = "helv"
MIN_FONT_SIZE = 1.0
FONT_SIZE_STEP = 0.5
BLACK = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class PreparedTranslation:
    rect: fitz.Rect
    text: str
    font_size: float
    color: tuple[float, float, float]


def build_translated_pdf(
    source_pdf_path: Path,
    output_pdf_path: Path,
    blocks: list[PDFTextBlock],
    translations: dict[str, str],
) -> None:
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    font_name, font_file = _font()

    document = fitz.open(source_pdf_path)
    try:
        translations_by_page: dict[int, list[PreparedTranslation]] = {}
        for block in blocks:
            translated_text = translations.get(block.block_id)
            if not translated_text:
                continue

            if block.page < 0 or block.page >= document.page_count:
                continue

            rect = fitz.Rect(block.bbox)
            fitted_text = fit_text(
                translated_text,
                block.bbox,
                block.font_size,
                min_font_size=MIN_FONT_SIZE,
            )
            font_size = _actual_fitted_font_size(
                rect,
                fitted_text.text,
                fitted_text.font_size,
                font_name,
                font_file,
            )
            translations_by_page.setdefault(block.page, []).append(
                PreparedTranslation(
                    rect=rect,
                    text=fitted_text.text,
                    font_size=font_size,
                    color=block.color or BLACK,
                )
            )

        for page_index, prepared_translations in translations_by_page.items():
            page = document[page_index]
            for prepared in prepared_translations:
                page.add_redact_annot(
                    _redaction_rect(prepared.rect, page.rect),
                    fill=None,
                    cross_out=False,
                )

            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_NONE,
                graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                text=fitz.PDF_REDACT_TEXT_REMOVE,
            )

            for prepared in prepared_translations:
                result = page.insert_textbox(
                    prepared.rect,
                    prepared.text,
                    fontsize=prepared.font_size,
                    fontname=font_name,
                    fontfile=font_file,
                    color=prepared.color,
                    overlay=True,
                )
                if result < 0:
                    page.insert_text(
                        prepared.rect.tl,
                        prepared.text,
                        fontsize=MIN_FONT_SIZE,
                        fontname=font_name,
                        fontfile=font_file,
                        color=prepared.color,
                        overlay=True,
                    )

        document.save(output_pdf_path)
    finally:
        document.close()


def _redaction_rect(rect: fitz.Rect, page_rect: fitz.Rect) -> fitz.Rect:
    padded_rect = fitz.Rect(
        rect.x0 - 1,
        rect.y0 - 1,
        rect.x1 + 1,
        rect.y1 + 1,
    )
    return padded_rect & page_rect


def _actual_fitted_font_size(
    rect: fitz.Rect,
    text: str,
    font_size: float,
    font_name: str,
    font_file: str | None,
) -> float:
    current_font_size = max(font_size, MIN_FONT_SIZE)
    while current_font_size >= MIN_FONT_SIZE:
        if _textbox_fits(rect, text, current_font_size, font_name, font_file):
            return current_font_size
        current_font_size -= FONT_SIZE_STEP

    return MIN_FONT_SIZE


def _textbox_fits(
    rect: fitz.Rect,
    text: str,
    font_size: float,
    font_name: str,
    font_file: str | None,
) -> bool:
    scratch_document = fitz.open()
    try:
        scratch_page = scratch_document.new_page(
            width=max(rect.x1 + 1, 1),
            height=max(rect.y1 + 1, 1),
        )
        return (
            scratch_page.insert_textbox(
                rect,
                text,
                fontsize=font_size,
                fontname=font_name,
                fontfile=font_file,
                color=BLACK,
            )
            >= 0
        )
    finally:
        scratch_document.close()


def _font() -> tuple[str, str | None]:
    for font_path in _candidate_font_paths():
        if font_path.is_file():
            return FONT_NAME, str(font_path)

    return FALLBACK_FONT_NAME, None


def _candidate_font_paths() -> list[Path]:
    return [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibri.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/local/share/fonts/dejavu/DejaVuSans.ttf"),
        Path("/Library/Fonts/Arial Unicode.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    ]
