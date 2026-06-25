from pathlib import Path

import fitz

from app.models.schemas import DocumentBlock


def extract_pdf_blocks(file_path: str | Path) -> list[DocumentBlock]:
    document = fitz.open(str(file_path))
    try:
        blocks: list[DocumentBlock] = []
        for page_index, page in enumerate(document, start=1):
            _append_page_blocks(blocks, page, page_index)

        return blocks
    finally:
        document.close()


def _append_page_blocks(
    blocks: list[DocumentBlock],
    page: fitz.Page,
    page_number: int,
) -> None:
    text_block_index = 0
    for raw_block in page.get_text("blocks"):
        if len(raw_block) > 6 and raw_block[6] != 0:
            continue

        text = _normalize_text(raw_block[4])
        if not text:
            continue

        text_block_index += 1
        blocks.append(
            DocumentBlock(
                block_id=f"p{page_number}b{text_block_index}",
                text=text,
                location=f"page:{page_number}:block:{text_block_index}",
                metadata={
                    "page": page_number,
                    "source": "pdf",
                },
            )
        )


def _normalize_text(text: str) -> str:
    return " ".join(text.split())

