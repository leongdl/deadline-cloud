# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.

"""Shared utilities for the simple plugins widgets."""


def format_file_size(size_bytes: int) -> str:
    """Format a byte count as a human-readable string (B / KB / MB / GB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
