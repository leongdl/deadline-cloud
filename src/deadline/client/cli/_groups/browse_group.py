# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Interactive TUI job attachments browser CLI."""

import os
import subprocess
import sys
import tempfile
from configparser import ConfigParser
from enum import Enum
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.table import Table

from deadline.client import api
from deadline.client.api._session import get_default_client_config
from deadline.client.config import config_file
from deadline.job_attachments.models import (
    S3_MANIFEST_FOLDER_NAME,
    JobAttachmentS3Settings,
)

from .._common import _apply_cli_options_to_config, _handle_error
from .._main import deadline as main
from ._job_tui._common import (
    format_size,
    format_time_ago,
    get_status_style,
    render_help_bar,
)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp", ".svg"}
console = Console()


# === Constants & Types ===


class NodeType(Enum):
    ROOT = "root"
    CATEGORY = "category"
    MANIFEST_ROOT = "manifest_root"
    FOLDER = "folder"
    FILE = "file"


class TreeNode:
    def __init__(
        self,
        name: str,
        node_type: NodeType,
        path: str = "",
        size: int = 0,
        hash: str = "",
        parent: Optional["TreeNode"] = None,
    ):
        self.name = name
        self.node_type = node_type
        self.path = path
        self.size = size
        self.hash = hash
        self.parent = parent
        self.children: list["TreeNode"] = []


# === Layer 1: Utilities ===


def is_image(filename: str) -> bool:
    return os.path.splitext(filename.lower())[1] in IMAGE_EXTENSIONS


def get_all_files_under(node: TreeNode) -> list[TreeNode]:
    files = []
    if node.node_type == NodeType.FILE:
        files.append(node)
    for child in node.children:
        files.extend(get_all_files_under(child))
    return files


# === Layer 2: Tree Construction ===


def build_file_tree(manifest, root_name: str) -> TreeNode:
    root = TreeNode(name=root_name, node_type=NodeType.MANIFEST_ROOT)
    for mp in manifest.paths:
        parts = mp.path.split("/")
        current = root
        for i, part in enumerate(parts):
            is_file = i == len(parts) - 1
            existing = next((c for c in current.children if c.name == part), None)
            if existing:
                current = existing
            else:
                node_type = NodeType.FILE if is_file else NodeType.FOLDER
                new_node = TreeNode(
                    name=part,
                    node_type=node_type,
                    path=mp.path if is_file else "/".join(parts[: i + 1]),
                    size=mp.size if is_file else 0,
                    hash=mp.hash if is_file else "",
                    parent=current,
                )
                current.children.append(new_node)
                current = new_node
    return root


# === Layer 3: Manifest Loading ===


def load_input_manifests(job: dict, s3_prefix: str, s3_bucket: str, session) -> list[TreeNode]:
    from deadline.job_attachments.download import get_manifest_from_s3

    trees = []
    attachments = job.get("attachments", {})
    for manifest_info in attachments.get("manifests", []):
        input_path = manifest_info.get("inputManifestPath", "")
        root_path = manifest_info["rootPath"]
        if input_path:
            manifest = get_manifest_from_s3(
                manifest_key=f"{s3_prefix}/{input_path}",
                s3_bucket=s3_bucket,
                session=session,
            )
            if manifest:
                trees.append(build_file_tree(manifest, root_path))
    return trees


def load_output_manifests(s3_settings, farm_id, queue_id, job_id, session) -> list[TreeNode]:
    from deadline.job_attachments.download import (
        get_output_manifests_by_asset_root,
        merge_asset_manifests,
    )

    trees = []
    output_manifests = get_output_manifests_by_asset_root(
        s3_settings=s3_settings,
        farm_id=farm_id,
        queue_id=queue_id,
        job_id=job_id,
        session=session,
    )
    for root_path, manifests in output_manifests.items():
        merged = merge_asset_manifests(manifests)
        if merged:
            trees.append(build_file_tree(merged, root_path))
    return trees


# === Layer 4: TUI Rendering ===


def get_node_icon(node: TreeNode) -> str:
    if node.node_type == NodeType.FILE:
        ext = os.path.splitext(node.name.lower())[1]
        if ext in IMAGE_EXTENSIONS:
            return "🖼️ "
        elif ext in {".txt", ".log", ".md"}:
            return "📝"
        return "📄"
    elif node.node_type == NodeType.FOLDER:
        return "📁"
    elif node.node_type == NodeType.MANIFEST_ROOT:
        return "💾"
    elif node.node_type == NodeType.CATEGORY:
        return "📦"
    return "📂"


