# Deadline Job Browser - User Guide

An interactive terminal UI for browsing and downloading job attachments from AWS Deadline Cloud.

## Quick Start

```bash
# Browse jobs and select one interactively
deadline browse

# Browse a specific job directly
deadline browse --job-id job-abc123def456
```

## Job Selection Screen

When you run `deadline browse` without a job ID, you'll see a list of recent jobs:

```
╭─────────────────── Deadline Job Browser ───────────────────╮
│ 🎬 Select a Job                              Queue: queue-x│
╰────────────────────────────────────────────────────────────╯

▶  ✓ SUCCEEDED  My Render Job              2m ago   ...abc123
   ● RUNNING    Animation Batch           10m ago   ...def456
   ✗ FAILED     Test Job                   1h ago   ...ghi789
```

### Controls
| Key | Action |
|-----|--------|
| ↑/↓ | Move selection up/down |
| Enter | Select job and open file browser |
| r | Refresh job list |
| q | Quit |

## File Browser Screen

After selecting a job, you can browse its input and output files:

```
╭─────────────────── Deadline Job Browser ───────────────────╮
│ 🎬 My Render Job                            ✓ SUCCEEDED    │
╰────────────────────────────────────────────────────────────╯
📍 Job › output › /renders

▶  💾 /renders/frames                              120 files
   📁 textures                                      45 files
   📄 scene.blend                                  2.4 MB
   🖼️  preview.png                                 156 KB
```

### Controls
| Key | Action |
|-----|--------|
| ↑/↓ | Move selection up/down |
| ←   | Go back to parent folder |
| →/Enter | Enter folder or view file info |
| d | Download selected file or folder |
| i | Show file information |
| v | View image (opens in system viewer) |
| m | Show all manifest files |
| q | Quit |

## Downloading Files

Press `d` on any file or folder to download:

- **Single file**: Downloads to specified directory with original filename
- **Folder**: Downloads all files with progress bar, preserving folder structure

```
Download to: /home/user/downloads
Downloading... ━━━━━━━━━━━━━━━━━━━━ 100%
✅ Downloaded 120 files to /home/user/downloads
```

## File Icons

| Icon | Type |
|------|------|
| 📦 | Category (input/output) |
| 💾 | Manifest root path |
| 📁 | Folder |
| 📄 | File |
| 🖼️ | Image file |
| 📝 | Text/log file |

## Options

```bash
deadline browse [OPTIONS]

Options:
  --job-id TEXT    Job ID to browse directly (skip job selection)
  --farm-id TEXT   Override default farm
  --queue-id TEXT  Override default queue
  --profile TEXT   AWS profile to use
```

## Examples

```bash
# Interactive job selection
deadline browse

# Browse specific job
deadline browse --job-id job-f2bb8e71194c418db5a57b45590638d5

# Use different farm/queue
deadline browse --farm-id farm-xxx --queue-id queue-yyy
```

## Requirements

- Interactive terminal (TTY)
- AWS credentials configured
- Default farm and queue set in Deadline config (or provided via options)
