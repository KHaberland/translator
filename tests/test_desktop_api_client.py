import pytest
import requests

from desktop_ui.core.api_client import ApiClient, ApiClientError


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
            {"source_lang": "en", "target_lang": "ru"},
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


class _Response:
    def __init__(self, ok: bool, status_code: int, payload: dict) -> None:
        self.ok = ok
        self.status_code = status_code
        self._payload = payload
        self.content = b""

    def json(self) -> dict:
        return self._payload