def render_header(title: str, subtitle: str = ""):
    header = Table.grid(padding=1)
    header.add_column(style="bold cyan", justify="left")
    header.add_column(justify="right", style="dim")
    header.add_row(f"🎬 {title}", subtitle)
    console.print(Panel(header, title="[bold]Deadline Job Browser[/bold]", border_style="blue"))


def render_breadcrumb(current_node: TreeNode):
    parts: list[str] = []
    node: Optional[TreeNode] = current_node
    while node:
        parts.insert(0, node.name)
        node = node.parent
    console.print(f"[dim]📍 {' › '.join(parts)}[/dim]\n")


def render_file_list(items: list[TreeNode], cursor: int):
    if not items:
        console.print("[dim italic]  (empty)[/dim italic]")
        return
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("", width=3)
    table.add_column("Name")
    table.add_column("Info", justify="right", style="dim")
    for i, item in enumerate(items):
        icon = get_node_icon(item)
        is_selected = i == cursor
        info = (
            format_size(item.size)
            if item.node_type == NodeType.FILE
            else f"{len(get_all_files_under(item))} files"
        )
        if is_selected:
            table.add_row(
                "[bold cyan]▶[/bold cyan]",
                f"[bold reverse] {icon} {item.name} [/bold reverse]",
                f"[bold cyan]{info}[/bold cyan]",
            )
        else:
            table.add_row(" ", f"{icon} {item.name}", info)
    console.print(table)


# === Layer 5: File Operations ===


def download_single_file(queue_role_session, s3_settings, node: TreeNode, dest_dir: str) -> str:
    s3 = queue_role_session.client("s3")
    s3_key = f"{s3_settings.rootPrefix}/Data/{node.hash}.xxh128"
    local_path = os.path.join(dest_dir, node.name)
    s3.download_file(s3_settings.s3BucketName, s3_key, local_path)
    return local_path


def download_folder(queue_role_session, s3_settings, node: TreeNode, dest_dir: str) -> int:
    files = get_all_files_under(node)
    s3 = queue_role_session.client("s3")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("Downloading...", total=len(files))
        for f in files:
            local_path = os.path.join(dest_dir, f.path)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            s3_key = f"{s3_settings.rootPrefix}/Data/{f.hash}.xxh128"
            s3.download_file(s3_settings.s3BucketName, s3_key, local_path)
            progress.update(task, advance=1, description=f"[cyan]{f.name}[/cyan]")
    return len(files)


def show_file_info(node: TreeNode):
    console.clear()
    table = Table(title="📋 File Information", show_header=False, border_style="cyan")
    table.add_column("Property", style="bold")
    table.add_column("Value")
    table.add_row("Name", node.name)
    table.add_row("Path", node.path)
    table.add_row("Size", format_size(node.size))
    table.add_row("Hash", node.hash)
    table.add_row("Type", "Image" if is_image(node.name) else "File")
    console.print(table)
    console.print("\n[dim]Press any key to continue...[/dim]")
    click.getchar()


def preview_file_content(queue_role_session, s3_settings, node: TreeNode):
    """Download and preview file content in terminal."""
    console.clear()
    console.print(f"[bold cyan]📄 {node.name}[/bold cyan]")
    console.print(f"[dim]Size: {format_size(node.size)} | Hash: {node.hash}[/dim]\n")

    # Download to temp
    path = download_single_file(queue_role_session, s3_settings, node, tempfile.gettempdir())

    # Preview based on file type
    ext = os.path.splitext(node.name.lower())[1]
    try:
        if ext in {".txt", ".log", ".md", ".json", ".yaml", ".yml", ".py", ".sh", ".csv"}:
            with open(path, "r", errors="replace") as f:
                content = f.read(4000)  # First 4KB
                if len(content) == 4000:
                    content += "\n... [truncated]"
            from rich.syntax import Syntax

            if ext in {".py", ".sh", ".json", ".yaml", ".yml"}:
                syntax = Syntax(content, ext[1:], theme="monokai", line_numbers=True)
                console.print(Panel(syntax, title="Preview", border_style="dim"))
            else:
                console.print(Panel(content, title="Preview", border_style="dim"))
        elif is_image(node.name):
            console.print("[yellow]Image file - press 'v' to open in viewer[/yellow]")
        else:
            # Binary file - show hex preview
            with open(path, "rb") as f:
                data = f.read(256)
            hex_lines = []
            for i in range(0, len(data), 16):
                hex_part = " ".join(f"{b:02x}" for b in data[i : i + 16])
                ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in data[i : i + 16])
                hex_lines.append(f"{i:04x}  {hex_part:<48}  {ascii_part}")
            console.print(Panel("\n".join(hex_lines), title="Hex Preview", border_style="dim"))
    except Exception as e:
        console.print(f"[red]Could not preview: {e}[/red]")

    console.print(f"\n[green]Downloaded to: {path}[/green]")
    console.print("[dim]Press any key to continue...[/dim]")
    click.getchar()


