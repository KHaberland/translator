from pathlib import Path

from PySide6.QtCore import QThread, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop_ui.core.worker import DownloadWorker, PollingWorker, UploadWorker


LANGUAGES = ["en", "ru", "lv", "lt", "et"]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.selected_file_path: str | None = None
        self.current_job_id: str | None = None
        self.result_file: str | None = None
        self.upload_worker: UploadWorker | None = None
        self.polling_worker: PollingWorker | None = None
        self.download_worker: DownloadWorker | None = None

        self.setWindowTitle("DOCX Translator MVP")
        self.resize(720, 360)

        self.select_file_button = QPushButton("Select DOCX")
        self.file_path_label = QLabel("No file selected")
        self.file_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.file_path_label.setWordWrap(True)

        self.source_language_combo = QComboBox()
        self.source_language_combo.addItems(LANGUAGES)
        self.source_language_combo.setCurrentText("en")

        self.target_language_combo = QComboBox()
        self.target_language_combo.addItems(LANGUAGES)
        self.target_language_combo.setCurrentText("ru")

        self.translate_button = QPushButton("Translate")
        self.translate_button.setEnabled(False)

        self.job_id_value_label = QLabel("-")
        self.job_id_value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.status_value_label = QLabel("idle")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.message_label = QLabel("Select a DOCX file to continue")
        self.message_label.setWordWrap(True)

        self.download_button = QPushButton("Download result")
        self.download_button.setEnabled(False)

        self._build_layout()
        self._connect_signals()
        self._update_validation()

    def _build_layout(self) -> None:
        central_widget = QWidget(self)
        main_layout = QVBoxLayout(central_widget)

        file_layout = QHBoxLayout()
        file_layout.addWidget(self.select_file_button)
        file_layout.addWidget(self.file_path_label, stretch=1)

        form_layout = QFormLayout()
        form_layout.addRow("Source language", self.source_language_combo)
        form_layout.addRow("Target language", self.target_language_combo)
        form_layout.addRow("Job ID", self.job_id_value_label)
        form_layout.addRow("Status", self.status_value_label)

        main_layout.addLayout(file_layout)
        main_layout.addLayout(form_layout)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.message_label)
        main_layout.addWidget(self.translate_button)
        main_layout.addWidget(self.download_button)
        main_layout.addStretch()

        self.setCentralWidget(central_widget)

    def _connect_signals(self) -> None:
        self.select_file_button.clicked.connect(self._select_docx)
        self.source_language_combo.currentTextChanged.connect(self._update_validation)
        self.target_language_combo.currentTextChanged.connect(self._update_validation)
        self.translate_button.clicked.connect(self._start_upload)
        self.download_button.clicked.connect(self._download_result)

    def _select_docx(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select DOCX",
            "",
            "Word documents (*.docx);;All files (*.*)",
        )

        if not file_path:
            return

        self.selected_file_path = file_path
        self.file_path_label.setText(file_path)
        self.current_job_id = None
        self.result_file = None
        self.job_id_value_label.setText("-")
        self.status_value_label.setText("idle")
        self.progress_bar.setValue(0)
        self.download_button.setEnabled(False)
        self._update_validation()

    def _update_validation(self, *_args: object) -> None:
        selected_path = Path(self.selected_file_path) if self.selected_file_path else None
        has_valid_docx = (
            selected_path is not None and selected_path.suffix.lower() == ".docx"
        )
        languages_are_different = (
            self.source_language_combo.currentText()
            != self.target_language_combo.currentText()
        )

        self.translate_button.setEnabled(has_valid_docx and languages_are_different)

        if selected_path is None:
            self.message_label.setText("Select a DOCX file to continue")
        elif not has_valid_docx:
            self.message_label.setText("Only DOCX files are supported")
        elif not languages_are_different:
            self.message_label.setText("Source and target languages must be different")
        else:
            self.message_label.setText("Ready")

    def _start_upload(self, *_args: object) -> None:
        if self.selected_file_path is None:
            self._update_validation()
            return

        self._stop_polling()
        self.current_job_id = None
        self.result_file = None
        self.job_id_value_label.setText("-")
        self.status_value_label.setText("uploading")
        self.progress_bar.setValue(0)
        self.download_button.setEnabled(False)
        self.message_label.setText("Uploading DOCX to backend...")

        self.upload_worker = UploadWorker(
            file_path=self.selected_file_path,
            source_language=self.source_language_combo.currentText(),
            target_language=self.target_language_combo.currentText(),
            parent=self,
        )
        self.upload_worker.started_signal.connect(self._set_uploading_state)
        self.upload_worker.uploaded_signal.connect(self._handle_upload_success)
        self.upload_worker.error_signal.connect(self._handle_upload_error)
        self.upload_worker.finished.connect(self._cleanup_upload_worker)
        self.upload_worker.start()

    def _set_uploading_state(self) -> None:
        self.select_file_button.setEnabled(False)
        self.source_language_combo.setEnabled(False)
        self.target_language_combo.setEnabled(False)
        self.translate_button.setEnabled(False)

    def _handle_upload_success(self, payload: dict) -> None:
        job_id = str(payload.get("job_id", ""))
        status = str(payload.get("status", "queued"))
        if not job_id:
            self._handle_upload_error("Upload response did not include job_id")
            return

        self.current_job_id = job_id
        self.job_id_value_label.setText(job_id or "-")
        self.status_value_label.setText(status)
        self.message_label.setText(
            "Upload completed. Waiting for translation status..."
        )
        self.progress_bar.setValue(0)
        self._start_polling(job_id)

    def _handle_upload_error(self, message: str) -> None:
        self.status_value_label.setText("failed")
        self.message_label.setText(self._friendly_worker_error(message))
        self.download_button.setEnabled(False)
        self._set_idle_state(update_message=False)

    def _set_idle_state(self, update_message: bool = True) -> None:
        current_message = self.message_label.text()
        self.select_file_button.setEnabled(True)
        self.source_language_combo.setEnabled(True)
        self.target_language_combo.setEnabled(True)
        self._update_validation()
        if not update_message:
            self.message_label.setText(current_message)

    def _start_polling(self, job_id: str) -> None:
        self._stop_polling()
        self.polling_worker = PollingWorker(job_id=job_id, parent=self)
        self.polling_worker.status_signal.connect(self._handle_status_update)
        self.polling_worker.progress_signal.connect(self._handle_progress_update)
        self.polling_worker.completed_signal.connect(self._handle_translation_completed)
        self.polling_worker.failed_signal.connect(self._handle_translation_failed)
        self.polling_worker.error_signal.connect(self._handle_polling_error)
        self.polling_worker.finished.connect(self._cleanup_polling_worker)
        self.polling_worker.start()

    def _handle_status_update(self, status: str) -> None:
        status = status or "unknown"
        self.status_value_label.setText(status)
        if status not in {"completed", "failed"}:
            self.message_label.setText(f"Translation status: {status}")

    def _handle_progress_update(self, progress: int) -> None:
        self.progress_bar.setValue(progress)

    def _handle_translation_completed(self, payload: dict) -> None:
        self.result_file = (
            str(payload.get("result_file")) if payload.get("result_file") else None
        )
        self.status_value_label.setText("completed")
        self.progress_bar.setValue(100)
        self.download_button.setEnabled(True)
        self.message_label.setText(
            "Translation completed. Result is ready to download."
        )
        self._set_idle_state(update_message=False)

    def _handle_translation_failed(self, message: str) -> None:
        self.status_value_label.setText("failed")
        self.progress_bar.setValue(100)
        self.download_button.setEnabled(False)
        self.message_label.setText(self._friendly_worker_error(message))
        self._set_idle_state(update_message=False)

    def _handle_polling_error(self, message: str) -> None:
        self.download_button.setEnabled(False)
        self.message_label.setText(self._friendly_worker_error(message))
        self._set_idle_state(update_message=False)

    def _download_result(self, *_args: object) -> None:
        if self.current_job_id is None:
            self.message_label.setText("No completed translation job to download")
            return

        default_path = self._default_download_path()
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save translated DOCX",
            default_path,
            "Word documents (*.docx);;All files (*.*)",
        )
        if not save_path:
            return
        if Path(save_path).suffix.lower() != ".docx":
            save_path = f"{save_path}.docx"

        self.download_worker = DownloadWorker(
            job_id=self.current_job_id,
            save_path=save_path,
            result_file=self.result_file,
            parent=self,
        )
        self.download_worker.started_signal.connect(self._set_downloading_state)
        self.download_worker.downloaded_signal.connect(self._handle_download_success)
        self.download_worker.error_signal.connect(self._handle_download_error)
        self.download_worker.finished.connect(self._cleanup_download_worker)
        self.download_worker.start()

    def _default_download_path(self) -> str:
        if self.selected_file_path:
            source_path = Path(self.selected_file_path)
            target_language = self.target_language_combo.currentText()
            filename = f"{source_path.stem}_translated_to_{target_language}.docx"
        elif self.result_file:
            filename = Path(self.result_file).name
        else:
            filename = "translated.docx"

        base_dir = (
            Path(self.selected_file_path).parent
            if self.selected_file_path
            else Path.home()
        )
        return str(base_dir / filename)

    def _set_downloading_state(self) -> None:
        self.download_button.setEnabled(False)
        self.message_label.setText("Downloading translated DOCX...")

    def _handle_download_success(self, saved_path: str) -> None:
        self.download_button.setEnabled(True)
        self.message_label.setText(f"Downloaded result to {saved_path}")

    def _handle_download_error(self, message: str) -> None:
        self.download_button.setEnabled(True)
        self.message_label.setText(self._friendly_worker_error(message))

    def _friendly_worker_error(self, message: str) -> str:
        known_errors = {
            "failed to process DOCX file": "Translation failed",
            "translation provider failed": "Translation failed",
            "translation result is not ready": "Result is not ready",
        }
        return known_errors.get(message, message or "Translation failed")

    def _stop_polling(self) -> None:
        if self.polling_worker is not None and self.polling_worker.isRunning():
            self.polling_worker.stop()
            self.polling_worker.wait(1000)

    def _cleanup_upload_worker(self) -> None:
        if self.upload_worker is not None:
            self.upload_worker.deleteLater()
            self.upload_worker = None

    def _cleanup_polling_worker(self) -> None:
        if self.polling_worker is not None:
            self.polling_worker.deleteLater()
            self.polling_worker = None

    def _cleanup_download_worker(self) -> None:
        if self.download_worker is not None:
            self.download_worker.deleteLater()
            self.download_worker = None

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._has_blocking_worker():
            QMessageBox.warning(
                self,
                "Operation in progress",
                "Upload or download is still running. Please wait for it to finish before closing the window.",
            )
            event.ignore()
            return

        self._stop_polling()
        super().closeEvent(event)

    def _has_blocking_worker(self) -> bool:
        return self._is_worker_running(self.upload_worker) or self._is_worker_running(
            self.download_worker
        )

    @staticmethod
    def _is_worker_running(worker: QThread | None) -> bool:
        return worker is not None and worker.isRunning()
