# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Shared utilities for the job TUI."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def get_terminal_page_size(chrome_lines: int = 18) -> int:
    """Compute how many list items fit on screen.

    chrome_lines accounts for all non-list-item lines rendered per frame:
    header panel (4), section label + blank (2), pagination + blank (2),
    message line (1), help bar panel (4), extra safety margin (5) = 18.
    """
    return max(5, console.height - chrome_lines)


def get_status_style(status: str) -> tuple[str, str]:
    """Return (color, icon) for all taskRunStatus/runStatus values."""
    if status == "SUCCEEDED":
        return "green", "✓"
    elif status in ("RUNNING", "STARTING", "SCHEDULED", "ASSIGNED"):
        return "yellow", "●"
    elif status == "INTERRUPTING":
        return "yellow", "⚡"
    elif status == "PENDING":
        return "blue", "○"
    elif status == "READY":
        return "cyan", "◉"
    elif status == "SUSPENDED":
        return "magenta", "⏸"
    elif status == "NOT_COMPATIBLE":
        return "red", "⚠"
    elif status in ("FAILED", "CANCELED"):
        return "red", "✗"
    return "dim", "○"


def get_lifecycle_badge(status: str) -> Optional[tuple[str, str]]:
    """Return (badge_text, color) for step lifecycleStatus, or None if CREATE_COMPLETE."""
    if status == "CREATE_COMPLETE":
        return None
    elif status == "UPDATE_IN_PROGRESS":
        return "[UPDATING]", "yellow"
    elif status == "UPDATE_FAILED":
        return "[UPD_FAIL]", "red"
    elif status == "UPDATE_SUCCEEDED":
        return "[UPDATED]", "green"
    return None


def format_size(size: int) -> str:
    """Convert bytes to human readable (KB, MB, GB)."""
    size_float = float(size)
    for unit in ["B", "KB", "MB", "GB"]:
        if size_float < 1024:
            return f"{size_float:.1f} {unit}"
        size_float /= 1024
    return f"{size_float:.1f} TB"


def format_time_ago(dt: Optional[datetime]) -> str:
    """Convert datetime to relative time (e.g., '2m ago')."""
    if not dt:
        return ""
    now = datetime.now(timezone.utc)
    diff = now - dt
    seconds = diff.total_seconds()
    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        mins = int(seconds / 60)
        return f"{mins}m ago"
    elif seconds < 86400:
        hrs = int(seconds / 3600)
        return f"{hrs}h ago"
    else:
        days = int(seconds / 86400)
        return f"{days}d ago"


def format_short_id(full_id: str) -> str:
    """Truncate 'prefix-<32hex>' to 'prefix-<6hex>' like git short hash."""
    if "-" in full_id:
        prefix, hex_part = full_id.rsplit("-", 1)
        return f"{prefix}-{hex_part[:6]}"
    return full_id


def copy_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard. Returns True on success."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode(), check=True)
        elif sys.platform == "linux":
            subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=True)
        elif sys.platform == "win32":
            subprocess.run(["clip"], input=text.encode(), check=True)
        else:
            return False
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def enter_alt_screen() -> None:
    """Switch to alternate screen buffer and hide cursor."""
    sys.stdout.write("\033[?1049h\033[?25l")
    sys.stdout.flush()


def leave_alt_screen() -> None:
    """Show cursor and return to the main screen buffer."""
    sys.stdout.write("\033[?25h\033[?1049l")
    sys.stdout.flush()


def clear_screen() -> None:
    """Move cursor to home without erasing. Content is overwritten in-place to avoid flash."""
    sys.stdout.write("\033[H")
    sys.stdout.flush()


def finish_render() -> None:
    """Erase from current cursor to end of screen.

    Call this after all render output to clean up any leftover lines
    from a previous longer render.  The cursor stays hidden to avoid
    flicker between frames — it is restored by leave_alt_screen().
    """
    sys.stdout.write("\033[J")
    sys.stdout.flush()


def render_header(title: str, subtitle: str = "") -> None:
    """Render title panel with subtitle."""
    header = Table.grid(padding=1)
    header.add_column(style="bold cyan", justify="left")
    header.add_column(justify="right", style="dim")
    header.add_row(f"🎬 {title}", subtitle)
    console.print(
        Panel(
            header,
            title="[bold]Deadline Job TUI[/bold]",
            border_style="blue",
            width=console.width - 1,
        )
    )


def render_help_bar(keys: list[tuple[str, str]]) -> None:
    """Render keyboard shortcut help panel and clean up leftover lines."""
    help_text = "  ".join([f"[bold]{k}[/bold] [dim]{v}[/dim]" for k, v in keys])
    console.print(Panel(help_text, style="dim", border_style="dim", width=console.width - 1))
    finish_render()


def read_key() -> str:
    """Read a single keypress, returning normalized key name.

    Returns one of: 'up', 'down', 'left', 'right', 'esc', 'enter',
    or the character pressed (e.g. 'q', 'j', 'J', 'c', 'n', 'p', 'r', 'l').
    """
    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            # Could be an escape sequence or just Esc key
            ch2 = sys.stdin.read(1)
            if ch2 == "[":
                ch3 = sys.stdin.read(1)
                if ch3 == "A":
                    return "up"
                elif ch3 == "B":
                    return "down"
                elif ch3 == "C":
                    return "right"
                elif ch3 == "D":
                    return "left"
            return "esc"
        elif ch == "\r":
            return "enter"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
