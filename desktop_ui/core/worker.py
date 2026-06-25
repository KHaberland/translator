from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from desktop_ui.config import POLL_INTERVAL
from desktop_ui.core.api_client import ApiClient, ApiClientError, PDF_MODE_SIMPLE


class UploadWorker(QThread):
    started_signal = Signal()
    uploaded_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(
        self,
        file_path: str,
        source_language: str,
        target_language: str,
        pdf_mode: str = PDF_MODE_SIMPLE,
        api_client: ApiClient | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.file_path = file_path
        self.source_language = source_language
        self.target_language = target_language
        self.pdf_mode = pdf_mode
        self.api_client = api_client or ApiClient()

    def run(self) -> None:
        self.started_signal.emit()
        try:
            payload: dict[str, Any] = self.api_client.upload(
                self.file_path,
                self.source_language,
                self.target_language,
                self.pdf_mode,
            )
        except ApiClientError as exc:
            self.error_signal.emit(str(exc))
            return
        except Exception as exc:
            self.error_signal.emit(f"Unexpected upload error: {exc}")
            return

        self.uploaded_signal.emit(payload)


class EstimateWorker(QThread):
    started_signal = Signal()
    estimated_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(
        self,
        file_path: str,
        source_language: str,
        target_language: str,
        pdf_mode: str = PDF_MODE_SIMPLE,
        api_client: ApiClient | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.file_path = file_path
        self.source_language = source_language
        self.target_language = target_language
        self.pdf_mode = pdf_mode
        self.api_client = api_client or ApiClient()

    def run(self) -> None:
        self.started_signal.emit()
        try:
            payload: dict[str, Any] = self.api_client.estimate(
                self.file_path,
                self.source_language,
                self.target_language,
                self.pdf_mode,
            )
        except ApiClientError as exc:
            self.error_signal.emit(str(exc))
            return
        except Exception as exc:
            self.error_signal.emit(f"Unexpected estimate error: {exc}")
            return

        self.estimated_signal.emit(payload)


class PollingWorker(QThread):
    status_signal = Signal(str)
    progress_signal = Signal(int)
    completed_signal = Signal(dict)
    failed_signal = Signal(str)
    error_signal = Signal(str)

    def __init__(
        self,
        job_id: str,
        api_client: ApiClient | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.job_id = job_id
        self.api_client = api_client or ApiClient()
        self._stop_requested = False

    def stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        while not self._stop_requested:
            try:
                payload: dict[str, Any] = self.api_client.get_status(self.job_id)
            except ApiClientError as exc:
                self.error_signal.emit(str(exc))
                return
            except Exception as exc:
                self.error_signal.emit(f"Unexpected polling error: {exc}")
                return

            status = str(payload.get("status", ""))
            progress = payload.get("progress", 0)
            self.status_signal.emit(status)
            if isinstance(progress, int):
                self.progress_signal.emit(progress)

            if status == "completed":
                self.completed_signal.emit(payload)
                return
            if status == "failed":
                error = payload.get("error")
                self.failed_signal.emit(
                    str(error) if error else "Translation failed"
                )
                return

            self.msleep(POLL_INTERVAL * 1000)


class DownloadWorker(QThread):
    started_signal = Signal()
    downloaded_signal = Signal(str)
    error_signal = Signal(str)

    def __init__(
        self,
        job_id: str,
        save_path: str,
        result_file: str | None = None,
        api_client: ApiClient | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.job_id = job_id
        self.save_path = save_path
        self.result_file = result_file
        self.api_client = api_client or ApiClient()

    def run(self) -> None:
        self.started_signal.emit()
        try:
            saved_path = self.api_client.download(
                self.job_id,
                self.save_path,
                self.result_file,
            )
        except ApiClientError as exc:
            self.error_signal.emit(str(exc))
            return
        except Exception as exc:
            self.error_signal.emit(f"Unexpected download error: {exc}")
            return

        self.downloaded_signal.emit(saved_path)