def open_image_viewer(queue_role_session, s3_settings, node: TreeNode):
    path = download_single_file(queue_role_session, s3_settings, node, tempfile.gettempdir())
    if sys.platform == "darwin":
        subprocess.run(["open", path])
    elif sys.platform == "linux":
        subprocess.run(["xdg-open", path])
    else:
        subprocess.run(["start", path], shell=True)


def show_manifest_list(root: TreeNode):
    console.clear()
    table = Table(title="📜 Manifest Files", border_style="cyan")
    table.add_column("Type", style="bold")
    table.add_column("Root Path")
    table.add_column("Files", justify="right")
    for category in root.children:
        for manifest_root in category.children:
            file_count = len(get_all_files_under(manifest_root))
            table.add_row(category.name, manifest_root.name, str(file_count))
    console.print(table)
    console.print("\n[dim]Press any key to continue...[/dim]")
    click.getchar()


# === Layer 6: Job Selector ===


class JobSelectorTUI:
    PAGE_SIZE = 20

    def __init__(self, farm_id: str, queue_id: str, deadline_client):
        self.farm_id = farm_id
        self.queue_id = queue_id
        self.deadline = deadline_client
        self.jobs: list[dict] = []
        self.cursor = 0
        self.page = 0
        self.total_jobs = 0

    def load_jobs(self):
        response = self.deadline.search_jobs(
            farmId=self.farm_id,
            queueIds=[self.queue_id],
            itemOffset=self.page * self.PAGE_SIZE,
            pageSize=self.PAGE_SIZE,
            sortExpressions=[{"fieldSort": {"name": "CREATED_AT", "sortOrder": "DESCENDING"}}],
        )
        self.jobs = response.get("jobs", [])
        self.total_jobs = response.get("totalResults", 0)

    def render(self):
        console.clear()
        render_header("Select a Job", f"Queue: {self.queue_id[:20]}...")
        console.print()
        if not self.jobs:
            console.print("[dim italic]  No jobs found[/dim italic]")
        else:
            table = Table(show_header=False, box=None, padding=(0, 1))
            table.add_column("", width=3)
            table.add_column("Status", width=12)
            table.add_column("Name", min_width=30)
            table.add_column("Time", width=10, justify="right")
            table.add_column("ID", width=12, justify="right")
            for i, job in enumerate(self.jobs):
                status = job.get("taskRunStatus", "UNKNOWN")
                color, icon = get_status_style(status)
                name = job.get("name", job.get("displayName", "Unnamed"))
                created = job.get("createdAt")
                time_str = format_time_ago(created) if created else ""
                job_id = job.get("jobId", "")
                short_id = job_id[-8:] if job_id else ""
                is_selected = i == self.cursor
                if is_selected:
                    table.add_row(
                        "[bold cyan]▶[/bold cyan]",
                        f"[bold {color}]{icon} {status}[/bold {color}]",
                        f"[bold reverse] {name} [/bold reverse]",
                        f"[bold cyan]{time_str}[/bold cyan]",
                        f"[bold cyan]...{short_id}[/bold cyan]",
                    )
                else:
                    table.add_row(
                        " ",
                        f"[{color}]{icon} {status}[/{color}]",
                        name,
                        f"[dim]{time_str}[/dim]",
                        f"[dim]...{short_id}[/dim]",
                    )
            console.print(table)
        # Pagination info
        total_pages = (self.total_jobs + self.PAGE_SIZE - 1) // self.PAGE_SIZE
        start = self.page * self.PAGE_SIZE + 1
        end = min(start + len(self.jobs) - 1, self.total_jobs)
        console.print(
            f"\n[dim]Page {self.page + 1}/{total_pages} ({start}-{end} of {self.total_jobs} jobs)[/dim]"
        )
        console.print()
        render_help_bar(
            [("↑↓", "nav"), ("←→", "page"), ("Enter", "select"), ("r", "refresh"), ("q", "quit")]
        )

    def run(self) -> Optional[str]:
        import termios
        import tty

        console.print("[dim]Loading jobs...[/dim]")
        self.load_jobs()
        while True:
            self.render()
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                ch = sys.stdin.read(1)
                if ch == "\x1b":
                    ch2 = sys.stdin.read(2)
                    if ch2 == "[A":  # Up
                        self.cursor = max(0, self.cursor - 1)
                    elif ch2 == "[B":  # Down
                        self.cursor = min(len(self.jobs) - 1, self.cursor + 1) if self.jobs else 0
                    elif ch2 == "[D":  # Left - prev page
                        if self.page > 0:
                            self.page -= 1
                            self.cursor = 0
                            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                            self.load_jobs()
                    elif ch2 == "[C":  # Right - next page
                        total_pages = (self.total_jobs + self.PAGE_SIZE - 1) // self.PAGE_SIZE
                        if self.page < total_pages - 1:
                            self.page += 1
                            self.cursor = 0
                            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                            self.load_jobs()
                elif ch == "\r" and self.jobs:
                    return self.jobs[self.cursor].get("jobId")
                elif ch == "r":
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                    console.print("[dim]Refreshing...[/dim]")
                    self.load_jobs()
                    self.cursor = 0
                elif ch == "q":
                    console.clear()
                    return None
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


