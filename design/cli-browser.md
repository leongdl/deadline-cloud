# CLI Browser Design

## Overview

Interactive TUI (Terminal User Interface) to browse and download input/output files of a Deadline Cloud job using the `rich` library for beautiful terminal rendering.

## Command

```bash
deadline browse [--job-id <job-id>] [--farm-id] [--queue-id] [--profile]
```

If `--job-id` is omitted, shows a job selection screen sorted by most recent first.

## UI Components

### Job Selection Screen (when no --job-id)
```
╭─────────────────── Deadline Job Browser ───────────────────╮
│ 🎬 Select a Job                              Farm: farm-xxx│
╰────────────────────────────────────────────────────────────╯

▶  ● SUCCEEDED  My Render Job              2 min ago   job-abc123
   ● RUNNING    Animation Batch           10 min ago   job-def456
   ● FAILED     Test Job                   1 hr ago    job-ghi789
   ● SUCCEEDED  Scene Export              2 hrs ago    job-jkl012

                                          Page 1/5 (20 of 100 jobs)

╭────────────────────────────────────────────────────────────═
│ ↑↓ nav  ←→ page  Enter select  r refresh  q quit           │
╰────────────────────────────────────────────────────────────╯
```

### File Browser Screen (after job selected)
```
┌─────────────────── Deadline Job Browser ───────────────────┐
│ 🎬 My Render Job                            ● SUCCEEDED    │
└────────────────────────────────────────────────────────────┘
📍 Job › output › /renders

▶  💾 /renders/frames                              120 files
   📁 textures                                      45 files
   📄 scene.blend                                  2.4 MB
   🖼️  preview.png                                 156 KB

✅ Downloaded 120 files to /home/user/downloads

┌────────────────────────────────────────────────────────────┐
│ ←→↑↓ nav  Enter open  d download  i info  v view  q quit   │
└────────────────────────────────────────────────────────────┘
```

## Features

1. **Job Selection Screen** - Browse recent jobs sorted by creation time
2. **Header Panel** - Job name with colored status indicator
3. **Breadcrumb** - Current path in tree
4. **File List** - Icons, names, sizes with cursor highlight
5. **Progress Bar** - For folder downloads
6. **File Preview** - In-terminal preview for text/binary files
7. **Message Area** - Success/error feedback
8. **Help Bar** - Keyboard shortcuts

## Icons

| Type | Icon |
|------|------|
| Category (input/output) | 📦 |
| Manifest Root | 💾 |
| Folder | 📁 |
| File | 📄 |
| Image | 🖼️ |
| Text/Log | 📝 |
| Script | 📜 |

## Keyboard Controls

| Key | Action |
|-----|--------|
| ↑/↓ | Navigate items in list |
| ←   | Go back to parent (same as 'b') |
| →   | Enter folder / Show file info (same as Enter) |
| Enter | Enter folder / Show file info |
| b | Go back to parent |
| d | Download & preview file / Download folder |
| i | Show file info panel |
| v | View image (opens system viewer) |
| m | List all manifest files (debug) |
| q | Quit |

## Data Flow

```
1. Load farm-id/queue-id from config defaults if not provided
2. Get job details (status, attachments)
3. Load input manifests from job.attachments.manifests[].inputManifestPath
4. Load output manifests via get_output_manifests_by_asset_root()
5. Merge manifests per root using merge_asset_manifests()
   - Later manifests eclipse earlier ones for same file path
   - Ensures latest version of each file is shown
6. Build tree structure from merged manifest paths
7. Download files from S3:
   - Source: {rootPrefix}/Data/{hash}.xxh128
   - Destination: {download_dir}/{original_filename} (preserves actual file name)
```

## Tree Structure

```
Job (root)
├── input (category)
│   └── /path/to/root (manifest_root)
│       └── folder/ (folder)
│           └── file.txt (file)
└── output (category)
    └── /path/to/output (manifest_root)
        └── result.png (file)
```

## Dependencies

- `rich` - Terminal rendering (already in project dependencies)

## Implementation

### Setup

- File: `src/deadline/client/cli/_groups/browse_group.py`
- Registered in: `src/deadline/client/cli/_groups/__init__.py`

Add to `__init__.py`:
```python
__all__ = [..., "browse_group"]
from . import browse_group as browse_group
```

### Module Structure (Pyramid Style)

```
cli_browse()                    # Entry point - CLI command
    └── JobBrowserTUI.run()     # Main loop
            ├── load_manifests()
            ├── render()
            ├── handle_input()
            └── actions...
```

### Pseudo Code

