import pytest
import requests

from desktop_ui.core.api_client import ApiClient, ApiClientError
from desktop_ui.ui.review_file import (
    build_review_file_payload,
    validate_review_file_payload,
)
from desktop_ui.ui.review_overflow import text_overflows_original_width


def test_api_client_estimate_returns_dict(tmp_path, monkeypatch):
    docx_path = tmp_path / "source.docx"
    docx_path.write_bytes(b"docx")
    response = _Response(
        ok=True,
        status_code=200,
        payload={
            "estimated_characters": 4,
            "estimated_total_tokens": 2,
            "estimated_cost_usd": 0.0001,
            "budget_status": "ok",
        },
    )
    calls = []

    def fake_post(url, files, data, timeout):
        calls.append((url, data, timeout))
        return response

    monkeypatch.setattr(requests, "post", fake_post)

    payload = ApiClient(base_url="http://backend", timeout=5).estimate(
        str(docx_path),
        "en",
        "ru",
    )

    assert payload == response._payload
    assert calls == [
        (
            "http://backend/estimate/",
            {"source_lang": "en", "target_lang": "ru", "file_type": "docx"},
            5,
        )
    ]


def test_api_client_upload_docx_uses_legacy_endpoint(tmp_path, monkeypatch):
    docx_path = tmp_path / "source.docx"
    docx_path.write_bytes(b"docx")
    response = _Response(
        ok=True,
        status_code=200,
        payload={"job_id": "job-1", "status": "queued"},
    )
    calls = []

    def fake_post(url, files, data, timeout):
        file_name, _file_handle, content_type = files["file"]
        calls.append((url, file_name, content_type, data, timeout))
        return response

    monkeypatch.setattr(requests, "post", fake_post)

    payload = ApiClient(base_url="http://backend", timeout=5).upload(
        str(docx_path),
        "en",
        "ru",
    )

    assert payload == response._payload
    assert calls == [
        (
            "http://backend/translate/",
            "source.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            {"source_lang": "en", "target_lang": "ru"},
            5,
        )
    ]


def test_api_client_upload_pdf_uses_pdf_endpoint(tmp_path, monkeypatch):
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"pdf")
    response = _Response(
        ok=True,
        status_code=200,
        payload={"job_id": "job-1", "status": "queued", "file_type": "pdf"},
    )
    calls = []

    def fake_post(url, files, data, timeout):
        file_name, _file_handle, content_type = files["file"]
        calls.append((url, file_name, content_type, data, timeout))
        return response

    monkeypatch.setattr(requests, "post", fake_post)

    payload = ApiClient(base_url="http://backend", timeout=5).upload(
        str(pdf_path),
        "en",
        "ru",
    )

    assert payload == response._payload
    assert calls == [
        (
            "http://backend/translate/pdf",
            "source.pdf",
            "application/pdf",
            {"source_lang": "en", "target_lang": "ru"},
            5,
        )
    ]


def test_api_client_upload_layout_pdf_uses_layout_endpoint(tmp_path, monkeypatch):
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"pdf")
    response = _Response(
        ok=True,
        status_code=200,
        payload={"job_id": "job-1", "status": "queued", "file_type": "pdf_layout"},
    )
    calls = []

    def fake_post(url, files, data, timeout):
        file_name, _file_handle, content_type = files["file"]
        calls.append((url, file_name, content_type, data, timeout))
        return response

    monkeypatch.setattr(requests, "post", fake_post)

    payload = ApiClient(base_url="http://backend", timeout=5).upload(
        str(pdf_path),
        "en",
        "ru",
        pdf_mode="layout",
    )

    assert payload == response._payload
    assert calls == [
        (
            "http://backend/translate/pdf-layout",
            "source.pdf",
            "application/pdf",
            {"source_lang": "en", "target_lang": "ru"},
            5,
        )
    ]


def test_api_client_estimate_pdf_sends_file_type(tmp_path, monkeypatch):
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"pdf")
    response = _Response(
        ok=True,
        status_code=200,
        payload={
            "estimated_characters": 3,
            "estimated_total_tokens": 2,
            "estimated_cost_usd": 0.0001,
            "budget_status": "ok",
        },
    )
    calls = []

    def fake_post(url, files, data, timeout):
        file_name, _file_handle, content_type = files["file"]
        calls.append((url, file_name, content_type, data, timeout))
        return response

    monkeypatch.setattr(requests, "post", fake_post)

    payload = ApiClient(base_url="http://backend", timeout=5).estimate(
        str(pdf_path),
        "en",
        "ru",
    )

    assert payload == response._payload
    assert calls == [
        (
            "http://backend/estimate/",
            "source.pdf",
            "application/pdf",
            {"source_lang": "en", "target_lang": "ru", "file_type": "pdf"},
            5,
        )
    ]


