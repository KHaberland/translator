import logging
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.api.translate import _validate_docx_file, _validate_pdf_file
from app.core.config import get_settings
from app.models.schemas import EstimateResponse, LanguageCode
from app.services.cost_estimator import estimate_translation_cost, unique_translatable_blocks
from app.services.docx_parser import extract_docx_blocks
from app.services.pdf.layout_parser import extract_pdf_layout_blocks
from app.services.pdf.parser import extract_pdf_blocks
from app.services.pdf.translator import pdf_text_blocks_to_document_blocks
from app.services.price_estimator import (
    budget_status,
    estimate_output_tokens,
    estimate_translation_cost_usd,
)

router = APIRouter(prefix="/estimate", tags=["estimate"])
logger = logging.getLogger(__name__)


@router.post("/", response_model=EstimateResponse)
async def estimate_docx(
    file: UploadFile = File(...),
    source_lang: LanguageCode = Form(...),
    target_lang: LanguageCode = Form(...),
    file_type: Literal["docx", "pdf", "pdf_layout"] = Form("docx"),
) -> EstimateResponse:
    if source_lang == target_lang:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_lang and target_lang must be different",
        )

    if file_type in {"pdf", "pdf_layout"}:
        _validate_pdf_file(file)
    else:
        _validate_docx_file(file)

    settings = get_settings()
    content = await file.read()
    tmp_path = _save_tmp_file(
        content=content,
        filename=file.filename or "document.docx",
        max_file_size_bytes=settings.max_file_size_bytes,
    )

    try:
        if file_type == "pdf_layout":
            blocks = pdf_text_blocks_to_document_blocks(extract_pdf_layout_blocks(tmp_path))
            cost_blocks = unique_translatable_blocks(blocks)
        elif file_type == "pdf":
            blocks = extract_pdf_blocks(tmp_path)
            cost_blocks = blocks
        else:
            blocks = extract_docx_blocks(tmp_path)
            cost_blocks = blocks
    except Exception as exc:
        logger.warning(
            "estimate status=failed file=%s file_type=%s reason=document_processing",
            tmp_path.name,
            file_type,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"failed to process {file_type.upper()} file",
        ) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    token_estimate = estimate_translation_cost(cost_blocks)
    input_tokens = token_estimate.estimated_tokens
    output_tokens = estimate_output_tokens(
        input_tokens,
        settings.estimated_output_token_multiplier,
    )
    cost_usd = estimate_translation_cost_usd(input_tokens, output_tokens, settings)
    translatable_blocks = sum(1 for block in cost_blocks if block.translatable)
    skipped_blocks = len(blocks) - translatable_blocks

    logger.info(
        "estimate status=ok file=%s file_type=%s characters=%s tokens=%s cost=%s",
        file.filename or tmp_path.name,
        file_type,
        token_estimate.translatable_characters,
        input_tokens + output_tokens,
        cost_usd,
    )
    return EstimateResponse(
        file_name=file.filename or tmp_path.name,
        source_lang=source_lang,
        target_lang=target_lang,
        translatable_blocks=translatable_blocks,
        skipped_blocks=skipped_blocks,
        estimated_characters=token_estimate.translatable_characters,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=output_tokens,
        estimated_total_tokens=input_tokens + output_tokens,
        estimated_cost_usd=cost_usd,
        budget_usd=settings.translation_budget_usd,
        budget_status=budget_status(cost_usd, settings.translation_budget_usd),
    )


def _save_tmp_file(
    content: bytes,
    filename: str,
    max_file_size_bytes: int,
) -> Path:
    if len(content) > max_file_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="file is too large",
        )

    tmp_dir = get_settings().tmp_dir
    tmp_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower() or ".docx"
    tmp_path = tmp_dir / f"estimate_{uuid4().hex}{suffix}"
    tmp_path.write_bytes(content)
    return tmp_path