```python
# === Constants & Types ===

IMAGE_EXTENSIONS = {".png", ".jpg", ...}

class NodeType(Enum):
    ROOT, CATEGORY, MANIFEST_ROOT, FOLDER, FILE

class TreeNode:
    name, node_type, path, size, hash, parent, children


# === Layer 1: Utilities ===

def format_size(size: int) -> str:
    """Convert bytes to human readable (KB, MB, GB)."""

def format_time_ago(dt) -> str:
    """Convert datetime to relative time (e.g., '2m ago')."""

def is_image(filename: str) -> bool:
    """Check if file extension is an image type."""

def get_all_files_under(node: TreeNode) -> list[TreeNode]:
    """Recursively collect all FILE nodes under a node."""


# === Layer 2: Tree Construction ===

def build_file_tree(manifest, root_name: str) -> TreeNode:
    """
    Convert flat manifest paths into hierarchical TreeNode structure.
    Splits paths by '/' and creates folder/file nodes.
    """


# === Layer 3: Manifest Loading ===

def load_input_manifests(job, s3_prefix, s3_bucket, session) -> list[TreeNode]:
    """
    Load input manifests from job.attachments.manifests[].inputManifestPath.
    Returns list of TreeNodes for each manifest root.
    """

def load_output_manifests(s3_settings, farm_id, queue_id, job_id, session) -> list[TreeNode]:
    """
    Load and merge output manifests via get_output_manifests_by_asset_root().
    Merging ensures later files eclipse earlier ones.
    Returns list of TreeNodes for each output root.
    """


# === Layer 4: TUI Rendering ===

def get_node_icon(node: TreeNode) -> str:
    """Return emoji icon based on node type and file extension."""

def get_status_style(status: str) -> tuple[str, str]:
    """Return color and icon for job status."""

def render_header(title: str, subtitle: str):
    """Render title panel with subtitle."""

def render_breadcrumb(current_node: TreeNode):
    """Render path breadcrumb: Job › output › /path."""

def render_file_list(items: list[TreeNode], cursor: int):
    """Render file/folder table with cursor highlight."""

def render_help_bar(keys: list[tuple[str, str]]):
    """Render keyboard shortcut help panel."""


# === Layer 5: File Operations ===

def download_single_file(session, s3_settings, node: TreeNode, dest_dir: str) -> str:
    """
    Download one file from S3.
    Source: {rootPrefix}/Data/{hash}.xxh128
    Dest: {dest_dir}/{node.name}
    Returns local path.
    """

def download_folder(session, s3_settings, node: TreeNode, dest_dir: str) -> int:
    """
    Download all files under node with progress bar.
    Preserves relative path structure.
    Returns file count.
    """

def show_file_info(node: TreeNode):
    """Display file info panel (name, path, size, hash)."""

def preview_file_content(session, s3_settings, node: TreeNode):
    """
    Download file and show preview in terminal:
    - Text files: syntax-highlighted content (first 4KB)
    - Binary files: hex dump preview
    - Images: prompt to use 'v' for viewer
    """

def open_image_viewer(session, s3_settings, node: TreeNode):
    """Download image to /tmp and open with system viewer."""

def show_manifest_list(root: TreeNode):
    """Show table of all manifest roots with file counts."""


# === Layer 6: Job Selector TUI ===

class JobSelectorTUI:
    def __init__(self, farm_id, queue_id, deadline_client):
        """Initialize with farm/queue and API client."""

    def load_jobs(self):
        """Fetch recent jobs sorted by creation time descending."""

    def render(self):
        """Render job list with status, name, time, and ID columns."""

    def run(self) -> Optional[str]:
        """
        Main loop: render -> read input -> handle action.
        Returns selected job_id or None if quit.
        """


# === Layer 7: File Browser TUI ===

class JobBrowserTUI:
    def __init__(self, farm_id, queue_id, job_id, job_name, job_status,
                 boto3_session, queue_role_session, s3_settings):
        """Initialize browser state."""

    def load_manifests(self):
        """Load input/output manifests into tree structure."""

    def render(self):
        """Render full TUI screen."""

    def handle_download(self, node: TreeNode):
        """Prompt for destination and download folder."""

    def run(self):
        """Main event loop: render -> read input -> handle action."""


# === Layer 8: CLI Entry Point ===

@main.command(name="browse")
@click.option("--profile", "--farm-id", "--queue-id", "--job-id")
def cli_browse(**args):
    """
    Entry point:
    1. Load config defaults for farm/queue
    2. If no job_id, show JobSelectorTUI
    3. Get job details and status
    4. Get queue S3 settings and role session
    5. Launch JobBrowserTUI
    """
```

### Function Size Limits

All functions must be ≤75 lines. Complex logic should be split:
- `load_manifests()` → calls `load_input_manifests()` + `load_output_manifests()`
- `render()` → calls `render_header()` + `render_breadcrumb()` + `render_file_list()` + `render_help_bar()`
- `run()` → calls `render()` + `read_keypress()` + `handle_action()`
