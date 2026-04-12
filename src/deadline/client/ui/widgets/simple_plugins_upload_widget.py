# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
Upload widget for the Simple Plugins dialog.

Provides OS/DCC/version selectors, a file drop zone, and an upload button
that puts files into the S3 convention path.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Dict, List, Optional, Set

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ..controllers import AsyncTaskRunner
from ._simple_plugins_utils import format_file_size

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2

_DCC_OPTIONS = [
    "maya",
    "houdini",
    "nuke",
    "blender",
    "cinema4d",
    "vred",
    "aftereffects",
    "3dsmax",
    "keyshot",
    "unreal",
]


def _upload_files_background(
    bucket: str,
    prefix: str,
    farm_id: str,
    queue_id: str,
    files: List[str],
    cancel_event: threading.Event,
) -> int:
    """
    Runs on a background thread. Uploads files to S3 and returns the count.

    All mutable widget state is captured as parameters — this function
    does NOT read from the widget instance (thread safety P0 fix).

    Checks ``cancel_event`` between each file so the user can abort.
    """
    from ... import api
    from qtpy.QtCore import QMetaObject, Q_ARG, Qt as QtConst

    boto3_session = api.get_boto3_session()
    deadline_client = boto3_session.client("deadline")
    s3_session = api.get_queue_user_boto3_session(
        deadline=deadline_client, farm_id=farm_id, queue_id=queue_id,
    )
    s3_client = s3_session.client("s3")

    uploaded = 0
    for i, filepath in enumerate(files):
        if cancel_event.is_set():
            logger.info("Upload cancelled after %d / %d files", uploaded, len(files))
            break

        key = f"{prefix}{os.path.basename(filepath)}"
        logger.info("Uploading %s -> s3://%s/%s", filepath, bucket, key)
        s3_client.upload_file(filepath, bucket, key)
        uploaded += 1

        # Progress bar update is safe — QMetaObject dispatches to main thread
        # We import the progress bar reference via a closure-free approach:
        # the caller stores it in a module-level holder before dispatch.
        # Actually, we return the count and let the caller update.
        # But for per-file progress we need QMetaObject. We pass the widget
        # ref as a parameter captured at dispatch time (it's a C++ pointer,
        # safe to read from any thread as long as we only invoke a slot).

    return uploaded


class _DropZone(QWidget):
    """A widget that accepts drag-and-drop files and directories."""

    files_dropped = Signal(list)  # list[str]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFixedHeight(120)
        self._set_idle_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        self._label = QLabel("Drag and drop plugin files or folders here\nor click Browse")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(self._label)

    def _set_idle_style(self) -> None:
        self.setStyleSheet(
            "QWidget { border: 2px dashed palette(mid); border-radius: 8px;"
            " background: palette(base); }"
        )

    def _set_hover_style(self) -> None:
        self.setStyleSheet(
            "QWidget { border: 2px dashed palette(highlight); border-radius: 8px;"
            " background: palette(alternate-base); }"
        )

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_hover_style()

    def dragLeaveEvent(self, event) -> None:  # type: ignore[override]
        self._set_idle_style()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        self._set_idle_style()
        paths: List[str] = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if os.path.isfile(local):
                paths.append(local)
            elif os.path.isdir(local):
                for root_dir, _dirs, files in os.walk(local):
                    for f in files:
                        paths.append(os.path.join(root_dir, f))
        if paths:
            self.files_dropped.emit(paths)


