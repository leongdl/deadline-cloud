# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
Browser widget for the Simple Plugins dialog.

Lists plugin files currently uploaded to the S3 convention path,
grouped by OS > DCC > version, and supports deletion.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..controllers import AsyncTaskRunner
from ._simple_plugins_utils import format_file_size

logger = logging.getLogger(__name__)


def _list_plugins_background(
    farm_id: str, queue_id: str, bucket: str, root_prefix: str
) -> Dict[str, Any]:
    """Background thread: list S3 objects under the plugins/ prefix."""
    from ... import api

    prefix = f"{root_prefix}/plugins/"
    boto3_session = api.get_boto3_session()
    deadline_client = boto3_session.client("deadline")
    s3_session = api.get_queue_user_boto3_session(
        deadline=deadline_client, farm_id=farm_id, queue_id=queue_id,
    )
    s3_client = s3_session.client("s3")

    paginator = s3_client.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=bucket, Prefix=prefix)

    groups: Dict[str, List[Tuple[str, int, datetime]]] = {}
    total_files = 0
    total_size = 0

    for page in pages:
        for obj in page.get("Contents", []):
            key: str = obj["Key"]
            relative = key[len(prefix):]
            if not relative or relative.endswith("/"):
                continue
            parts = relative.rsplit("/", 1)
            if len(parts) == 2:
                group_path, filename = parts
            else:
                group_path, filename = "", parts[0]
            size: int = obj.get("Size", 0)
            last_modified: datetime = obj.get("LastModified", datetime.now(timezone.utc))
            groups.setdefault(group_path, []).append((filename, size, last_modified))
            total_files += 1
            total_size += size

    return {"groups": groups, "total_files": total_files, "total_size": total_size}


def _delete_plugins_background(
    farm_id: str, queue_id: str, bucket: str, keys: List[str]
) -> int:
    """Background thread: delete S3 objects."""
    from ... import api

    boto3_session = api.get_boto3_session()
    deadline_client = boto3_session.client("deadline")
    s3_session = api.get_queue_user_boto3_session(
        deadline=deadline_client, farm_id=farm_id, queue_id=queue_id,
    )
    s3_client = s3_session.client("s3")

    errors: List[str] = []
    for i in range(0, len(keys), 1000):
        batch = keys[i : i + 1000]
        response = s3_client.delete_objects(
            Bucket=bucket, Delete={"Objects": [{"Key": k} for k in batch]},
        )
        # S3 delete_objects returns errors per-key in the response body
        for err in response.get("Errors", []):
            errors.append(f"{err.get('Key', '?')}: {err.get('Message', 'unknown error')}")

    if errors:
        raise RuntimeError(
            f"Failed to delete {len(errors)} file(s):\n" + "\n".join(errors[:5])
        )
    return len(keys)