# === Layer 7: File Browser ===


class JobBrowserTUI:
    def __init__(
        self,
        farm_id,
        queue_id,
        job_id,
        job_name,
        job_status,
        boto3_session,
        queue_role_session,
        s3_settings,
    ):
        self.farm_id = farm_id
        self.queue_id = queue_id
        self.job_id = job_id
        self.job_name = job_name
        self.job_status = job_status
        self.boto3_session = boto3_session
        self.queue_role_session = queue_role_session
        self.s3_settings = s3_settings
        self.root = TreeNode(name="Job", node_type=NodeType.ROOT)
        self.current_node = self.root
        self.cursor = 0
        self.message = ""

    def load_manifests(self):
        deadline = self.boto3_session.client("deadline", config=get_default_client_config())
        job = deadline.get_job(farmId=self.farm_id, queueId=self.queue_id, jobId=self.job_id)
        input_node = TreeNode(name="input", node_type=NodeType.CATEGORY, parent=self.root)
        output_node = TreeNode(name="output", node_type=NodeType.CATEGORY, parent=self.root)
        self.root.children = [input_node, output_node]
        s3_prefix = f"{self.s3_settings.rootPrefix}/{S3_MANIFEST_FOLDER_NAME}"
        for tree in load_input_manifests(
            job, s3_prefix, self.s3_settings.s3BucketName, self.queue_role_session
        ):
            tree.parent = input_node
            input_node.children.append(tree)
        for tree in load_output_manifests(
            self.s3_settings, self.farm_id, self.queue_id, self.job_id, self.queue_role_session
        ):
            tree.parent = output_node
            output_node.children.append(tree)

    def render(self):
        console.clear()
        color, icon = get_status_style(self.job_status)
        render_header(self.job_name, f"[{color}]{icon} {self.job_status}[/{color}]")
        render_breadcrumb(self.current_node)
        render_file_list(self.current_node.children, self.cursor)
        if self.message:
            console.print(f"\n[yellow]{self.message}[/yellow]")
            self.message = ""
        console.print()
        render_help_bar(
            [
                ("←→↑↓", "nav"),
                ("Enter", "open"),
                ("d", "download"),
                ("i", "info"),
                ("v", "view"),
                ("m", "manifests"),
                ("q", "quit"),
            ]
        )

    def handle_download(self, node: TreeNode):
        dest = console.input("[bold]Download to:[/bold] ") or os.getcwd()
        os.makedirs(dest, exist_ok=True)
        if node.node_type == NodeType.FILE:
            path = download_single_file(self.queue_role_session, self.s3_settings, node, dest)
            self.message = f"✅ Downloaded to {path}"
        else:
            count = download_folder(self.queue_role_session, self.s3_settings, node, dest)
            self.message = f"✅ Downloaded {count} files to {dest}"

    def run(self):
        import termios
        import tty

        console.print("[dim]Loading manifests...[/dim]")
        self.load_manifests()
        while True:
            self.render()
            items = self.current_node.children
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                ch = sys.stdin.read(1)
                if ch == "\x1b":
                    ch2 = sys.stdin.read(2)
                    if ch2 == "[A":
                        self.cursor = max(0, self.cursor - 1)
                    elif ch2 == "[B":
                        self.cursor = min(len(items) - 1, self.cursor + 1) if items else 0
                    elif ch2 == "[D" and self.current_node.parent:
                        self.current_node = self.current_node.parent
                        self.cursor = 0
                    elif ch2 == "[C" and items:
                        node = items[self.cursor]
                        if node.node_type == NodeType.FILE:
                            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                            show_file_info(node)
                        else:
                            self.current_node = node
                            self.cursor = 0
                elif ch == "\r" and items:
                    node = items[self.cursor]
                    if node.node_type == NodeType.FILE:
                        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                        show_file_info(node)
                    else:
                        self.current_node = node
                        self.cursor = 0
                elif ch == "b" and self.current_node.parent:
                    self.current_node = self.current_node.parent
                    self.cursor = 0
                elif ch == "d" and items:
                    node = items[self.cursor]
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                    if node.node_type == NodeType.FILE:
                        preview_file_content(self.queue_role_session, self.s3_settings, node)
                    else:
                        self.handle_download(node)
                    continue
                elif ch == "i" and items and items[self.cursor].node_type == NodeType.FILE:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                    show_file_info(items[self.cursor])
                    continue
                elif ch == "v" and items:
                    node = items[self.cursor]
                    if node.node_type == NodeType.FILE and is_image(node.name):
                        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                        open_image_viewer(self.queue_role_session, self.s3_settings, node)
                        self.message = f"🖼️  Opened {node.name}"
                        continue
                elif ch == "m":
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                    show_manifest_list(self.root)
                    continue
                elif ch == "q":
                    console.clear()
                    break
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