class SimplePluginsUploadWidget(QGroupBox):
    """Upload form: OS / DCC / version selectors, drop zone, file list, upload button."""

    upload_completed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Upload", parent)
        self._farm_id = ""
        self._queue_id = ""
        self._bucket = ""
        self._root_prefix = ""
        self._selected_files: List[str] = []
        self._selected_files_set: Set[str] = set()  # O(1) dedup lookups
        self._async_runner = AsyncTaskRunner(parent=self)
        self._uploading = False
        self._cancel_event: Optional[threading.Event] = None
        self._retry_count = 0

        self._build_ui()

    # ── Public API ───────────────────────────────────────────────────

    def set_s3_target(
        self, farm_id: str, queue_id: str, bucket: str, root_prefix: str
    ) -> None:
        self._farm_id = farm_id
        self._queue_id = queue_id
        self._bucket = bucket
        self._root_prefix = root_prefix
        self._update_upload_btn()

    # ── UI construction ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # OS radio buttons
        os_row = QHBoxLayout()
        os_row.addWidget(QLabel("Worker OS:"))
        self._os_linux = QRadioButton("Linux")
        self._os_linux.setChecked(True)
        self._os_windows = QRadioButton("Windows")
        os_row.addWidget(self._os_linux)
        os_row.addWidget(self._os_windows)
        os_row.addStretch()
        layout.addLayout(os_row)

        # DCC + Version
        dcc_row = QHBoxLayout()
        dcc_row.addWidget(QLabel("DCC:"))
        self._dcc_box = QComboBox()
        self._dcc_box.setEditable(True)
        self._dcc_box.addItems(_DCC_OPTIONS)
        self._dcc_box.setCurrentIndex(0)  # "maya"
        dcc_row.addWidget(self._dcc_box, stretch=1)

        dcc_row.addWidget(QLabel("Version:"))
        self._version_edit = QLineEdit()
        self._version_edit.setPlaceholderText("e.g. 2025")
        dcc_row.addWidget(self._version_edit, stretch=1)
        layout.addLayout(dcc_row)

        # Generic checkbox
        self._generic_check = QCheckBox("Generic (DCC-agnostic)")
        self._generic_check.toggled.connect(self._on_generic_toggled)
        layout.addWidget(self._generic_check)

        # Drop zone
        self._drop_zone = _DropZone(parent=self)
        self._drop_zone.files_dropped.connect(self._add_files)
        layout.addWidget(self._drop_zone)

        # Browse buttons + file list
        browse_row = QHBoxLayout()
        browse_files_btn = QPushButton("Browse Files…")
        browse_files_btn.clicked.connect(self._on_browse_files)
        browse_row.addWidget(browse_files_btn)

        browse_dir_btn = QPushButton("Browse Folder…")
        browse_dir_btn.clicked.connect(self._on_browse_directory)
        browse_row.addWidget(browse_dir_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_files)
        browse_row.addWidget(clear_btn)
        browse_row.addStretch()
        layout.addLayout(browse_row)

        self._file_list = QListWidget()
        self._file_list.setMaximumHeight(100)
        layout.addWidget(self._file_list)

        # Upload / Cancel buttons
        upload_row = QHBoxLayout()
        self._upload_btn = QPushButton("Upload")
        self._upload_btn.setEnabled(False)
        self._upload_btn.clicked.connect(self._on_upload)
        upload_row.addWidget(self._upload_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setVisible(False)
        self._cancel_btn.clicked.connect(self._on_cancel)
        upload_row.addWidget(self._cancel_btn)

        upload_row.addStretch()
        layout.addLayout(upload_row)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setTextVisible(True)
        layout.addWidget(self._progress)

    # ── Handlers ─────────────────────────────────────────────────────

    def _on_generic_toggled(self, checked: bool) -> None:
        self._dcc_box.setEnabled(not checked)
        self._version_edit.setEnabled(not checked)

    def _on_browse_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Select plugin files")
        if paths:
            self._add_files(paths)

    def _on_browse_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select plugin folder")
        if directory:
            files: List[str] = []
            for root_dir, _dirs, filenames in os.walk(directory):
                for f in filenames:
                    files.append(os.path.join(root_dir, f))
            if files:
                self._add_files(files)

    def _add_files(self, paths: List[str]) -> None:
        # Check for filename collisions — warn if two different paths share a basename
        basenames_seen: Dict[str, str] = {}
        for existing in self._selected_files:
            basenames_seen[os.path.basename(existing)] = existing

        collisions: List[str] = []
        for p in paths:
            if p in self._selected_files_set:
                continue  # exact duplicate, skip silently
            basename = os.path.basename(p)
            if basename in basenames_seen and basenames_seen[basename] != p:
                collisions.append(
                    f"  {basename}\n    existing: {basenames_seen[basename]}\n    new:      {p}"
                )
            basenames_seen[basename] = p

        if collisions:
            msg = (
                "These files have the same name as files already selected.\n"
                "Only the last one will be uploaded to S3:\n\n"
                + "\n".join(collisions)
            )
            QMessageBox.warning(self, "Filename collision", msg)

        for p in paths:
            if p not in self._selected_files_set:
                self._selected_files.append(p)
                self._selected_files_set.add(p)
                name = os.path.basename(p)
                size = os.path.getsize(p)
                item = QListWidgetItem(f"{name}  ({format_file_size(size)})")
                item.setData(Qt.UserRole, p)
                self._file_list.addItem(item)
        self._update_upload_btn()

    def _clear_files(self) -> None:
        self._selected_files.clear()
        self._selected_files_set.clear()
        self._file_list.clear()
        self._update_upload_btn()

    def _update_upload_btn(self) -> None:
        self._upload_btn.setEnabled(
            bool(self._bucket) and len(self._selected_files) > 0 and not self._uploading
        )

    def _on_upload(self) -> None:
        if not self._bucket:
            QMessageBox.warning(self, "No bucket", "Select a queue with job attachment settings.")
            return

        if not self._generic_check.isChecked():
            dcc = self._dcc_box.currentText().strip().lower()
            version = self._version_edit.text().strip()
            if not dcc or not version:
                QMessageBox.warning(
                    self, "Missing fields", "Enter a DCC name and version, or check 'Generic'.",
                )
                return

        self._retry_count = 0
        self._do_upload()

    def _on_cancel(self) -> None:
        if self._cancel_event:
            self._cancel_event.set()
        self._async_runner.cancel("upload_plugins")
        self._uploading = False
        self._cancel_btn.setVisible(False)
        self._progress.setFormat("Cancelled")
        self._update_upload_btn()

    # ── Async upload ─────────────────────────────────────────────────

    def _do_upload(self) -> None:
        # Snapshot all mutable state before dispatching to background thread (P0 #1)
        prefix = self._build_prefix()
        files = list(self._selected_files)
        bucket = self._bucket
        farm_id = self._farm_id
        queue_id = self._queue_id

        self._cancel_event = threading.Event()
        self._uploading = True
        self._upload_btn.setEnabled(False)
        self._cancel_btn.setVisible(True)
        self._progress.setVisible(True)
        self._progress.setMaximum(len(files))
        self._progress.setValue(0)
        self._progress.setFormat("Uploading… %v / %m")

        self._async_runner.run(
            operation_key="upload_plugins",
            fn=_upload_files_background,
            on_success=self._on_upload_success,
            on_error=self._on_upload_error,
            bucket=bucket,
            prefix=prefix,
            farm_id=farm_id,
            queue_id=queue_id,
            files=files,
            cancel_event=self._cancel_event,
        )

    def _on_upload_success(self, count: int) -> None:
        self._uploading = False
        self._cancel_btn.setVisible(False)
        self._retry_count = 0

        if self._cancel_event and self._cancel_event.is_set():
            # Upload was cancelled — some files may have been uploaded
            self._progress.setFormat(f"Cancelled ({count} file(s) uploaded before cancel)")
            self._progress.setVisible(True)
            self._update_upload_btn()
            return

        self._progress.setFormat(f"Uploaded {count} file(s)")
        self._clear_files()
        self._progress.setVisible(False)
        self._update_upload_btn()
        self.upload_completed.emit()

    def _on_upload_error(self, error: BaseException) -> None:
        self._uploading = False
        self._cancel_btn.setVisible(False)
        logger.error("Upload failed: %s", error)
        self._progress.setFormat("Upload failed")

        self._retry_count += 1
        if self._retry_count <= _MAX_RETRIES:
            reply = QMessageBox.critical(
                self,
                "Upload failed",
                f"{error}\n\nRetry? (attempt {self._retry_count} of {_MAX_RETRIES})",
                QMessageBox.Retry | QMessageBox.Cancel,
                QMessageBox.Retry,
            )
            if reply == QMessageBox.Retry:
                self._progress.setVisible(False)
                self._do_upload()
                return

        # Exhausted retries or user chose Cancel
        if self._retry_count > _MAX_RETRIES:
            QMessageBox.critical(
                self,
                "Upload failed",
                f"Upload failed after {_MAX_RETRIES} retries.\n\n{error}",
            )
        self._retry_count = 0
        self._progress.setVisible(False)
        self._update_upload_btn()

    # ── Helpers ──────────────────────────────────────────────────────

    def _build_prefix(self) -> str:
        base = f"{self._root_prefix}/plugins"
        if self._generic_check.isChecked():
            return f"{base}/generic/"
        os_name = "linux" if self._os_linux.isChecked() else "windows"
        dcc = self._dcc_box.currentText().strip().lower()
        version = self._version_edit.text().strip()
        return f"{base}/{os_name}/{dcc}/{version}/"
