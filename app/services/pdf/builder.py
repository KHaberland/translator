from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.models.schemas import DocumentBlock


PAGE_SIZE = A4
LEFT_MARGIN = 56
RIGHT_MARGIN = 56
TOP_MARGIN = 56
BOTTOM_MARGIN = 56
FONT_SIZE = 11
LINE_HEIGHT = 15
BLOCK_SPACING = 10
FONT_NAME = "TranslatorMVP"
FALLBACK_FONT_NAME = "Helvetica"


def build_pdf(blocks: list[DocumentBlock], output_path: str) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    font_name = _font_name()
    page_width, page_height = PAGE_SIZE
    max_line_width = page_width - LEFT_MARGIN - RIGHT_MARGIN

    pdf = canvas.Canvas(str(path), pagesize=PAGE_SIZE)
    pdf.setTitle(path.name)
    pdf.setFont(font_name, FONT_SIZE)

    y_position = page_height - TOP_MARGIN
    for block in blocks:
        text = block.text.strip()
        if not text:
            continue

        lines = _wrap_text(text, font_name, FONT_SIZE, max_line_width)
        block_height = len(lines) * LINE_HEIGHT
        if y_position - block_height < BOTTOM_MARGIN:
            pdf.showPage()
            pdf.setFont(font_name, FONT_SIZE)
            y_position = page_height - TOP_MARGIN

        for line in lines:
            pdf.drawString(LEFT_MARGIN, y_position, line)
            y_position -= LINE_HEIGHT

        y_position -= BLOCK_SPACING

    pdf.save()


def _wrap_text(
    text: str,
    font_name: str,
    font_size: int,
    max_line_width: float,
) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue

        current_line = words[0]
        for word in words[1:]:
            candidate = f"{current_line} {word}"
            if _text_width(candidate, font_name, font_size) <= max_line_width:
                current_line = candidate
                continue

            lines.extend(_split_oversized_line(current_line, font_name, font_size, max_line_width))
            current_line = word

        lines.extend(_split_oversized_line(current_line, font_name, font_size, max_line_width))

    return lines


def _split_oversized_line(
    text: str,
    font_name: str,
    font_size: int,
    max_line_width: float,
) -> list[str]:
    if _text_width(text, font_name, font_size) <= max_line_width:
        return [text]

    lines: list[str] = []
    current_line = ""
    for character in text:
        candidate = f"{current_line}{character}"
        if current_line and _text_width(candidate, font_name, font_size) > max_line_width:
            lines.append(current_line)
            current_line = character
        else:
            current_line = candidate

    if current_line:
        lines.append(current_line)

    return lines


def _text_width(text: str, font_name: str, font_size: int) -> float:
    return pdfmetrics.stringWidth(text, font_name, font_size)


def _font_name() -> str:
    if FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return FONT_NAME

    for font_path in _candidate_font_paths():
        if font_path.is_file():
            pdfmetrics.registerFont(TTFont(FONT_NAME, font_path))
            return FONT_NAME

    return FALLBACK_FONT_NAME


def _candidate_font_paths() -> list[Path]:
    return [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibri.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/local/share/fonts/dejavu/DejaVuSans.ttf"),
        Path("/Library/Fonts/Arial Unicode.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    ]

