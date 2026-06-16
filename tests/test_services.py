import asyncio
from types import SimpleNamespace

import pytest
from docx import Document
from fastapi import HTTPException

from app.api.translate import translate_docx
from app.core.config import Settings
from app.models.schemas import DocumentBlock, LanguageCode
from app.services.builder import build_translated_docx
from app.services.cost_estimator import estimate_translation_cost
from app.services.docx_parser import extract_docx_blocks
from app.services.segmenter import build_translation_batches
from app.services.translator import translate_docx_file
from app.services.translation_cache import TranslationCache, normalize_translation_cache_text


def test_extract_docx_blocks_from_paragraphs_and_tables(tmp_path):
    source_path = tmp_path / "source.docx"
    document = Document()
    document.add_paragraph("Document title")
    document.add_paragraph("")
    document.add_paragraph("API123")
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "Table text"
    document.save(source_path)

    blocks = extract_docx_blocks(source_path)

    assert [block.block_id for block in blocks] == ["p1", "p3", "t1r1c1p1"]
    assert blocks[0].text == "Document title"
    assert blocks[1].translatable is False
    assert blocks[2].location == "table:1:row:1:cell:1:paragraph:1"


def test_build_translated_docx_replaces_paragraphs_and_table_cells(tmp_path):
    source_path = tmp_path / "source.docx"
    output_path = tmp_path / "output.docx"
    document = Document()
    document.add_paragraph("Hello")
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "World"
    document.save(source_path)

    build_translated_docx(
        source_path,
        output_path,
        {
            "p1": "Привет",
            "t1r1c1p1": "Мир",
        },
    )

    result = Document(output_path)
    assert result.paragraphs[0].text == "Привет"
    assert result.tables[0].cell(0, 0).text == "Мир"


def test_translation_cache_normalizes_repeated_text():
    cache = TranslationCache(LanguageCode.EN, LanguageCode.RU)
    first_block = _block("b1", " Repeated   text ")
    second_block = _block("b2", "Repeated text")

    assert normalize_translation_cache_text(" Repeated   text ") == "Repeated text"
    assert cache.original_block_id_for(first_block) is None
    assert cache.original_block_id_for(second_block) == "b1"

    cache.remember_translation(first_block.text, "Повторяющийся текст")
    assert cache.translation_for(second_block.text) == "Повторяющийся текст"


def test_segmenter_respects_batch_limits_and_skips_non_translatable_blocks():
    blocks = [
        _block("b1", "12345"),
        _block("b2", "1234"),
        _block("b3", "skip", translatable=False),
        _block("b4", "12"),
    ]

    batches = build_translation_batches(blocks, max_batch_chars=6, max_batch_blocks=2)

    assert [[block.block_id for block in batch] for batch in batches] == [
        ["b1"],
        ["b2", "b4"],
    ]


def test_segmenter_rejects_single_block_over_char_limit():
    with pytest.raises(ValueError, match="exceeds max_batch_chars"):
        build_translation_batches(
            [_block("b1", "too long")],
            max_batch_chars=3,
            max_batch_blocks=10,
        )


def test_cost_estimator_counts_only_translatable_blocks():
    estimate = estimate_translation_cost(
        [
            _block("b1", "12345678"),
            _block("b2", "ignored", translatable=False),
        ]
    )

    assert estimate.translatable_characters == 8
    assert estimate.estimated_tokens == 2


def test_translate_endpoint_rejects_equal_languages_before_reading_file():
    file = SimpleNamespace(filename="document.docx")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            translate_docx(
                file=file,
                source_lang=LanguageCode.EN,
                target_lang=LanguageCode.EN,
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "source_lang and target_lang must be different"


def test_translate_endpoint_rejects_non_docx_file():
    file = SimpleNamespace(filename="document.txt", content_type="text/plain")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            translate_docx(
                file=file,
                source_lang=LanguageCode.EN,
                target_lang=LanguageCode.RU,
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "only DOCX files are supported"


def test_translate_endpoint_rejects_invalid_docx_content_type():
    file = SimpleNamespace(filename="document.docx", content_type="text/plain")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            translate_docx(
                file=file,
                source_lang=LanguageCode.EN,
                target_lang=LanguageCode.RU,
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "invalid DOCX content type"


def test_translate_docx_file_uses_mock_ai_without_api_key(tmp_path):
    source_path = tmp_path / "source.docx"
    output_dir = tmp_path / "outputs"
    document = Document()
    document.add_paragraph("Hello")
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "World"
    document.save(source_path)

    result = asyncio.run(
        translate_docx_file(
            source_path=source_path,
            original_filename="source.docx",
            source_lang=LanguageCode.EN,
            target_lang=LanguageCode.RU,
            settings=Settings(
                mock_ai_enabled=True,
                output_dir=output_dir,
                upload_dir=tmp_path / "uploads",
                tmp_dir=tmp_path / "tmp",
            ),
        )
    )

    translated_document = Document(result.file_path)
    assert result.status == "completed"
    assert result.file_name == "source_translated_to_ru.docx"
    assert translated_document.paragraphs[0].text == "Hello [ru]"
    assert translated_document.tables[0].cell(0, 0).text == "World [ru]"


def _block(block_id: str, text: str, translatable: bool = True) -> DocumentBlock:
    return DocumentBlock(
        block_id=block_id,
        text=text,
        location=f"test:{block_id}",
        translatable=translatable,
    )
