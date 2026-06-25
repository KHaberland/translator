from pathlib import Path
from typing import Any

import requests

from desktop_ui.config import API_BASE_URL, REQUEST_TIMEOUT

PDF_MODE_SIMPLE = "simple"
PDF_MODE_LAYOUT = "layout"


class ApiClientError(RuntimeError):
    """Raised when the backend API returns an error or cannot be reached."""


class ApiClient:
    def __init__(
        self,
        base_url: str = API_BASE_URL,
        timeout: int = REQUEST_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def upload(
        self,
        file_path: str,
        source: str,
        target: str,
        pdf_mode: str = PDF_MODE_SIMPLE,
    ) -> dict[str, Any]:
        path = Path(file_path)
        if not path.is_file():
            raise ApiClientError("File does not exist")

        file_type = self._file_type(path)
        url = self._upload_url(file_type, pdf_mode)
        try:
            with path.open("rb") as file_handle:
                response = requests.post(
                    url,
                    files={
                        "file": (
                            path.name,
                            file_handle,
                            self._content_type(file_type),
                        )
                    },
                    data={
                        "source_lang": source,
                        "target_lang": target,
                    },
                    timeout=self.timeout,
                )
        except requests.RequestException as exc:
            raise ApiClientError(self._request_error_message(exc)) from exc

        return self._json_response(response, "Upload failed")

    def estimate(
        self,
        file_path: str,
        source: str,
        target: str,
        pdf_mode: str = PDF_MODE_SIMPLE,
    ) -> dict[str, Any]:
        path = Path(file_path)
        if not path.is_file():
            raise ApiClientError("File does not exist")

        file_type = self._file_type(path)
        estimate_file_type = self._estimate_file_type(file_type, pdf_mode)
        url = f"{self.base_url}/estimate/"
        try:
            with path.open("rb") as file_handle:
                response = requests.post(
                    url,
                    files={
                        "file": (
                            path.name,
                            file_handle,
                            self._content_type(file_type),
                        )
                    },
                    data={
                        "source_lang": source,
                        "target_lang": target,
                        "file_type": estimate_file_type,
                    },
                    timeout=self.timeout,
                )
        except requests.RequestException as exc:
            raise ApiClientError(self._request_error_message(exc)) from exc

        return self._json_response(response, "Estimate failed")

    def get_status(self, job_id: str) -> dict[str, Any]:
        url = f"{self.base_url}/status/{job_id}"
        try:
            response = requests.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ApiClientError(self._request_error_message(exc)) from exc

        return self._json_response(response, "Status request failed")

    def download(
        self,
        job_id: str,
        save_path: str,
        result_file: str | None = None,
    ) -> str:
        url = f"{self.base_url}/download/{job_id}"
        try:
            response = requests.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ApiClientError(self._request_error_message(exc)) from exc

        if not response.ok:
            fallback_message = self._local_result_fallback(response, result_file)
            if fallback_message:
                raise ApiClientError(fallback_message)
            raise ApiClientError(self._error_message(response, "Download failed"))

        destination = Path(save_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)
        return str(destination)

    def _json_response(self, response: requests.Response, fallback: str) -> dict[str, Any]:
        if not response.ok:
            raise ApiClientError(self._error_message(response, fallback))

        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiClientError("Backend returned invalid JSON") from exc

        if not isinstance(payload, dict):
            raise ApiClientError("Backend returned an unexpected response")

        return payload

    def _request_error_message(self, exc: requests.RequestException) -> str:
        if isinstance(exc, requests.Timeout):
            return "Request timed out"
        return "Backend is unavailable"

    def _file_type(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return "pdf"
        if suffix == ".docx":
            return "docx"
        raise ApiClientError("Only DOCX and PDF files are supported")

    def _upload_url(self, file_type: str, pdf_mode: str) -> str:
        if file_type == "docx":
            return f"{self.base_url}/translate/"
        if self._normalized_pdf_mode(pdf_mode) == PDF_MODE_LAYOUT:
            return f"{self.base_url}/translate/pdf-layout"
        return f"{self.base_url}/translate/pdf"

    def _estimate_file_type(self, file_type: str, pdf_mode: str) -> str:
        if file_type != "pdf":
            return file_type
        if self._normalized_pdf_mode(pdf_mode) == PDF_MODE_LAYOUT:
            return "pdf_layout"
        return "pdf"

    def _normalized_pdf_mode(self, pdf_mode: str) -> str:
        if pdf_mode in {PDF_MODE_SIMPLE, PDF_MODE_LAYOUT}:
            return pdf_mode
        raise ApiClientError("Unknown PDF mode")

    def _content_type(self, file_type: str) -> str:
        if file_type == "pdf":
            return "application/pdf"
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    def _error_message(self, response: requests.Response, fallback: str) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = None

        detail = payload.get("detail") if isinstance(payload, dict) else None
        if isinstance(detail, list):
            detail = "; ".join(str(item) for item in detail)
        if detail:
            return self._friendly_detail(str(detail), response.status_code)

        if response.status_code == 409:
            return "Result is not ready"
        if response.status_code == 404:
            return "Job not found"
        if response.status_code >= 500:
            return "Translation failed"

        return f"{fallback}: HTTP {response.status_code}"

    def _local_result_fallback(
        self,
        response: requests.Response,
        result_file: str | None,
    ) -> str | None:
        if response.status_code != 404 or not result_file:
            return None

        try:
            payload = response.json()
        except ValueError:
            payload = None

        detail = payload.get("detail") if isinstance(payload, dict) else None
        if detail == "Not Found":
            return f"Download endpoint is unavailable. Backend result path: {result_file}"
        return None

    def _friendly_detail(self, detail: str, status_code: int) -> str:
        known_details = {
            "invalid DOCX content type": "Only DOCX files are supported",
            "invalid PDF content type": "Only PDF files are supported",
            "only DOCX files are supported": "Only DOCX files are supported",
            "only PDF files are supported": "Only PDF files are supported",
            "source_lang and target_lang must be different": (
                "Source and target languages must be different"
            ),
            "translation job not found": "Job not found",
            "translation result is not ready": "Result is not ready",
            "translation result file not found": "Result file not found",
            "translation provider failed": "Translation failed",
            "failed to process DOCX file": "Translation failed",
            "translation queue is unavailable": "Backend queue is unavailable",
            "file is too large": "File is too large",
            "failed to process PDF file": "Translation failed",
        }
        if detail in known_details:
            return known_details[detail]
        if status_code == 409:
            return "Result is not ready"
        if status_code >= 500:
            return "Translation failed"
        return detail
