from pathlib import Path
from typing import Any


REVIEW_FILE_VERSION = 1
REVIEW_FILE_FILTER = "PDF review files (*.pdfreview.json);;JSON files (*.json);;All files (*.*)"


def build_review_file_payload(
    draft: dict[str, Any],
    updates: list[dict[str, Any]],
) -> dict[str, Any]:
    updates_by_id = {str(update.get("block_id", "")): update for update in updates}
    blocks = []
    for block in draft.get("blocks", []):
        if not isinstance(block, dict):
            continue
        update = updates_by_id.get(str(block.get("block_id", "")), {})
        blocks.append(
            {
                **block,
                "translated_text": update.get(
                    "translated_text",
                    block.get("translated_text", ""),
                ),
                "font_size": update.get("font_size", block.get("font_size")),
                "color": update.get("color", block.get("color")),
                "keep_original": update.get(
                    "keep_original",
                    block.get("keep_original", False),
                ),
            }
        )

    return {
        "version": REVIEW_FILE_VERSION,
        "job_id": str(draft.get("job_id", "")),
        "file_type": "pdf_layout",
        "source_pdf_path": str(draft.get("source_pdf_path", "")),
        "original_filename": str(draft.get("original_filename", "source.pdf")),
        "target_lang": str(draft.get("target_lang", "")),
        "blocks": blocks,
    }


def validate_review_file_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Review file is invalid")
    if payload.get("version") != REVIEW_FILE_VERSION:
        raise ValueError("Unsupported review file version")
    if payload.get("file_type") != "pdf_layout":
        raise ValueError("Review file is invalid")
    if not Path(str(payload.get("source_pdf_path", ""))).is_file():
        raise FileNotFoundError("Original PDF not found")

    blocks = payload.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("Review file is invalid")
    for block in blocks:
        _validate_block(block)
    return payload


def _validate_block(block: object) -> None:
    if not isinstance(block, dict) or not block.get("block_id"):
        raise ValueError("Review file is invalid")
    bbox = block.get("bbox")
    if (
        not isinstance(bbox, (list, tuple))
        or len(bbox) != 4
        or not all(isinstance(value, (int, float)) for value in bbox)
    ):
        raise ValueError("Review file is invalid")
    font_size = block.get("font_size")
    if not isinstance(font_size, (int, float)) or font_size <= 0:
        raise ValueError("Review file is invalid")
    color = block.get("color")
    if color is not None and (
        not isinstance(color, (list, tuple))
        or len(color) != 3
        or not all(isinstance(value, (int, float)) and 0 <= value <= 1 for value in color)
    ):
        raise ValueError("Review file is invalid")
