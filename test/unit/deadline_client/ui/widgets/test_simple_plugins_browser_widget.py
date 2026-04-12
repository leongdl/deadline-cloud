# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
Tests for the SimplePluginsBrowserWidget.
"""

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

try:
    from deadline.client.ui.widgets.simple_plugins_browser_widget import (
        SimplePluginsBrowserWidget,
    )
except ImportError:
    pytest.importorskip("deadline.client.ui.widgets.simple_plugins_browser_widget")

from qtpy.QtCore import Qt


class TestSimplePluginsBrowserWidget:
    """Tests for the plugin browser tree widget."""

    def test_initial_state(self, qtbot):
        """Tree should be empty and delete button disabled initially."""
        widget = SimplePluginsBrowserWidget()
        qtbot.addWidget(widget)

        assert widget._tree.topLevelItemCount() == 0
        assert not widget._delete_btn.isEnabled()

    def test_set_s3_target_clears_tree(self, qtbot):
        """Setting a new S3 target should clear the tree."""
        widget = SimplePluginsBrowserWidget()
        qtbot.addWidget(widget)

        from qtpy.QtWidgets import QTreeWidgetItem

        widget._tree.addTopLevelItem(QTreeWidgetItem(["test", "1 KB", "2026-01-01"]))
        assert widget._tree.topLevelItemCount() == 1

        widget.set_s3_target("farm-1", "queue-1", "bucket", "prefix")

        assert widget._tree.topLevelItemCount() == 0
        assert not widget._delete_btn.isEnabled()

    def test_populate_tree_groups_by_path(self, qtbot):
        """_populate_tree should create nested groups for OS/DCC/version."""
        widget = SimplePluginsBrowserWidget()
        qtbot.addWidget(widget)
        widget._root_prefix = "Root"

        now = datetime(2026, 4, 10, 14, 30, tzinfo=timezone.utc)
        groups = {
            "linux/maya/2025": [
                ("plugin-a.so", 1200, now),
                ("plugin-b.so", 340000, now),
            ],
            "generic": [
                ("script.sh", 2048, now),
            ],
        }

        widget._populate_tree(groups)

        assert widget._tree.topLevelItemCount() == 2

        linux_item = None
        generic_item = None
        for i in range(widget._tree.topLevelItemCount()):
            item = widget._tree.topLevelItem(i)
            if item.text(0) == "linux":
                linux_item = item
            elif item.text(0) == "generic":
                generic_item = item

        assert linux_item is not None
        assert generic_item is not None

        maya_item = linux_item.child(0)
        assert maya_item.text(0) == "maya"
        version_item = maya_item.child(0)
        assert version_item.text(0) == "2025"
        assert version_item.childCount() == 2

        assert generic_item.childCount() == 1
        assert generic_item.child(0).text(0) == "script.sh"

    def test_checked_keys_collection(self, qtbot):
        """_get_checked_keys should return S3 keys of checked leaf items."""
        widget = SimplePluginsBrowserWidget()
        qtbot.addWidget(widget)
        widget._root_prefix = "Root"

        now = datetime(2026, 4, 10, 14, 30, tzinfo=timezone.utc)
        groups = {
            "linux/maya/2025": [
                ("plugin-a.so", 1200, now),
                ("plugin-b.so", 340000, now),
            ],
        }

        widget._populate_tree(groups)

        assert widget._get_checked_keys() == []

        linux_item = widget._tree.topLevelItem(0)
        maya_item = linux_item.child(0)
        version_item = maya_item.child(0)
        file_item = version_item.child(0)
        file_item.setCheckState(0, Qt.CheckState.Checked)

        keys = widget._get_checked_keys()
        assert len(keys) == 1
        assert "plugin-a.so" in keys[0]

    def test_folder_check_propagates_to_children(self, qtbot):
        """Clicking a folder node should check/uncheck all descendant files."""
        widget = SimplePluginsBrowserWidget()
        qtbot.addWidget(widget)
        widget._root_prefix = "Root"

        now = datetime(2026, 4, 10, 14, 30, tzinfo=timezone.utc)
        groups = {
            "linux/maya/2025": [
                ("plugin-a.so", 1200, now),
                ("plugin-b.so", 340000, now),
            ],
        }

        widget._populate_tree(groups)

        # Check the "linux" folder node
        linux_item = widget._tree.topLevelItem(0)
        linux_item.setCheckState(0, Qt.CheckState.Checked)
        widget._on_item_clicked(linux_item, 0)

        # Both files should now be checked
        keys = widget._get_checked_keys()
        assert len(keys) == 2

        # Uncheck the folder
        linux_item.setCheckState(0, Qt.CheckState.Unchecked)
        widget._on_item_clicked(linux_item, 0)

        keys = widget._get_checked_keys()
        assert len(keys) == 0

    def test_format_size(self, qtbot):
        """Size formatting should produce human-readable strings."""
        from deadline.client.ui.widgets._simple_plugins_utils import format_file_size

        assert format_file_size(500) == "500 B"
        assert format_file_size(1536) == "1.5 KB"
        assert format_file_size(5 * 1024 * 1024) == "5.0 MB"

    def test_on_list_success_populates_tree(self, qtbot):
        """_on_list_success should populate the tree from the result dict."""
        widget = SimplePluginsBrowserWidget()
        qtbot.addWidget(widget)
        widget._root_prefix = "Root"

        now = datetime(2026, 4, 10, 14, 30, tzinfo=timezone.utc)
        result = {
            "groups": {
                "linux/maya/2025": [("plugin.so", 1024, now)],
            },
            "total_files": 1,
            "total_size": 1024,
        }

        widget._on_list_success(result)

        assert widget._tree.topLevelItemCount() > 0
        assert "1 file" in widget._status_label.text()

    def test_on_list_error_shows_error(self, qtbot):
        """_on_list_error should show error in status label."""
        widget = SimplePluginsBrowserWidget()
        qtbot.addWidget(widget)

        widget._on_list_error(RuntimeError("Access denied"))

        assert "Error" in widget._status_label.text()

    def test_refresh_with_no_bucket_clears_tree(self, qtbot):
        """Refresh with no bucket should clear the tree."""
        widget = SimplePluginsBrowserWidget()
        qtbot.addWidget(widget)

        from qtpy.QtWidgets import QTreeWidgetItem

        widget._tree.addTopLevelItem(QTreeWidgetItem(["leftover"]))
        assert widget._tree.topLevelItemCount() == 1

        widget._bucket = ""
        widget.refresh()

        assert widget._tree.topLevelItemCount() == 0


    # ── #11: Delete success is non-blocking (status label, not QMessageBox) ──

    def test_on_delete_success_updates_label_not_dialog(self, qtbot):
        """Delete success should update status label, not show a blocking dialog."""
        widget = SimplePluginsBrowserWidget()
        qtbot.addWidget(widget)
        widget._bucket = "my-bucket"
        widget._root_prefix = "Root"
        widget._farm_id = "farm-1"
        widget._queue_id = "queue-1"

        # Patch refresh to avoid actual S3 call
        with patch.object(widget, "refresh") as mock_refresh:
            widget._on_delete_success(3)

            assert "Deleted 3" in widget._status_label.text()
            mock_refresh.assert_called_once()

    # ── Async delete callback ──

    def test_on_delete_error_shows_error(self, qtbot):
        """Delete error should show error dialog and update status."""
        widget = SimplePluginsBrowserWidget()
        qtbot.addWidget(widget)

        with patch(
            "deadline.client.ui.widgets.simple_plugins_browser_widget.QMessageBox.critical"
        ) as mock_critical:
            widget._on_delete_error(RuntimeError("Access denied"))

            mock_critical.assert_called_once()
            assert "Delete failed" in widget._status_label.text()

    # ── Folder nodes are checkable ──

    def test_folder_nodes_are_checkable(self, qtbot):
        """Folder nodes (OS, DCC, version) should have checkboxes."""
        widget = SimplePluginsBrowserWidget()
        qtbot.addWidget(widget)
        widget._root_prefix = "Root"

        now = datetime(2026, 4, 10, 14, 30, tzinfo=timezone.utc)
        groups = {
            "linux/maya/2025": [("plugin.so", 1024, now)],
        }
        widget._populate_tree(groups)

        linux_item = widget._tree.topLevelItem(0)
        # Folder node should be checkable
        assert linux_item.flags() & Qt.ItemIsUserCheckable
        assert linux_item.checkState(0) == Qt.CheckState.Unchecked

    # ── Delete button enable/disable tracks checked state ──

    def test_delete_button_enables_on_check(self, qtbot):
        """Delete button should enable when a file is checked."""
        widget = SimplePluginsBrowserWidget()
        qtbot.addWidget(widget)
        widget._root_prefix = "Root"

        now = datetime(2026, 4, 10, 14, 30, tzinfo=timezone.utc)
        groups = {
            "linux/maya/2025": [("plugin.so", 1024, now)],
        }
        widget._populate_tree(groups)

        assert not widget._delete_btn.isEnabled()

        linux_item = widget._tree.topLevelItem(0)
        maya_item = linux_item.child(0)
        version_item = maya_item.child(0)
        file_item = version_item.child(0)
        file_item.setCheckState(0, Qt.CheckState.Checked)
        widget._on_check_changed(file_item)

        assert widget._delete_btn.isEnabled()

    # ── Refresh triggers async runner ──

    def test_refresh_triggers_async_list(self, qtbot):
        """refresh() should call AsyncTaskRunner.run with list_plugins key."""
        widget = SimplePluginsBrowserWidget()
        qtbot.addWidget(widget)
        widget._bucket = "my-bucket"
        widget._root_prefix = "Root"
        widget._farm_id = "farm-1"
        widget._queue_id = "queue-1"

        with patch.object(widget._async_runner, "run") as mock_run:
            widget.refresh()

            mock_run.assert_called_once()
            assert mock_run.call_args.kwargs["operation_key"] == "list_plugins"

    # ── S3 key stored correctly on leaf items ──

    def test_leaf_items_store_s3_key(self, qtbot):
        """Leaf file items should store the full S3 key in UserRole data."""
        widget = SimplePluginsBrowserWidget()
        qtbot.addWidget(widget)
        widget._root_prefix = "Root"

        now = datetime(2026, 4, 10, 14, 30, tzinfo=timezone.utc)
        groups = {
            "linux/maya/2025": [("plugin.so", 1024, now)],
        }
        widget._populate_tree(groups)

        linux_item = widget._tree.topLevelItem(0)
        maya_item = linux_item.child(0)
        version_item = maya_item.child(0)
        file_item = version_item.child(0)

        key = file_item.data(0, Qt.UserRole)
        assert key == "Root/plugins/linux/maya/2025/plugin.so"
