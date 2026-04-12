# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
Tests for the SimplePluginsUploadWidget.
"""

import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

try:
    from deadline.client.ui.widgets.simple_plugins_upload_widget import (
        SimplePluginsUploadWidget,
    )
except ImportError:
    pytest.importorskip("deadline.client.ui.widgets.simple_plugins_upload_widget")


class TestSimplePluginsUploadWidget:
    """Tests for the upload form widget."""

    def test_initial_state(self, qtbot):
        """Upload button should be disabled initially, DCC should default to maya."""
        widget = SimplePluginsUploadWidget()
        qtbot.addWidget(widget)

        assert not widget._upload_btn.isEnabled()
        assert not widget._cancel_btn.isVisible()
        assert widget._os_linux.isChecked()
        assert not widget._os_windows.isChecked()
        assert widget._dcc_box.currentText() == "maya"
        assert widget._dcc_box.currentIndex() == 0

    def test_set_s3_target_enables_upload_with_files(self, qtbot):
        """Upload button should enable when bucket is set and files are selected."""
        widget = SimplePluginsUploadWidget()
        qtbot.addWidget(widget)

        with tempfile.NamedTemporaryFile(suffix=".so", delete=False) as f:
            f.write(b"fake plugin data")
            temp_path = f.name

        try:
            widget._add_files([temp_path])
            assert not widget._upload_btn.isEnabled()

            widget.set_s3_target("farm-1", "queue-1", "my-bucket", "prefix")
            assert widget._upload_btn.isEnabled()
        finally:
            os.unlink(temp_path)

    def test_set_s3_target_no_bucket_disables_upload(self, qtbot):
        """Upload button should be disabled when bucket is empty."""
        widget = SimplePluginsUploadWidget()
        qtbot.addWidget(widget)

        widget.set_s3_target("farm-1", "queue-1", "", "")
        assert not widget._upload_btn.isEnabled()

    def test_generic_checkbox_disables_dcc_version(self, qtbot):
        """Checking 'Generic' should disable DCC and version fields."""
        widget = SimplePluginsUploadWidget()
        qtbot.addWidget(widget)

        assert widget._dcc_box.isEnabled()
        assert widget._version_edit.isEnabled()

        widget._generic_check.setChecked(True)

        assert not widget._dcc_box.isEnabled()
        assert not widget._version_edit.isEnabled()

        widget._generic_check.setChecked(False)

        assert widget._dcc_box.isEnabled()
        assert widget._version_edit.isEnabled()

    def test_build_prefix_linux_maya(self, qtbot):
        """Prefix should follow the convention path for Linux/Maya."""
        widget = SimplePluginsUploadWidget()
        qtbot.addWidget(widget)

        widget._root_prefix = "RootPrefix"
        widget._os_linux.setChecked(True)
        widget._dcc_box.setCurrentText("maya")
        widget._version_edit.setText("2025")

        assert widget._build_prefix() == "RootPrefix/plugins/linux/maya/2025/"

    def test_build_prefix_windows_nuke(self, qtbot):
        """Prefix should follow the convention path for Windows/Nuke."""
        widget = SimplePluginsUploadWidget()
        qtbot.addWidget(widget)

        widget._root_prefix = "RootPrefix"
        widget._os_windows.setChecked(True)
        widget._dcc_box.setCurrentText("nuke")
        widget._version_edit.setText("15.1")

        assert widget._build_prefix() == "RootPrefix/plugins/windows/nuke/15.1/"

    def test_build_prefix_generic(self, qtbot):
        """Generic checkbox should produce the generic prefix."""
        widget = SimplePluginsUploadWidget()
        qtbot.addWidget(widget)

        widget._root_prefix = "RootPrefix"
        widget._generic_check.setChecked(True)

        assert widget._build_prefix() == "RootPrefix/plugins/generic/"

    def test_add_files_deduplicates(self, qtbot):
        """Adding the same file twice should not create duplicates."""
        widget = SimplePluginsUploadWidget()
        qtbot.addWidget(widget)

        with tempfile.NamedTemporaryFile(suffix=".so", delete=False) as f:
            f.write(b"data")
            temp_path = f.name

        try:
            widget._add_files([temp_path])
            widget._add_files([temp_path])

            assert len(widget._selected_files) == 1
            assert widget._file_list.count() == 1
        finally:
            os.unlink(temp_path)

    def test_clear_files(self, qtbot):
        """Clear should remove all selected files."""
        widget = SimplePluginsUploadWidget()
        qtbot.addWidget(widget)

        with tempfile.NamedTemporaryFile(suffix=".so", delete=False) as f:
            f.write(b"data")
            temp_path = f.name

        try:
            widget._add_files([temp_path])
            assert len(widget._selected_files) == 1

            widget._clear_files()

            assert len(widget._selected_files) == 0
            assert widget._file_list.count() == 0
            assert not widget._upload_btn.isEnabled()
        finally:
            os.unlink(temp_path)

    def test_format_size(self, qtbot):
        """Size formatting should produce human-readable strings."""
        from deadline.client.ui.widgets._simple_plugins_utils import format_file_size

        assert format_file_size(500) == "500 B"
        assert format_file_size(1536) == "1.5 KB"
        assert format_file_size(2 * 1024 * 1024) == "2.0 MB"

    @patch(
        "deadline.client.ui.widgets.simple_plugins_upload_widget.QMessageBox.warning"
    )
    def test_upload_no_bucket_shows_warning(self, mock_warning, qtbot):
        """Clicking upload with no bucket should show a warning."""
        widget = SimplePluginsUploadWidget()
        qtbot.addWidget(widget)

        widget._bucket = ""
        widget._on_upload()

        mock_warning.assert_called_once()

    @patch(
        "deadline.client.ui.widgets.simple_plugins_upload_widget.QMessageBox.warning"
    )
    def test_upload_missing_dcc_version_shows_warning(self, mock_warning, qtbot):
        """Clicking upload without DCC/version (non-generic) should warn."""
        widget = SimplePluginsUploadWidget()
        qtbot.addWidget(widget)

        widget._bucket = "my-bucket"
        widget._dcc_box.setCurrentText("")
        widget._version_edit.setText("")

        widget._on_upload()

        mock_warning.assert_called_once()

    def test_cancel_button_hidden_initially(self, qtbot):
        """Cancel button should be hidden when not uploading."""
        widget = SimplePluginsUploadWidget()
        qtbot.addWidget(widget)

        assert not widget._cancel_btn.isVisible()

    def test_on_upload_success_clears_and_emits(self, qtbot):
        """Upload success should clear files and emit upload_completed."""
        widget = SimplePluginsUploadWidget()
        qtbot.addWidget(widget)
        widget._bucket = "my-bucket"
        widget._root_prefix = "Root"
        widget._uploading = True

        with tempfile.NamedTemporaryFile(suffix=".so", delete=False) as f:
            f.write(b"data")
            temp_path = f.name

        try:
            widget._add_files([temp_path])

            with patch.object(widget, "upload_completed") as mock_signal:
                widget._on_upload_success(1)

                assert len(widget._selected_files) == 0
                assert not widget._uploading
                mock_signal.emit.assert_called_once()
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    @patch(
        "deadline.client.ui.widgets.simple_plugins_upload_widget.QMessageBox.critical",
        return_value=MagicMock(),  # Cancel
    )
    def test_on_upload_error_shows_retry(self, mock_critical, qtbot):
        """Upload error should show a retry/cancel dialog."""
        widget = SimplePluginsUploadWidget()
        qtbot.addWidget(widget)
        widget._uploading = True

        widget._on_upload_error(RuntimeError("Network error"))

        mock_critical.assert_called_once()
        assert not widget._uploading


    # ── P0 #1: Thread safety — background function receives all state as params ──

    def test_upload_background_receives_captured_state(self, qtbot):
        """_do_upload should snapshot bucket/farm/queue into the async call,
        not read from self during background execution."""
        widget = SimplePluginsUploadWidget()
        qtbot.addWidget(widget)
        widget._bucket = "original-bucket"
        widget._farm_id = "farm-original"
        widget._queue_id = "queue-original"
        widget._root_prefix = "Root"
        widget._os_linux.setChecked(True)
        widget._dcc_box.setCurrentText("maya")
        widget._version_edit.setText("2025")

        with tempfile.NamedTemporaryFile(suffix=".so", delete=False) as f:
            f.write(b"data")
            temp_path = f.name

        try:
            widget._add_files([temp_path])

            with patch.object(widget._async_runner, "run") as mock_run:
                widget._do_upload()

                # Verify the background function receives captured values, not self references
                call_kwargs = mock_run.call_args
                assert call_kwargs.kwargs["bucket"] == "original-bucket"
                assert call_kwargs.kwargs["farm_id"] == "farm-original"
                assert call_kwargs.kwargs["queue_id"] == "queue-original"
                assert "prefix" in call_kwargs.kwargs
                assert "files" in call_kwargs.kwargs
                assert "cancel_event" in call_kwargs.kwargs
        finally:
            os.unlink(temp_path)

    # ── P0 #2: Cancel sets threading.Event ──

    def test_cancel_sets_event_and_resets_state(self, qtbot):
        """_on_cancel should set the cancel event and reset uploading state."""
        import threading

        widget = SimplePluginsUploadWidget()
        qtbot.addWidget(widget)
        widget._uploading = True
        widget._cancel_event = threading.Event()
        widget._cancel_btn.setVisible(True)

        widget._on_cancel()

        assert widget._cancel_event.is_set()
        assert not widget._uploading
        assert not widget._cancel_btn.isVisible()
        assert "Cancelled" in widget._progress.format()

    # ── #4: Set-based dedup stays in sync ──

    def test_selected_files_set_stays_in_sync(self, qtbot):
        """_selected_files_set should mirror _selected_files for O(1) lookups."""
        widget = SimplePluginsUploadWidget()
        qtbot.addWidget(widget)

        with tempfile.NamedTemporaryFile(suffix=".so", delete=False) as f:
            f.write(b"data")
            path1 = f.name
        with tempfile.NamedTemporaryFile(suffix=".dll", delete=False) as f:
            f.write(b"data")
            path2 = f.name

        try:
            widget._add_files([path1, path2])
            assert len(widget._selected_files) == 2
            assert len(widget._selected_files_set) == 2
            assert path1 in widget._selected_files_set
            assert path2 in widget._selected_files_set

            widget._clear_files()
            assert len(widget._selected_files_set) == 0
        finally:
            os.unlink(path1)
            os.unlink(path2)

    # ── #5: Filename collision warning ──

    @patch(
        "deadline.client.ui.widgets.simple_plugins_upload_widget.QMessageBox.warning"
    )
    def test_filename_collision_warns(self, mock_warning, qtbot):
        """Adding two files with the same basename from different dirs should warn."""
        widget = SimplePluginsUploadWidget()
        qtbot.addWidget(widget)

        dir1 = tempfile.mkdtemp()
        dir2 = tempfile.mkdtemp()
        path1 = os.path.join(dir1, "plugin.so")
        path2 = os.path.join(dir2, "plugin.so")

        try:
            with open(path1, "w") as f:
                f.write("v1")
            with open(path2, "w") as f:
                f.write("v2")

            widget._add_files([path1])
            mock_warning.assert_not_called()

            widget._add_files([path2])
            mock_warning.assert_called_once()
            assert "collision" in mock_warning.call_args[0][1].lower()
        finally:
            os.unlink(path1)
            os.unlink(path2)
            os.rmdir(dir1)
            os.rmdir(dir2)

    # ── #10: Retry limit (max 2 then hard fail) ──

    @patch(
        "deadline.client.ui.widgets.simple_plugins_upload_widget.QMessageBox.critical"
    )
    def test_retry_limit_exhausted(self, mock_critical, qtbot):
        """After MAX_RETRIES, should show hard failure without Retry button."""
        from deadline.client.ui.widgets.simple_plugins_upload_widget import _MAX_RETRIES

        widget = SimplePluginsUploadWidget()
        qtbot.addWidget(widget)
        widget._uploading = True

        # Simulate exhausting retries — set count beyond max
        widget._retry_count = _MAX_RETRIES
        widget._on_upload_error(RuntimeError("Persistent failure"))

        # Should have been called with just the hard failure message (no Retry button)
        assert mock_critical.call_count >= 1
        # retry_count should be reset
        assert widget._retry_count == 0

    @patch(
        "deadline.client.ui.widgets.simple_plugins_upload_widget.QMessageBox.critical",
        return_value=MagicMock(),  # Simulate clicking Cancel on retry dialog
    )
    def test_first_retry_shows_attempt_count(self, mock_critical, qtbot):
        """First failure should show retry dialog with attempt count."""
        widget = SimplePluginsUploadWidget()
        qtbot.addWidget(widget)
        widget._uploading = True
        widget._retry_count = 0

        widget._on_upload_error(RuntimeError("Network error"))

        mock_critical.assert_called_once()
        call_args = mock_critical.call_args[0]
        assert "attempt 1" in call_args[1].lower() or "1 of" in call_args[1].lower()
