from pathlib import Path

import fitz

from app.services.pdf.fit_engine import fit_text
from app.services.pdf.layout_parser import PDFTextBlock


FONT_NAME = "TranslatorMVP"
FALLBACK_FONT_NAME = "helv"
MIN_FONT_SIZE = 1.0
WHITE = (1.0, 1.0, 1.0)
BLACK = (0.0, 0.0, 0.0)


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
        for block in blocks:
            translated_text = translations.get(block.block_id)
            if not translated_text:
                continue

            if block.page < 0 or block.page >= document.page_count:
                continue

            page = document[block.page]
            rect = fitz.Rect(block.bbox)
            fitted_text = fit_text(translated_text, block.bbox, block.font_size)
            page.draw_rect(rect, color=WHITE, fill=WHITE, overlay=True, width=0)
            page.insert_textbox(
                rect,
                fitted_text.text,
                fontsize=max(fitted_text.font_size, MIN_FONT_SIZE),
                fontname=font_name,
                fontfile=font_file,
                color=BLACK,
                overlay=True,
            )

        document.save(output_pdf_path)
    finally:
        document.close()


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
