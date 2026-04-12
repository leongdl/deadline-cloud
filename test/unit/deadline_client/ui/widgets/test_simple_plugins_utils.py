# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""
Tests for the shared simple plugins utilities.
"""

from deadline.client.ui.widgets._simple_plugins_utils import format_file_size


class TestFormatFileSize:
    """Tests for the shared format_file_size utility."""

    def test_bytes(self):
        assert format_file_size(0) == "0 B"
        assert format_file_size(500) == "500 B"
        assert format_file_size(1023) == "1023 B"

    def test_kilobytes(self):
        assert format_file_size(1024) == "1.0 KB"
        assert format_file_size(1536) == "1.5 KB"
        assert format_file_size(1024 * 1024 - 1) == "1024.0 KB"

    def test_megabytes(self):
        assert format_file_size(1024 * 1024) == "1.0 MB"
        assert format_file_size(5 * 1024 * 1024) == "5.0 MB"
        assert format_file_size(1024 * 1024 * 1024 - 1) == "1024.0 MB"

    def test_gigabytes(self):
        assert format_file_size(1024 * 1024 * 1024) == "1.0 GB"
        assert format_file_size(2 * 1024 * 1024 * 1024) == "2.0 GB"