# === Layer 8: CLI Entry Point ===


@main.command(name="browse")
@click.option("--profile", help="The AWS profile to use.")
@click.option("--farm-id", help="The AWS Deadline Cloud Farm to use.")
@click.option("--queue-id", help="The AWS Deadline Cloud Queue to use.")
@click.option(
    "--job-id", help="The AWS Deadline Cloud Job to browse. If omitted, shows job selector."
)
@_handle_error
def cli_browse(**args):
    """
    Interactively browse input and output files of a Deadline Cloud job.

    If --job-id is not provided, shows a job selection screen.
    Navigate with arrow keys, Enter to select, 'd' to download, 'q' to quit.
    """
    config: Optional[ConfigParser] = _apply_cli_options_to_config(
        required_options={"farm_id", "queue_id"}, **args
    )
    farm_id = config_file.get_setting("defaults.farm_id", config=config)
    queue_id = config_file.get_setting("defaults.queue_id", config=config)
    job_id = args.get("job_id") or config_file.get_setting("defaults.job_id", config=config)

    if not sys.stdin.isatty():
        raise click.ClickException("This command requires an interactive terminal")

    boto3_session = api.get_boto3_session(config=config)
    deadline = api.get_boto3_client("deadline", config=config)

    # If no job_id, show job selector
    if not job_id:
        selector = JobSelectorTUI(farm_id, queue_id, deadline)
        job_id = selector.run()
        if not job_id:
            return

    job = deadline.get_job(farmId=farm_id, queueId=queue_id, jobId=job_id)
    job_name = job["name"]
    job_status = job.get("taskRunStatus", "UNKNOWN")

    queue = deadline.get_queue(farmId=farm_id, queueId=queue_id)
    if "jobAttachmentSettings" not in queue:
        raise click.ClickException("Queue does not have job attachments configured")

    s3_settings = JobAttachmentS3Settings(**queue["jobAttachmentSettings"])
    queue_role_session = api.get_queue_user_boto3_session(
        deadline=deadline,
        config=config,
        farm_id=farm_id,
        queue_id=queue_id,
        queue_display_name=queue["displayName"],
    )

    browser = JobBrowserTUI(
        farm_id=farm_id,
        queue_id=queue_id,
        job_id=job_id,
        job_name=job_name,
        job_status=job_status,
        boto3_session=boto3_session,
        queue_role_session=queue_role_session,
        s3_settings=s3_settings,
    )
    browser.run()
