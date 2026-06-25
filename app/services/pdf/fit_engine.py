from dataclasses import dataclass


DEFAULT_MIN_FONT_SIZE = 6.0
FONT_SIZE_STEP = 0.5
LINE_HEIGHT_RATIO = 1.2


@dataclass(frozen=True)
class FittedText:
    text: str
    font_size: float
    overflow: bool


def fit_text(
    text: str,
    bbox: tuple[float, float, float, float],
    font_size: float,
    min_font_size: float = DEFAULT_MIN_FONT_SIZE,
) -> FittedText:
    normalized_text = _normalize_text(text)
    normalized_min_font_size = max(min_font_size, 1.0)
    current_font_size = max(font_size, normalized_min_font_size)

    if not normalized_text:
        return FittedText(text="", font_size=current_font_size, overflow=False)

    while current_font_size >= normalized_min_font_size:
        if _fits(normalized_text, bbox, current_font_size):
            return FittedText(
                text=normalized_text,
                font_size=current_font_size,
                overflow=False,
            )

        current_font_size -= FONT_SIZE_STEP

    return FittedText(
        text=normalized_text,
        font_size=normalized_min_font_size,
        overflow=not _fits(normalized_text, bbox, normalized_min_font_size),
    )


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _fits(text: str, bbox: tuple[float, float, float, float], font_size: float) -> bool:
    width = max(0.0, bbox[2] - bbox[0])
    height = max(0.0, bbox[3] - bbox[1])
    if width <= 0 or height <= 0:
        return False

    lines = _wrap_text(text, width, font_size)
    line_height = font_size * LINE_HEIGHT_RATIO
    return len(lines) * line_height <= height


def _wrap_text(text: str, max_width: float, font_size: float) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue

        current_line = words[0]
        for word in words[1:]:
            candidate = f"{current_line} {word}"
            if _text_width(candidate, font_size) <= max_width:
                current_line = candidate
                continue

            lines.extend(_split_oversized_line(current_line, max_width, font_size))
            current_line = word

        lines.extend(_split_oversized_line(current_line, max_width, font_size))

    return lines


def _split_oversized_line(
    text: str,
    max_width: float,
    font_size: float,
) -> list[str]:
    if _text_width(text, font_size) <= max_width:
        return [text]

    lines: list[str] = []
    current_line = ""
    for character in text:
        candidate = f"{current_line}{character}"
        if current_line and _text_width(candidate, font_size) > max_width:
            lines.append(current_line)
            current_line = character
        else:
            current_line = candidate

    if current_line:
        lines.append(current_line)

    return lines


def _text_width(text: str, font_size: float) -> float:
    return sum(_character_width(character) for character in text) * font_size


def _character_width(character: str) -> float:
    if character.isspace():
        return 0.33

    if character in ".,;:!|ijl'`":
        return 0.3

    if character in "MW@#%&":
        return 0.85

    if ord(character) > 0x2E7F:
        return 1.0

    if character.isupper():
        return 0.65

    return 0.55