class SimplePluginsBrowserWidget(QGroupBox):
    """Tree view of uploaded plugins with async load/delete and folder-level select."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Uploaded Plugins", parent)
        self._farm_id = ""
        self._queue_id = ""
        self._bucket = ""
        self._root_prefix = ""
        self._async_runner = AsyncTaskRunner(parent=self)

        self._build_ui()

    # ── Public API ───────────────────────────────────────────────────

    def set_s3_target(
        self, farm_id: str, queue_id: str, bucket: str, root_prefix: str
    ) -> None:
        self._farm_id = farm_id
        self._queue_id = queue_id
        self._bucket = bucket
        self._root_prefix = root_prefix
        self._delete_btn.setEnabled(False)
        self._tree.clear()

    def refresh(self) -> None:
        """Reload the plugin list from S3 asynchronously."""
        if not self._bucket:
            self._tree.clear()
            self._status_label.setText("")
            return
        logger.info("Refreshing plugin browser for bucket=%s", self._bucket)
        self._status_label.setText("⏳ Loading…")
        self._tree.clear()
        self._async_runner.run(
            operation_key="list_plugins",
            fn=_list_plugins_background,
            on_success=self._on_list_success,
            on_error=self._on_list_error,
            farm_id=self._farm_id,
            queue_id=self._queue_id,
            bucket=self._bucket,
            root_prefix=self._root_prefix,
        )

    # ── UI construction ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Name", "Size", "Last Modified"])
        self._tree.setColumnCount(3)
        self._tree.setMinimumHeight(250)
        header = self._tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._tree.itemChanged.connect(self._on_check_changed)
        self._tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._tree, stretch=1)

        btn_row = QHBoxLayout()
        self._delete_btn = QPushButton("Delete Selected")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(self._delete_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        btn_row.addWidget(refresh_btn)

        btn_row.addStretch()

        self._status_label = QLabel("")
        btn_row.addWidget(self._status_label)

        layout.addLayout(btn_row)

    # ── Async callbacks ──────────────────────────────────────────────

    def _on_list_success(self, result: Dict[str, Any]) -> None:
        self._populate_tree(result["groups"])
        total = result["total_files"]
        size = result["total_size"]
        self._status_label.setText(f"{total} file(s), {format_file_size(size)}")

    def _on_list_error(self, error: BaseException) -> None:
        logger.error("Failed to list plugins: %s", error)
        self._status_label.setText(f"Error: {error}")

    def _on_delete_success(self, count: int) -> None:
        logger.info("Delete succeeded: %d file(s). Refreshing browser.", count)
        self._status_label.setText(f"Deleted {count} file(s). Refreshing…")
        self.refresh()

    def _on_delete_error(self, error: BaseException) -> None:
        logger.error("Delete failed: %s", error)
        self._status_label.setText(f"Delete failed: {error}")
        QMessageBox.critical(self, "Delete failed", str(error))

    # ── Tree population ──────────────────────────────────────────────

    def _populate_tree(
        self, groups: Dict[str, List[Tuple[str, int, datetime]]]
    ) -> None:
        """Build the tree from grouped S3 objects."""
        self._tree.blockSignals(True)
        self._tree.clear()

        for group_path in sorted(groups.keys()):
            files = groups[group_path]

            parent: QTreeWidgetItem | QTreeWidget = self._tree
            for segment in group_path.split("/"):
                if not segment:
                    continue
                found = None
                count = (
                    parent.topLevelItemCount()
                    if isinstance(parent, QTreeWidget)
                    else parent.childCount()
                )
                for i in range(count):
                    child = (
                        parent.topLevelItem(i)
                        if isinstance(parent, QTreeWidget)
                        else parent.child(i)
                    )
                    if child and child.text(0) == segment:
                        found = child
                        break
                if found is None:
                    found = QTreeWidgetItem([segment, "", ""])
                    # Folder nodes are checkable — toggling selects/deselects all children
                    found.setFlags(found.flags() | Qt.ItemIsUserCheckable)
                    found.setCheckState(0, Qt.CheckState.Unchecked)
                    if isinstance(parent, QTreeWidget):
                        parent.addTopLevelItem(found)
                    else:
                        parent.addChild(found)
                    found.setExpanded(True)
                parent = found

            for filename, size, last_modified in sorted(files, key=lambda f: f[0]):
                item = QTreeWidgetItem(
                    [filename, format_file_size(size), last_modified.strftime("%Y-%m-%d %H:%M")]
                )
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Unchecked)
                s3_key = f"{self._root_prefix}/plugins/{group_path}/{filename}"
                item.setData(0, Qt.UserRole, s3_key)
                if isinstance(parent, QTreeWidget):
                    parent.addTopLevelItem(item)
                else:
                    parent.addChild(item)

        self._tree.blockSignals(False)

    # ── Handlers ─────────────────────────────────────────────────────

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """Handle click — propagate folder check state to children."""
        if item.childCount() > 0:
            # Folder node clicked: propagate check state to all descendants
            state = item.checkState(0)
            self._tree.blockSignals(True)
            self._set_children_check_state(item, state)
            self._tree.blockSignals(False)
        self._update_delete_btn()

    def _on_check_changed(self, item: QTreeWidgetItem, column: int = 0) -> None:
        """Handle programmatic check changes."""
        self._update_delete_btn()

    def _update_delete_btn(self) -> None:
        self._delete_btn.setEnabled(len(self._get_checked_keys()) > 0)

    def _set_children_check_state(
        self, parent: QTreeWidgetItem, state: Qt.CheckState
    ) -> None:
        """Recursively set check state on all descendants."""
        for i in range(parent.childCount()):
            child = parent.child(i)
            child.setCheckState(0, state)
            if child.childCount() > 0:
                self._set_children_check_state(child, state)

    def _on_delete(self) -> None:
        keys = self._get_checked_keys()
        if not keys:
            return

        reply = QMessageBox.question(
            self,
            "Delete plugins",
            f"Delete {len(keys)} file(s)? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._delete_btn.setEnabled(False)
        self._status_label.setText("⏳ Deleting…")
        self._async_runner.run(
            operation_key="delete_plugins",
            fn=_delete_plugins_background,
            on_success=self._on_delete_success,
            on_error=self._on_delete_error,
            farm_id=self._farm_id,
            queue_id=self._queue_id,
            bucket=self._bucket,
            keys=keys,
        )

    # ── Helpers ──────────────────────────────────────────────────────

    def _get_checked_keys(self) -> List[str]:
        """Walk the tree and collect S3 keys of checked leaf items."""
        keys: List[str] = []
        self._collect_checked(self._tree.invisibleRootItem(), keys)
        return keys

    def _collect_checked(self, parent: QTreeWidgetItem, keys: List[str]) -> None:
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.childCount() > 0:
                self._collect_checked(child, keys)
            else:
                if child.checkState(0) == Qt.CheckState.Checked:
                    key = child.data(0, Qt.UserRole)
                    if key:
                        keys.append(key)
