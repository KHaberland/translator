AVERAGE_CHARACTER_WIDTH_FACTOR = 0.55


def text_overflows_original_width(
    text: str,
    bbox: object,
    font_size: float,
) -> bool:
    available_width = _bbox_width(bbox)
    if available_width <= 0 or font_size <= 0:
        return False

    estimated_width = len(text) * font_size * AVERAGE_CHARACTER_WIDTH_FACTOR
    return estimated_width > available_width


def _bbox_width(bbox: object) -> float:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return 0.0
    try:
        x0 = float(bbox[0])
        x1 = float(bbox[2])
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, x1 - x0)
