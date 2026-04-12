# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
Provides a dialog for uploading, browsing, and removing simple plugin files
for Deadline Cloud render workers.

Example code:
    from deadline.client.ui.dialogs.simple_plugins_dialog import SimplePluginsDialog
    SimplePluginsDialog.show_dialog(farm_id="farm-xxxx")
"""

from __future__ import annotations

import logging
from configparser import ConfigParser
from typing import Any, Optional

from qtpy.QtCore import QSize, Qt
from qtpy.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...config import config_file
from ..deadline_authentication_status import DeadlineAuthenticationStatus
from ..widgets import (
    DeadlineFarmListComboBoxController,
    DeadlineQueueListComboBoxController,
)
from ..controllers import AsyncTaskRunner, DeadlineUIController

logger = logging.getLogger(__name__)

# Cached boto3 session for the dialog lifetime — avoids re-creating on every
# queue change.  Cleared when the module is reloaded (i.e., next dialog open).
_cached_boto3_session = None


def _fetch_queue_attachment_settings(farm_id: str, queue_id: str) -> dict:
    """
    Background-thread helper: calls GetQueue and returns attachment info.
    Raises on failure so AsyncTaskRunner routes to the error callback.
    """
    global _cached_boto3_session
    from ... import api
    from ....job_attachments._aws.deadline import get_queue

    if _cached_boto3_session is None:
        _cached_boto3_session = api.get_boto3_session()

    queue_info = get_queue(
        farm_id=farm_id,
        queue_id=queue_id,
        session=_cached_boto3_session,
    )
    s3_settings = queue_info.jobAttachmentSettings
    if not s3_settings:
        raise RuntimeError(f"Queue {queue_id} has no job attachment settings.")
    return {
        "bucket": s3_settings.s3BucketName,
        "root_prefix": s3_settings.rootPrefix,
        "farm_id": farm_id,
        "queue_id": queue_id,
    }


class SimplePluginsDialog(QDialog):
    """
    A dialog for managing simple plugin files on Deadline Cloud queues.

    Provides farm/queue selection, a file upload form with OS/DCC/version
    targeting, and a browser for viewing and deleting uploaded plugins.
    """

    @staticmethod
    def show_dialog(
        farm_id: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        dialog = SimplePluginsDialog(farm_id=farm_id, parent=parent)
        dialog.exec_()

    def __init__(
        self,
        farm_id: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(
            parent=parent,
            f=Qt.WindowSystemMenuHint | Qt.WindowTitleHint | Qt.WindowCloseButtonHint,
        )
        self.setWindowTitle("Simple Plugins — AWS Deadline Cloud")
        self._farm_id = farm_id or config_file.get_setting("defaults.farm_id")
        self._queue_id: str = ""
        self._bucket: str = ""
        self._root_prefix: str = ""

        # Local config copy so we don't mutate the global config file
        self._config = ConfigParser()
        self._config.read_dict(config_file.read_config())
        if self._farm_id:
            config_file.set_setting("defaults.farm_id", self._farm_id, self._config)

        self._auth_status = DeadlineAuthenticationStatus.getInstance()
        self._controller = DeadlineUIController.getInstance()
        self._async_runner = AsyncTaskRunner(parent=self)

        # Cascade flags — used to auto-load queues after farms finish loading.
        # NOTE: These flags guard against a known race condition. The controller's
        # farms_updated / queues_updated signals are shared across all connected
        # widgets. If another dialog (e.g., DeadlineConfigDialog) triggers a farm
        # refresh concurrently, our handler would fire on their signal. The boolean
        # flags ensure we only act on cascades we initiated. This is the same
        # pattern used by DeadlineConfigDialog._awaiting_farms_for_cascade.
        self._awaiting_farms_for_cascade = False
        self._awaiting_queues_for_cascade = False

        self._build_ui()
        self._connect_signals()
        self._initial_refresh()

    def sizeHint(self) -> QSize:
        return QSize(750, 700)

    # ── UI construction ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # Farm / Queue selectors
        selector_group = QGroupBox("Farm and Queue")
        selector_layout = QVBoxLayout(selector_group)

        farm_row = QHBoxLayout()
        farm_row.addWidget(QLabel("Farm:"))
        self._farm_box = DeadlineFarmListComboBoxController(parent=selector_group)
        farm_row.addWidget(self._farm_box, stretch=1)
        selector_layout.addLayout(farm_row)

        queue_row = QHBoxLayout()
        queue_row.addWidget(QLabel("Queue:"))
        self._queue_box = DeadlineQueueListComboBoxController(parent=selector_group)
        queue_row.addWidget(self._queue_box, stretch=1)
        selector_layout.addLayout(queue_row)

        self._bucket_label = QLabel("")
        selector_layout.addWidget(self._bucket_label)

        root.addWidget(selector_group)

        # Upload + Browser in a splitter
        splitter = QSplitter(Qt.Vertical)

        from ..widgets.simple_plugins_upload_widget import SimplePluginsUploadWidget
        from ..widgets.simple_plugins_browser_widget import SimplePluginsBrowserWidget

        self._upload_widget = SimplePluginsUploadWidget(parent=self)
        self._browser_widget = SimplePluginsBrowserWidget(parent=self)

        splitter.addWidget(self._upload_widget)
        splitter.addWidget(self._browser_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        root.addWidget(splitter, stretch=1)

        # Close button
        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)

    # ── Signals ──────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        self._farm_box.box.currentIndexChanged.connect(self._on_farm_changed)
        self._queue_box.box.currentIndexChanged.connect(self._on_queue_changed)
        self._upload_widget.upload_completed.connect(self._browser_widget.refresh)

        # Listen for controller list-updated signals to cascade farm → queue → resolve
        self._controller.farms_updated.connect(
            self._on_farms_list_updated, Qt.QueuedConnection
        )
        self._controller.queues_updated.connect(
            self._on_queues_list_updated, Qt.QueuedConnection
        )

    def _initial_refresh(self) -> None:
        """Kick off the first data load with cascading: farms → queues → resolve."""
        self._farm_box.set_config(self._config)
        self._queue_box.set_config(self._config)
        self._awaiting_farms_for_cascade = True
        self._farm_box.refresh_list()

    # ── Cascade handlers ─────────────────────────────────────────────

    def _on_farms_list_updated(self, farms_list: list) -> None:
        """After farms load, select the default and kick off queue loading."""
        if not self._awaiting_farms_for_cascade:
            return
        self._awaiting_farms_for_cascade = False

        current_farm_id = self._farm_box.box.currentData()
        if current_farm_id:
            self._farm_id = current_farm_id
            config_file.set_setting("defaults.farm_id", current_farm_id, self._config)
            self._queue_box.set_config(self._config)
            self._awaiting_queues_for_cascade = True
            self._queue_box.refresh_list()

    def _on_queues_list_updated(self, queues_list: list) -> None:
        """After queues load, select the default and resolve attachment settings."""
        if not self._awaiting_queues_for_cascade:
            return
        self._awaiting_queues_for_cascade = False

        current_queue_id = self._queue_box.box.currentData()
        if current_queue_id and current_queue_id != "":
            self._queue_id = current_queue_id
            self._resolve_attachment_settings_async()

    # ── User-driven handlers ─────────────────────────────────────────

    def _on_farm_changed(self, _index: int) -> None:
        farm_id = self._farm_box.box.currentData()
        if not farm_id or farm_id == "":
            return
        self._farm_id = farm_id
        config_file.set_setting("defaults.farm_id", farm_id, self._config)
        config_file.set_setting("defaults.queue_id", "", self._config)
        self._queue_box.set_config(self._config)
        self._awaiting_queues_for_cascade = True
        self._queue_box.refresh_list()

    def _on_queue_changed(self, _index: int) -> None:
        queue_id = self._queue_box.box.currentData()
        if not queue_id or queue_id == "":
            self._set_no_bucket()
            return
        self._queue_id = queue_id
        self._resolve_attachment_settings_async()

    # ── Async queue resolution ───────────────────────────────────────

    def _resolve_attachment_settings_async(self) -> None:
        """Fire off GetQueue in a background thread; show a spinner while loading."""
        self._bucket_label.setText("⏳ Loading attachment settings…")
        self._bucket_label.setStyleSheet("color: #aaa;")
        self._upload_widget.set_s3_target("", "", "", "")
        self._browser_widget.set_s3_target("", "", "", "")

        self._async_runner.run(
            operation_key="resolve_queue_attachments",
            fn=_fetch_queue_attachment_settings,
            on_success=self._on_resolve_success,
            on_error=self._on_resolve_error,
            farm_id=self._farm_id,
            queue_id=self._queue_id,
        )

    def _on_resolve_success(self, result: Any) -> None:
        """Called on the main thread when GetQueue succeeds."""
        self._bucket = result["bucket"]
        self._root_prefix = result["root_prefix"]
        self._bucket_label.setText(
            f"Bucket: s3://{self._bucket}/{self._root_prefix}/plugins/"
        )
        self._bucket_label.setStyleSheet("")

        self._upload_widget.set_s3_target(
            farm_id=result["farm_id"],
            queue_id=result["queue_id"],
            bucket=self._bucket,
            root_prefix=self._root_prefix,
        )
        self._browser_widget.set_s3_target(
            farm_id=result["farm_id"],
            queue_id=result["queue_id"],
            bucket=self._bucket,
            root_prefix=self._root_prefix,
        )
        self._browser_widget.refresh()

    def _on_resolve_error(self, error: BaseException) -> None:
        """Called on the main thread when GetQueue fails."""
        logger.warning("Failed to resolve attachment settings: %s", error)
        self._set_no_bucket(str(error))

    def _set_no_bucket(self, message: str = "") -> None:
        self._bucket = ""
        self._root_prefix = ""
        label = message or "Select a queue with job attachment settings configured."
        self._bucket_label.setText(label)
        self._bucket_label.setStyleSheet("color: orange;")
        self._upload_widget.set_s3_target("", "", "", "")
        self._browser_widget.set_s3_target("", "", "", "")
