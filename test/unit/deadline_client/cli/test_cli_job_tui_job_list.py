# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Tests for JobListTUI."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from deadline.client.cli._groups._job_tui._job_list import JobListTUI


@pytest.fixture
def mock_deadline_client():
    client = MagicMock()
    client.search_jobs.return_value = {
        "jobs": [
            {
                "jobId": "job-abcdef1234567890abcdef1234567890",
                "name": "Test Render Job",
                "taskRunStatus": "SUCCEEDED",
                "createdAt": datetime(2026, 2, 8, 10, 0, 0, tzinfo=timezone.utc),
            },
            {
                "jobId": "job-11111111111111111111111111111111",
                "name": "Running Job",
                "taskRunStatus": "RUNNING",
                "targetTaskRunStatus": "CANCELED",
                "createdAt": datetime(2026, 2, 8, 9, 0, 0, tzinfo=timezone.utc),
            },
        ],
        "totalResults": 2,
    }
    return client


class TestJobListTUI:
    def test_load_page(self, mock_deadline_client):
        tui = JobListTUI("farm-123", "queue-456", mock_deadline_client)
        tui.load_page()
        assert len(tui.jobs) == 2
        assert tui.total_jobs == 2
        mock_deadline_client.search_jobs.assert_called_once()

    def test_load_page_pagination(self, mock_deadline_client):
        tui = JobListTUI("farm-123", "queue-456", mock_deadline_client)
        tui.page = 2
        tui.load_page()
        call_kwargs = mock_deadline_client.search_jobs.call_args[1]
        assert call_kwargs["itemOffset"] == 2 * tui.page_size

    @patch("deadline.client.cli._groups._job_tui._job_list.read_key")
    @patch("deadline.client.cli._groups._job_tui._job_list.console")
    def test_run_select_job(self, mock_console, mock_read_key, mock_deadline_client):
        mock_read_key.return_value = "enter"
        tui = JobListTUI("farm-123", "queue-456", mock_deadline_client)
        result = tui.run()
        assert result == ("select", "job-abcdef1234567890abcdef1234567890")

    @patch("deadline.client.cli._groups._job_tui._job_list.read_key")
    @patch("deadline.client.cli._groups._job_tui._job_list.console")
    def test_run_quit(self, mock_console, mock_read_key, mock_deadline_client):
        mock_read_key.return_value = "q"
        tui = JobListTUI("farm-123", "queue-456", mock_deadline_client)
        result = tui.run()
        assert result is None

    @patch("deadline.client.cli._groups._job_tui._job_list.read_key")
    @patch("deadline.client.cli._groups._job_tui._job_list.console")
    def test_run_attachments(self, mock_console, mock_read_key, mock_deadline_client):
        mock_read_key.return_value = "a"
        tui = JobListTUI("farm-123", "queue-456", mock_deadline_client)
        result = tui.run()
        assert result == ("attachments", "job-abcdef1234567890abcdef1234567890")

    @patch("deadline.client.cli._groups._job_tui._job_list.read_key")
    @patch("deadline.client.cli._groups._job_tui._job_list.console")
    def test_run_right_arrow_selects(self, mock_console, mock_read_key, mock_deadline_client):
        mock_read_key.return_value = "right"
        tui = JobListTUI("farm-123", "queue-456", mock_deadline_client)
        result = tui.run()
        assert result == ("select", "job-abcdef1234567890abcdef1234567890")

    @patch("deadline.client.cli._groups._job_tui._job_list.copy_to_clipboard", return_value=True)
    @patch("deadline.client.cli._groups._job_tui._job_list.read_key")
    @patch("deadline.client.cli._groups._job_tui._job_list.console")
    def test_run_copy_id(self, mock_console, mock_read_key, mock_copy, mock_deadline_client):
        # First press 'c' to copy, then 'q' to quit
        mock_read_key.side_effect = ["c", "q"]
        tui = JobListTUI("farm-123", "queue-456", mock_deadline_client)
        result = tui.run()
        mock_copy.assert_called_once_with("job-abcdef1234567890abcdef1234567890")
        assert result is None

    @patch("deadline.client.cli._groups._job_tui._job_list.read_key")
    @patch("deadline.client.cli._groups._job_tui._job_list.console")
    def test_cursor_movement(self, mock_console, mock_read_key, mock_deadline_client):
        mock_read_key.side_effect = ["down", "enter"]
        tui = JobListTUI("farm-123", "queue-456", mock_deadline_client)
        result = tui.run()
        assert result == ("select", "job-11111111111111111111111111111111")

    @patch("deadline.client.cli._groups._job_tui._job_list.read_key")
    @patch("deadline.client.cli._groups._job_tui._job_list.console")
    def test_cursor_does_not_go_below_zero(self, mock_console, mock_read_key, mock_deadline_client):
        mock_read_key.side_effect = ["up", "up", "enter"]
        tui = JobListTUI("farm-123", "queue-456", mock_deadline_client)
        result = tui.run()
        # Cursor should stay at 0
        assert result == ("select", "job-abcdef1234567890abcdef1234567890")

    @patch("deadline.client.cli._groups._job_tui._job_list.read_key")
    @patch("deadline.client.cli._groups._job_tui._job_list.console")
    def test_empty_jobs(self, mock_console, mock_read_key, mock_deadline_client):
        mock_deadline_client.search_jobs.return_value = {"jobs": [], "totalResults": 0}
        mock_read_key.return_value = "q"
        tui = JobListTUI("farm-123", "queue-456", mock_deadline_client)
        result = tui.run()
        assert result is None
