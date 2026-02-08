# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Tests for AttachmentBrowserTUI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from deadline.client.cli._groups._job_tui._attachment_browser import AttachmentBrowserTUI


@pytest.fixture
def mock_s3_settings():
    settings = MagicMock()
    settings.rootPrefix = "root/prefix"
    settings.s3BucketName = "test-bucket"
    return settings


@pytest.fixture
def mock_sessions():
    boto3_session = MagicMock()
    queue_role_session = MagicMock()
    # Mock the deadline client returned by boto3_session.client()
    mock_deadline = MagicMock()
    mock_deadline.get_job.return_value = {
        "name": "Test Job",
        "attachments": {"manifests": []},
    }
    boto3_session.client.return_value = mock_deadline
    return boto3_session, queue_role_session


class TestAttachmentBrowserTUI:
    @patch(
        "deadline.client.cli._groups._job_tui._attachment_browser.load_output_manifests",
        return_value=[],
    )
    @patch(
        "deadline.client.cli._groups._job_tui._attachment_browser.load_input_manifests",
        return_value=[],
    )
    @patch("deadline.client.cli._groups._job_tui._attachment_browser.read_key")
    @patch("deadline.client.cli._groups._job_tui._attachment_browser.console")
    def test_run_esc_returns(
        self,
        mock_console,
        mock_read_key,
        mock_load_input,
        mock_load_output,
        mock_sessions,
        mock_s3_settings,
    ):
        mock_read_key.return_value = "esc"
        boto3_session, queue_role_session = mock_sessions
        tui = AttachmentBrowserTUI(
            "farm-1",
            "queue-1",
            "job-1",
            "Test Job",
            "SUCCEEDED",
            boto3_session,
            queue_role_session,
            mock_s3_settings,
        )
        tui.run()  # Should return without error

    @patch(
        "deadline.client.cli._groups._job_tui._attachment_browser.load_output_manifests",
        return_value=[],
    )
    @patch(
        "deadline.client.cli._groups._job_tui._attachment_browser.load_input_manifests",
        return_value=[],
    )
    @patch("deadline.client.cli._groups._job_tui._attachment_browser.read_key")
    @patch("deadline.client.cli._groups._job_tui._attachment_browser.console")
    def test_run_quit(
        self,
        mock_console,
        mock_read_key,
        mock_load_input,
        mock_load_output,
        mock_sessions,
        mock_s3_settings,
    ):
        mock_read_key.return_value = "q"
        boto3_session, queue_role_session = mock_sessions
        tui = AttachmentBrowserTUI(
            "farm-1",
            "queue-1",
            "job-1",
            "Test Job",
            "SUCCEEDED",
            boto3_session,
            queue_role_session,
            mock_s3_settings,
        )
        tui.run()  # Should return without error

    @patch(
        "deadline.client.cli._groups._job_tui._attachment_browser.load_output_manifests",
        return_value=[],
    )
    @patch(
        "deadline.client.cli._groups._job_tui._attachment_browser.load_input_manifests",
        return_value=[],
    )
    def test_load_manifests(
        self, mock_load_input, mock_load_output, mock_sessions, mock_s3_settings
    ):
        boto3_session, queue_role_session = mock_sessions
        tui = AttachmentBrowserTUI(
            "farm-1",
            "queue-1",
            "job-1",
            "Test Job",
            "SUCCEEDED",
            boto3_session,
            queue_role_session,
            mock_s3_settings,
        )
        tui.load_manifests()
        assert len(tui.root.children) == 2  # input + output categories
        assert tui.root.children[0].name == "input"
        assert tui.root.children[1].name == "output"
