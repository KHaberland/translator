import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz

from app.services.docx_parser import TECHNICAL_TEXT_RE


URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
CERTIFICATE_RE = re.compile(r"\b(?:EN\s+ISO|ISO|DIN|AWS|ASME)\s+\d[\w:./-]*\b", re.IGNORECASE)
DRAWING_RE = re.compile(r"\b(?:DWG|DRW|DRAWING|PLAN|SCHEME)[-_\s]?\d[\w.-]*\b", re.IGNORECASE)
ARTICLE_RE = re.compile(r"\b(?:ART|ARTICLE|ITEM|SKU|PN|P/N)[-:\s]?[A-Z0-9][A-Z0-9_.-]*\b", re.IGNORECASE)


@dataclass(frozen=True)
class PDFTextBlock:
    block_id: str
    text: str
    page: int
    bbox: tuple[float, float, float, float]
    font_size: float
    font_name: str | None
    translatable: bool
    color: tuple[float, float, float] | None = None


def extract_pdf_layout_blocks(file_path: str | Path) -> list[PDFTextBlock]:
    document = fitz.open(str(file_path))
    try:
        blocks: list[PDFTextBlock] = []
        for page_index, page in enumerate(document):
            _append_page_lines(blocks, page, page_index)

        return blocks
    finally:
        document.close()


def _append_page_lines(
    blocks: list[PDFTextBlock],
    page: fitz.Page,
    page_index: int,
) -> None:
    line_index = 0
    raw_page = page.get_text("rawdict")
    for raw_block in raw_page.get("blocks", []):
        if raw_block.get("type") != 0:
            continue

        for raw_line in raw_block.get("lines", []):
            text = _normalize_text(_line_text(raw_line))
            if not text:
                continue

            line_index += 1
            font_size, font_name = _line_font(raw_line)
            blocks.append(
                PDFTextBlock(
                    block_id=f"p{page_index}l{line_index}",
                    text=text,
                    page=page_index,
                    bbox=_line_bbox(raw_line),
                    font_size=font_size,
                    font_name=font_name,
                    translatable=_is_translatable(text, page_index + 1),
                    color=_line_color(raw_line),
                )
            )


def _line_text(raw_line: dict[str, Any]) -> str:
    return "".join(_span_text(span) for span in raw_line.get("spans", []))


def _span_text(raw_span: dict[str, Any]) -> str:
    chars = raw_span.get("chars")
    if isinstance(chars, list):
        return "".join(str(char.get("c", "")) for char in chars if isinstance(char, dict))

    return str(raw_span.get("text", ""))


def _line_bbox(raw_line: dict[str, Any]) -> tuple[float, float, float, float]:
    bbox = raw_line.get("bbox")
    if _is_bbox(bbox):
        return tuple(float(value) for value in bbox)

    for span in raw_line.get("spans", []):
        span_bbox = span.get("bbox")
        if _is_bbox(span_bbox):
            return tuple(float(value) for value in span_bbox)

    return (0.0, 0.0, 0.0, 0.0)


def _is_bbox(value: object) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 4
        and all(isinstance(item, (int, float)) for item in value)
    )


def _line_font(raw_line: dict[str, Any]) -> tuple[float, str | None]:
    for span in raw_line.get("spans", []):
        if not _normalize_text(_span_text(span)):
            continue

        font_size = span.get("size", 0.0)
        font_name = span.get("font")
        return (
            float(font_size) if isinstance(font_size, (int, float)) else 0.0,
            font_name if isinstance(font_name, str) and font_name else None,
        )

    return 0.0, None


def _line_color(raw_line: dict[str, Any]) -> tuple[float, float, float] | None:
    for span in raw_line.get("spans", []):
        if not _normalize_text(_span_text(span)):
            continue

        color = span.get("color")
        if isinstance(color, int):
            return _rgb_from_int(color)

    return None


def _rgb_from_int(value: int) -> tuple[float, float, float]:
    red = ((value >> 16) & 255) / 255
    green = ((value >> 8) & 255) / 255
    blue = (value & 255) / 255
    return red, green, blue


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _is_translatable(text: str, page_number: int) -> bool:
    if not any(character.isalpha() for character in text):
        return False

    if _looks_like_page_number(text, page_number):
        return False

    if URL_RE.fullmatch(text) or EMAIL_RE.fullmatch(text):
        return False

    if TECHNICAL_TEXT_RE.fullmatch(text):
        return False

    if (
        CERTIFICATE_RE.fullmatch(text)
        or DRAWING_RE.fullmatch(text)
        or ARTICLE_RE.fullmatch(text)
    ):
        return False

    return True


def _looks_like_page_number(text: str, page_number: int) -> bool:
    normalized = text.strip()
    return normalized in {
        str(page_number),
        f"- {page_number} -",
        f"Page {page_number}",
        f"PAGE {page_number}",
    } or bool(re.fullmatch(rf"{page_number}\s*/\s*\d+", normalized))
