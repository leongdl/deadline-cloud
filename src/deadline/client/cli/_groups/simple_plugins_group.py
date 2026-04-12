# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
The `deadline simple-plugins` command:
    Opens a GUI for uploading, browsing, and removing plugin files
    for Deadline Cloud render workers.
"""

from __future__ import annotations

import click

from .._common import _handle_error
from .._main import deadline as main


@main.command(name="simple-plugins")
@click.option("--farm-id", default=None, help="The AWS Deadline Cloud Farm to use.")
@click.option(
    "--install-gui",
    is_flag=True,
    help="Installs GUI dependencies if they are not installed already",
)
@_handle_error
def simple_plugins(farm_id: str, install_gui: bool) -> None:
    """
    Open the simple plugins GUI to upload, browse, and remove
    plugin files for Deadline Cloud render workers.

    Plugin files are uploaded to the queue's job attachment bucket
    at the convention path `plugins/<os>/<dcc>/<version>/` and are
    automatically downloaded to workers at session start.
    """
    from ...ui import gui_context_for_cli

    with gui_context_for_cli(automatically_install_dependencies=install_gui):
        from ...ui.dialogs.simple_plugins_dialog import SimplePluginsDialog

        SimplePluginsDialog.show_dialog(farm_id=farm_id)