def test_api_client_estimate_layout_pdf_sends_layout_file_type(tmp_path, monkeypatch):
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"pdf")
    response = _Response(
        ok=True,
        status_code=200,
        payload={
            "estimated_characters": 3,
            "estimated_total_tokens": 2,
            "estimated_cost_usd": 0.0001,
            "budget_status": "ok",
        },
    )
    calls = []

    def fake_post(url, files, data, timeout):
        file_name, _file_handle, content_type = files["file"]
        calls.append((url, file_name, content_type, data, timeout))
        return response

    monkeypatch.setattr(requests, "post", fake_post)

    payload = ApiClient(base_url="http://backend", timeout=5).estimate(
        str(pdf_path),
        "en",
        "ru",
        pdf_mode="layout",
    )

    assert payload == response._payload
    assert calls == [
        (
            "http://backend/estimate/",
            "source.pdf",
            "application/pdf",
            {"source_lang": "en", "target_lang": "ru", "file_type": "pdf_layout"},
            5,
        )
    ]


def test_api_client_estimate_backend_error_is_short_message(tmp_path, monkeypatch):
    docx_path = tmp_path / "source.docx"
    docx_path.write_bytes(b"docx")

    def fake_post(url, files, data, timeout):
        return _Response(
            ok=False,
            status_code=400,
            payload={"detail": "source_lang and target_lang must be different"},
        )

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(
        ApiClientError,
        match="Source and target languages must be different",
    ):
        ApiClient(base_url="http://backend").estimate(str(docx_path), "en", "en")


def test_api_client_estimate_timeout_is_short_message(tmp_path, monkeypatch):
    docx_path = tmp_path / "source.docx"
    docx_path.write_bytes(b"docx")

    def fake_post(url, files, data, timeout):
        raise requests.Timeout("timeout")

    monkeypatch.setattr(requests, "post", fake_post)

    with pytest.raises(ApiClientError, match="Request timed out"):
        ApiClient(base_url="http://backend").estimate(str(docx_path), "en", "ru")


def test_api_client_build_from_review_file_posts_review_payload(monkeypatch):
    response = _Response(
        ok=True,
        status_code=200,
        payload={"status": "completed", "result_file": "outputs/result.pdf"},
    )
    calls = []

    def fake_post(url, json, timeout):
        calls.append((url, json, timeout))
        return response

    monkeypatch.setattr(requests, "post", fake_post)

    payload = ApiClient(base_url="http://backend", timeout=5).build_from_review_file(
        {"version": 1, "file_type": "pdf_layout", "blocks": []}
    )

    assert payload == response._payload
    assert calls == [
        (
            "http://backend/review/build-from-file",
            {"review": {"version": 1, "file_type": "pdf_layout", "blocks": []}},
            5,
        )
    ]


def test_build_review_file_payload_preserves_manual_edits(tmp_path):
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"%PDF-1.4\n")
    payload = build_review_file_payload(
        {
            "job_id": "job-1",
            "source_pdf_path": str(source_path),
            "original_filename": "source.pdf",
            "target_lang": "ru",
            "blocks": [
                {
                    "block_id": "p0l1",
                    "page": 0,
                    "source_text": "Original",
                    "translated_text": "Auto",
                    "bbox": [0.0, 0.0, 100.0, 12.0],
                    "font_size": 12.0,
                    "color": [0.0, 0.0, 0.0],
                    "translatable": True,
                    "keep_original": False,
                }
            ],
        },
        [
            {
                "block_id": "p0l1",
                "translated_text": "Manual",
                "font_size": 10.5,
                "color": [1.0, 0.0, 0.0],
                "keep_original": True,
            }
        ],
    )

    restored = validate_review_file_payload(payload)

    assert restored["version"] == 1
    assert restored["blocks"][0]["translated_text"] == "Manual"
    assert restored["blocks"][0]["font_size"] == 10.5
    assert restored["blocks"][0]["color"] == [1.0, 0.0, 0.0]
    assert restored["blocks"][0]["keep_original"] is True


def test_review_overflow_allows_text_inside_original_width():
    assert text_overflows_original_width(
        text="Short",
        bbox=(0.0, 0.0, 100.0, 12.0),
        font_size=12.0,
    ) is False


def test_review_overflow_detects_text_longer_than_original_width():
    assert text_overflows_original_width(
        text="This translated text is too long",
        bbox=(0.0, 0.0, 80.0, 12.0),
        font_size=12.0,
    ) is True


def test_review_overflow_ignores_invalid_geometry():
    assert text_overflows_original_width(
        text="Long text",
        bbox=None,
        font_size=12.0,
    ) is False


class _Response:
    def __init__(self, ok: bool, status_code: int, payload: dict) -> None:
        self.ok = ok
        self.status_code = status_code
        self._payload = payload
        self.content = b""

    def json(self) -> dict:
        return self._payload
