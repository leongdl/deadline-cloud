# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
Tests for the `deadline simple-plugins` CLI command.
"""

from unittest.mock import patch, MagicMock

from click.testing import CliRunner

from deadline.client.cli import main


class TestSimplePluginsCommand:
    """Tests for the simple-plugins CLI command registration and invocation."""

    def test_command_exists(self):
        """The simple-plugins command should be registered on the CLI."""
        runner = CliRunner()
        result = runner.invoke(main, ["simple-plugins", "--help"])
        assert result.exit_code == 0
        assert "simple plugins GUI" in result.output.lower() or "simple-plugins" in result.output

    def test_help_shows_options(self):
        """Help text should list --farm-id and --install-gui options."""
        runner = CliRunner()
        result = runner.invoke(main, ["simple-plugins", "--help"])
        assert result.exit_code == 0
        assert "--farm-id" in result.output
        assert "--install-gui" in result.output

    @patch("deadline.client.cli._groups.simple_plugins_group.gui_context_for_cli")
    def test_launches_gui_context(self, mock_gui_ctx):
        """The command should call gui_context_for_cli and SimplePluginsDialog.show_dialog."""
        mock_gui_ctx.return_value.__enter__ = MagicMock(return_value=None)
        mock_gui_ctx.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "deadline.client.ui.dialogs.simple_plugins_dialog.SimplePluginsDialog.show_dialog"
        ) as mock_show:
            runner = CliRunner()
            result = runner.invoke(main, ["simple-plugins", "--farm-id", "farm-abc123"])

            # gui_context_for_cli should be called with install_gui=False
            mock_gui_ctx.assert_called_once_with(automatically_install_dependencies=False)
            mock_show.assert_called_once_with(farm_id="farm-abc123")

    @patch("deadline.client.cli._groups.simple_plugins_group.gui_context_for_cli")
    def test_install_gui_flag(self, mock_gui_ctx):
        """--install-gui should pass True to gui_context_for_cli."""
        mock_gui_ctx.return_value.__enter__ = MagicMock(return_value=None)
        mock_gui_ctx.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "deadline.client.ui.dialogs.simple_plugins_dialog.SimplePluginsDialog.show_dialog"
        ):
            runner = CliRunner()
            runner.invoke(main, ["simple-plugins", "--install-gui"])

            mock_gui_ctx.assert_called_once_with(automatically_install_dependencies=True)

    @patch("deadline.client.cli._groups.simple_plugins_group.gui_context_for_cli")
    def test_farm_id_defaults_to_none(self, mock_gui_ctx):
        """When --farm-id is not provided, farm_id should be None."""
        mock_gui_ctx.return_value.__enter__ = MagicMock(return_value=None)
        mock_gui_ctx.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "deadline.client.ui.dialogs.simple_plugins_dialog.SimplePluginsDialog.show_dialog"
        ) as mock_show:
            runner = CliRunner()
            runner.invoke(main, ["simple-plugins"])

            mock_show.assert_called_once_with(farm_id=None)
