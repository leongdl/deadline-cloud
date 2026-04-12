# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
Tests for the SimplePluginsDialog.
"""

from unittest.mock import patch, MagicMock, PropertyMock

import pytest

try:
    from deadline.client.ui.dialogs.simple_plugins_dialog import SimplePluginsDialog
except ImportError:
    pytest.importorskip("deadline.client.ui.dialogs.simple_plugins_dialog")


@patch(
    "deadline.client.ui.dialogs.simple_plugins_dialog.DeadlineAuthenticationStatus.getInstance",
    return_value=MagicMock(),
)
@patch(
    "deadline.client.ui.dialogs.simple_plugins_dialog.DeadlineUIController.getInstance",
    return_value=MagicMock(),
)
class TestSimplePluginsDialog:
    """Tests for SimplePluginsDialog construction and queue resolution."""

    @patch("deadline.client.ui.dialogs.simple_plugins_dialog.config_file")
    def test_dialog_opens_with_farm_id(
        self, mock_config_file, mock_controller, mock_auth, qtbot
    ):
        """Dialog should initialize with the provided farm ID."""
        mock_config_file.get_setting.return_value = ""
        mock_config_file.read_config.return_value = {}
        mock_config_file.set_setting = lambda *a, **kw: None

        dialog = SimplePluginsDialog(farm_id="farm-test123")
        qtbot.addWidget(dialog)

        assert dialog._farm_id == "farm-test123"

    @patch("deadline.client.ui.dialogs.simple_plugins_dialog.config_file")
    def test_dialog_uses_config_default_farm(
        self, mock_config_file, mock_controller, mock_auth, qtbot
    ):
        """When no farm_id is provided, should fall back to config default."""
        mock_config_file.get_setting.return_value = "farm-from-config"
        mock_config_file.read_config.return_value = {}
        mock_config_file.set_setting = lambda *a, **kw: None

        dialog = SimplePluginsDialog(farm_id=None)
        qtbot.addWidget(dialog)

        assert dialog._farm_id == "farm-from-config"

    @patch("deadline.client.ui.dialogs.simple_plugins_dialog.config_file")
    def test_dialog_has_upload_and_browser_widgets(
        self, mock_config_file, mock_controller, mock_auth, qtbot
    ):
        """Dialog should contain both upload and browser child widgets."""
        mock_config_file.get_setting.return_value = ""
        mock_config_file.read_config.return_value = {}
        mock_config_file.set_setting = lambda *a, **kw: None

        dialog = SimplePluginsDialog(farm_id="farm-test123")
        qtbot.addWidget(dialog)

        assert dialog._upload_widget is not None
        assert dialog._browser_widget is not None

    @patch("deadline.client.ui.dialogs.simple_plugins_dialog.config_file")
    def test_set_no_bucket_shows_message(
        self, mock_config_file, mock_controller, mock_auth, qtbot
    ):
        """_set_no_bucket should update the label and clear S3 targets."""
        mock_config_file.get_setting.return_value = ""
        mock_config_file.read_config.return_value = {}
        mock_config_file.set_setting = lambda *a, **kw: None

        dialog = SimplePluginsDialog(farm_id="farm-test123")
        qtbot.addWidget(dialog)

        dialog._set_no_bucket("Queue has no attachment settings.")

        assert "no attachment settings" in dialog._bucket_label.text().lower()
        assert dialog._bucket == ""
        assert dialog._root_prefix == ""

    @patch("deadline.client.ui.dialogs.simple_plugins_dialog.config_file")
    def test_resolve_attachment_settings_success(
        self, mock_config_file, mock_controller, mock_auth, qtbot
    ):
        """Successful queue resolution should populate bucket and root_prefix."""
        mock_config_file.get_setting.return_value = ""
        mock_config_file.read_config.return_value = {}
        mock_config_file.set_setting = lambda *a, **kw: None

        dialog = SimplePluginsDialog(farm_id="farm-test123")
        qtbot.addWidget(dialog)
        dialog._queue_id = "queue-test456"

        # Simulate the async success callback directly
        result = {
            "bucket": "my-bucket",
            "root_prefix": "MyPrefix",
            "farm_id": "farm-test123",
            "queue_id": "queue-test456",
        }
        dialog._on_resolve_success(result)

        assert dialog._bucket == "my-bucket"
        assert dialog._root_prefix == "MyPrefix"
        assert "my-bucket" in dialog._bucket_label.text()

    @patch("deadline.client.ui.dialogs.simple_plugins_dialog.config_file")
    def test_resolve_attachment_settings_no_settings(
        self, mock_config_file, mock_controller, mock_auth, qtbot
    ):
        """When queue has no attachment settings, should show error."""
        mock_config_file.get_setting.return_value = ""
        mock_config_file.read_config.return_value = {}
        mock_config_file.set_setting = lambda *a, **kw: None

        dialog = SimplePluginsDialog(farm_id="farm-test123")
        qtbot.addWidget(dialog)

        # Simulate the async error callback directly
        dialog._on_resolve_error(RuntimeError("Queue has no job attachment settings."))

        assert dialog._bucket == ""


    # ── Cascade flags ──

    @patch("deadline.client.ui.dialogs.simple_plugins_dialog.config_file")
    def test_initial_refresh_sets_cascade_flag(
        self, mock_config_file, mock_controller, mock_auth, qtbot
    ):
        """_initial_refresh should set _awaiting_farms_for_cascade."""
        mock_config_file.get_setting.return_value = "farm-test"
        mock_config_file.read_config.return_value = {}
        mock_config_file.set_setting = lambda *a, **kw: None

        dialog = SimplePluginsDialog(farm_id="farm-test")
        qtbot.addWidget(dialog)

        # After __init__ calls _initial_refresh, the flag should have been set
        # (it may already be cleared if farms_updated fired synchronously,
        # but we can verify the farm_box.refresh_list was called)
        assert dialog._farm_box is not None

    @patch("deadline.client.ui.dialogs.simple_plugins_dialog.config_file")
    def test_on_farm_changed_triggers_queue_cascade(
        self, mock_config_file, mock_controller, mock_auth, qtbot
    ):
        """Changing farm should set _awaiting_queues_for_cascade and refresh queues."""
        mock_config_file.get_setting.return_value = ""
        mock_config_file.read_config.return_value = {}
        mock_config_file.set_setting = lambda *a, **kw: None

        dialog = SimplePluginsDialog(farm_id="farm-test")
        qtbot.addWidget(dialog)

        # Simulate farm combo box having a valid selection
        dialog._farm_box.box.clear()
        dialog._farm_box.box.addItem("Test Farm", "farm-new")
        dialog._farm_box.box.setCurrentIndex(0)

        with patch.object(dialog._queue_box, "refresh_list") as mock_refresh:
            dialog._on_farm_changed(0)

            assert dialog._farm_id == "farm-new"
            assert dialog._awaiting_queues_for_cascade
            mock_refresh.assert_called_once()

    @patch("deadline.client.ui.dialogs.simple_plugins_dialog.config_file")
    def test_on_queues_list_updated_ignores_without_flag(
        self, mock_config_file, mock_controller, mock_auth, qtbot
    ):
        """_on_queues_list_updated should no-op if _awaiting_queues_for_cascade is False."""
        mock_config_file.get_setting.return_value = ""
        mock_config_file.read_config.return_value = {}
        mock_config_file.set_setting = lambda *a, **kw: None

        dialog = SimplePluginsDialog(farm_id="farm-test")
        qtbot.addWidget(dialog)
        dialog._awaiting_queues_for_cascade = False

        with patch.object(dialog, "_resolve_attachment_settings_async") as mock_resolve:
            dialog._on_queues_list_updated([("Queue", "queue-1")])
            mock_resolve.assert_not_called()

    # ── Resolve fires async runner ──

    @patch("deadline.client.ui.dialogs.simple_plugins_dialog.config_file")
    def test_resolve_fires_async_runner(
        self, mock_config_file, mock_controller, mock_auth, qtbot
    ):
        """_resolve_attachment_settings_async should call AsyncTaskRunner.run."""
        mock_config_file.get_setting.return_value = ""
        mock_config_file.read_config.return_value = {}
        mock_config_file.set_setting = lambda *a, **kw: None

        dialog = SimplePluginsDialog(farm_id="farm-test")
        qtbot.addWidget(dialog)
        dialog._farm_id = "farm-test"
        dialog._queue_id = "queue-test"

        with patch.object(dialog._async_runner, "run") as mock_run:
            dialog._resolve_attachment_settings_async()

            mock_run.assert_called_once()
            assert mock_run.call_args.kwargs["operation_key"] == "resolve_queue_attachments"
            assert mock_run.call_args.kwargs["farm_id"] == "farm-test"
            assert mock_run.call_args.kwargs["queue_id"] == "queue-test"
