# Design: `deadline simple-plugins` GUI

## Overview

Add a `deadline simple-plugins` command that opens a PySide/Qt GUI dialog for uploading, browsing, and removing plugin files from the S3 convention path (`s3://<bucket>/plugins/<os>/<dcc>/<version>/`) in a queue's job attachment bucket. This follows the same pattern as `deadline config gui` — a CLI entry point that launches a standalone Qt window.

## Problem Statement

The Simple Plugin Delivery feature requires customers to upload plugin files to a specific S3 prefix in their job attachment bucket. Today, customers must navigate the S3 console manually, know the correct bucket, and construct the path convention themselves. This is error-prone and requires AWS console familiarity that many target customers (small studios, individual artists) lack.

A GUI provides the simplest possible experience: select a queue, pick the DCC, drag and drop files, done. The bucket and path convention are resolved automatically.

## CLI Interface

```bash
# Open the simple plugins GUI (farm from flag)
deadline simple-plugins --farm-id farm-xxxx

# Use default farm from config
deadline simple-plugins

# Install GUI dependencies if needed
deadline simple-plugins --install-gui
```

| Option | Required | Description |
|--------|----------|-------------|
| `--farm-id` | No (falls back to config `defaults.farm_id`) | The Deadline Cloud farm to scope queue selection |
| `--install-gui` | No | Install PySide GUI dependencies if not already installed |

## GUI Layout

```
┌─ Simple Plugins — AWS Deadline Cloud ────────────────────────────┐
│                                                                  │
│  ┌─ Farm and Queue ────────────────────────────────────────────┐ │
│  │  Farm:     [ My Farm                           ▼ ] [↻]     │ │
│  │  Queue:    [ My Production Queue               ▼ ] [↻]     │ │
│  │  Bucket: s3://deadline-ja/RootPrefix/plugins/               │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌─ Upload ────────────────────────────────────────────────────┐ │
│  │  Worker OS:  (● Linux  ○ Windows)                           │ │
│  │  DCC: [ maya ▼ ]              Version: [ 2025       ]       │ │
│  │  ☐ Generic (DCC-agnostic, ignores DCC and version)          │ │
│  │                                                             │ │
│  │  ┌─────────────────────────────────────────────────────┐    │ │
│  │  │                                                     │    │ │
│  │  │       Drag and drop plugin files here               │    │ │
│  │  │            or click Browse                          │    │ │
│  │  │                                                     │    │ │
│  │  └─────────────────────────────────────────────────────┘    │ │
│  │  [Browse…] [Clear]                                          │ │
│  │  ┌─ Selected files ──────────────────────────────────────┐  │ │
│  │  │  my-plugin.so  (1.2 MB)                               │  │ │
│  │  │  my-other-plugin.so  (340 KB)                          │  │ │
│  │  └───────────────────────────────────────────────────────┘  │ │
│  │  [Upload]                                                   │ │
│  │  ████████████████████░░░░░░░░  Uploading… 3 / 5            │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌─ Uploaded Plugins ──────────────────────────────────────────┐ │
│  │  ▼ linux                                                    │ │
│  │    ▼ maya / 2025                                            │ │
│  │      ☑ my-plugin.so        1.2 MB   2026-04-10 14:30       │ │
│  │      ☐ my-other-plugin.so  340 KB   2026-04-10 14:30       │ │
│  │    ▼ nuke / 15.1                                            │ │
│  │      ☐ custom-gizmo.nk     12 KB   2026-04-08 09:15        │ │
│  │  ▼ generic                                                  │ │
│  │    ☐ my-script.sh           2 KB   2026-04-11 11:00         │ │
│  │                                                             │ │
│  │  [Delete Selected] [Refresh]          4 file(s), 1.6 MB    │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│                                                      [ Close ]   │
└──────────────────────────────────────────────────────────────────┘
```

## Startup Behavior

On launch, the dialog performs a cascading initialization:

1. Read `defaults.farm_id` and `defaults.queue_id` from the workstation config (or `--farm-id` flag).
2. Create a local `ConfigParser` copy so the dialog never mutates the global config file.
3. Call `set_config()` on both `DeadlineFarmListComboBoxController` and `DeadlineQueueListComboBoxController`.
4. Set `_awaiting_farms_for_cascade = True` and call `farm_box.refresh_list()`.
5. When `DeadlineUIController.farms_updated` fires → the farm combo box auto-selects the default farm from config → set `_awaiting_queues_for_cascade = True` and call `queue_box.refresh_list()`.
6. When `DeadlineUIController.queues_updated` fires → the queue combo box auto-selects the default queue from config → fire async `_resolve_attachment_settings_async()`.
7. When the async GetQueue call completes → populate the bucket label, enable the upload widget, and trigger the browser to load the plugin list.

If any step fails (no farms, no queues, no attachment settings), the UI shows an orange status message and the upload/browser remain disabled.

## Button and Interaction Behavior

### Farm dropdown

| Trigger | Behavior | Async? | Refresh side-effects |
|---------|----------|--------|---------------------|
| User selects a different farm | Update local config `defaults.farm_id`, clear `defaults.queue_id`, call `queue_box.set_config()` + `queue_box.refresh_list()` | Queue list loads async via `DeadlineUIController` | Queue dropdown repopulates. Bucket label clears. Upload and browser disabled until a queue is selected and resolved. |
| Refresh button (built into combo box) | Re-fetches the farm list from the API | Yes (controller) | Farm dropdown repopulates, selected farm preserved if still in list |

### Queue dropdown

| Trigger | Behavior | Async? | Refresh side-effects |
|---------|----------|--------|---------------------|
| User selects a different queue | Fire `_resolve_attachment_settings_async()` | Yes (AsyncTaskRunner) | Bucket label shows "⏳ Loading…". On success: bucket label updates, upload widget enabled, browser loads plugin list. On error: orange error message. |
| Refresh button (built into combo box) | Re-fetches the queue list for the current farm | Yes (controller) | Queue dropdown repopulates |

### Worker OS radio buttons

| Trigger | Behavior | Async? | Refresh side-effects |
|---------|----------|--------|---------------------|
| User toggles Linux/Windows | Updates the S3 prefix used for upload (`linux/` vs `windows/`) | No | None — only affects the next upload |

### DCC dropdown

| Trigger | Behavior | Async? | Refresh side-effects |
|---------|----------|--------|---------------------|
| User selects or types a DCC name | Updates the S3 prefix used for upload | No | None |
| Default on startup | `maya` (index 0) via `setCurrentIndex(0)` | — | — |

### Version text field

| Trigger | Behavior | Async? | Refresh side-effects |
|---------|----------|--------|---------------------|
| User types a version | Updates the S3 prefix used for upload | No | None |

### Generic checkbox

| Trigger | Behavior | Async? | Refresh side-effects |
|---------|----------|--------|---------------------|
| User checks | Disables DCC dropdown and version field. Upload prefix becomes `plugins/generic/` | No | None |
| User unchecks | Re-enables DCC dropdown and version field | No | None |

### Drop zone

| Trigger | Behavior | Async? | Refresh side-effects |
|---------|----------|--------|---------------------|
| User drags files onto the zone | Files added to the selected files list (deduplicated). If a directory is dropped, all files within it are added recursively. | No | File list widget updates. Upload button enables if bucket is set. |
| Visual feedback | Border changes from dashed gray to dashed blue on drag hover | No | — |

### Browse button

| Trigger | Behavior | Async? | Refresh side-effects |
|---------|----------|--------|---------------------|
| Click | Opens native `QFileDialog.getOpenFileNames()` | No (blocks on OS dialog) | Selected files added to list (deduplicated). Upload button enables if bucket is set. |

### Clear button

| Trigger | Behavior | Async? | Refresh side-effects |
|---------|----------|--------|---------------------|
| Click | Clears all selected files from the list | No | File list empties. Upload button disables. |

### Upload button

| Trigger | Behavior | Async? | Refresh side-effects |
|---------|----------|--------|---------------------|
| Click (no bucket) | Shows warning: "Select a queue with job attachment settings." | No | None |
| Click (no DCC/version, non-generic) | Shows warning: "Enter a DCC name and version, or check 'Generic'." | No | None |
| Click (valid) | Disables upload button. Shows progress bar below button. Fires `AsyncTaskRunner` to upload files to S3. Progress bar updates per-file via `QMetaObject.invokeMethod` from background thread. | Yes (AsyncTaskRunner) | On success: info dialog, files cleared, `upload_completed` signal emitted → browser refreshes. On error: error dialog, files preserved for retry. Progress bar hides. Upload button re-enables. |

### Delete Selected button

| Trigger | Behavior | Async? | Refresh side-effects |
|---------|----------|--------|---------------------|
| Click (nothing checked) | No-op (button should be disabled) | — | — |
| Click (items checked) | Shows confirmation dialog: "Delete N file(s)? This cannot be undone." If Yes: calls S3 `DeleteObjects`. If No: no-op. | No (blocking S3 call — see Gaps) | On success: info dialog, browser refreshes via `self.refresh()`. On error: error dialog. |
| Enable/disable logic | Enabled when ≥1 leaf item is checked. Updated on both `itemChanged` and `itemClicked` signals. | — | — |

### Refresh button (browser)

| Trigger | Behavior | Async? | Refresh side-effects |
|---------|----------|--------|---------------------|
| Click | Calls `_load_plugins()` which lists S3 objects under `plugins/` prefix | No (blocking S3 call — see Gaps) | Tree repopulates. Status label updates with file count and total size. |

### Close button

| Trigger | Behavior | Async? | Refresh side-effects |
|---------|----------|--------|---------------------|
| Click | Closes the dialog | No | None |

## Refresh Matrix

This table summarizes which UI elements refresh after each user action:

| Action | Farm dropdown | Queue dropdown | Bucket label | Upload form | Browser tree |
|--------|:---:|:---:|:---:|:---:|:---:|
| Startup | ✅ load | ✅ load (cascade) | ✅ resolve (async) | ✅ enable | ✅ load |
| Change farm | — | ✅ reload | ✅ clear → resolve | ✅ disable → enable | ✅ clear → reload |
| Change queue | — | — | ✅ resolve (async) | ✅ disable → enable | ✅ reload |
| Upload files | — | — | — | ✅ clear files | ✅ reload |
| Delete files | — | — | — | — | ✅ reload |
| Click Refresh (browser) | — | — | — | — | ✅ reload |

## S3 Path Convention

```
s3://<bucket>/<rootPrefix>/plugins/<os>/<dcc>/<version>/<filename>
s3://<bucket>/<rootPrefix>/plugins/generic/<filename>
```

- `<os>`: `linux` or `windows`
- `<dcc>`: lowercase DCC name (editable combo box, not a strict allowlist)
- `<version>`: freeform version string
- `<filename>`: original filename preserved

## Implementation Details

### Files added

- `src/deadline/client/cli/_groups/simple_plugins_group.py` — Click command.
- `src/deadline/client/ui/dialogs/simple_plugins_dialog.py` — `SimplePluginsDialog` (QDialog).
- `src/deadline/client/ui/widgets/simple_plugins_upload_widget.py` — Upload form widget.
- `src/deadline/client/ui/widgets/simple_plugins_browser_widget.py` — Plugin browser tree widget.

### Files modified

- `src/deadline/client/cli/_groups/__init__.py` — Register `simple_plugins_group`.

### Key patterns

- `gui_context_for_cli` for Qt app lifecycle (no `app.exec()` needed — dialog uses modal `exec_()`).
- `DeadlineFarmListComboBoxController` / `DeadlineQueueListComboBoxController` for farm/queue dropdowns with async loading.
- `AsyncTaskRunner` for background S3 operations (queue resolution, file upload).
- `DeadlineUIController` signals (`farms_updated`, `queues_updated`) for cascading initialization.
- Local `ConfigParser` copy to avoid mutating the global workstation config.
- `Qt.CheckState.Checked` (not `Qt.Checked`) for PySide6 enum compatibility.

## Security Considerations

- Queue-scoped credentials via `api.get_queue_user_boto3_session()` — same trust boundary as job attachments.
- Files in the `plugins/` prefix execute on workers with DCC application permissions.
- No new S3 buckets or IAM policies required.

## Testing

### CLI tests (`test_cli_simple_plugins.py`)
- Command registered and shows help
- `--farm-id` and `--install-gui` passed correctly
- `gui_context_for_cli` called with correct args

### Dialog tests (`test_simple_plugins_dialog.py`)
- Farm ID initialization (explicit and config fallback)
- Child widget creation
- `_set_no_bucket` error display
- `_on_resolve_success` populates bucket
- `_on_resolve_error` shows error

### Upload widget tests (`test_simple_plugins_upload_widget.py`)
- Initial state (button disabled, DCC defaults to maya index 0)
- S3 target enable/disable
- Generic checkbox toggles DCC/version fields
- Prefix construction (linux/maya, windows/nuke, generic)
- File deduplication and clear
- Validation warnings

### Browser widget tests (`test_simple_plugins_browser_widget.py`)
- Initial state (empty tree, delete disabled)
- Tree population with nested groups
- Checked key collection with `Qt.CheckState.Checked`
- S3 list integration (mocked)
- Error handling
- Refresh clears tree when no bucket

## Gaps and Future Work

### Resolved gaps

1. ~~Browser list is synchronous.~~ **Fixed.** `_load_plugins()` now uses `AsyncTaskRunner` with a "⏳ Loading…" status label. Tree populates on the main thread via success callback.

2. ~~Delete is synchronous.~~ **Fixed.** `_do_delete()` now uses `AsyncTaskRunner` with a "⏳ Deleting…" status label. Browser refreshes automatically on success.

3. ~~No error retry for upload.~~ **Fixed.** On upload failure, a `QMessageBox.critical` popup offers Retry / Cancel. Files are preserved in the list so Retry re-uploads the same set. Already-uploaded files are overwritten idempotently (accepted — S3 PutObject is idempotent).

4. ~~No upload cancellation.~~ **Fixed.** A "Cancel" button appears next to "Upload" during upload. Clicking it calls `AsyncTaskRunner.cancel("upload_plugins")`. Progress bar shows "Cancelled". Files remain in the list for re-upload.

5. ~~No duplicate file warning on upload.~~ **Accepted.** S3 PutObject is idempotent — overwriting an existing file with the same content is a no-op, and overwriting with different content is the intended behavior (updating a plugin). No warning needed.

6. ~~No file size validation.~~ **Accepted.** `boto3 upload_file()` handles multipart upload automatically for large files. No user-facing validation needed.

7. ~~DCC name is freeform.~~ **Accepted.** Freeform is intentional — it keeps the CLI forward-compatible as new DCCs are added. The editable combo box provides suggestions for common names.

8. ~~No version auto-detection.~~ **Accepted.** Version auto-detection from Conda packages is a future enhancement, not a gap.

9. ~~Browser doesn't auto-refresh on external changes.~~ **Accepted.** Manual Refresh button is sufficient. Auto-refresh would require polling S3 which adds cost and complexity.

10. ~~No "Select All" / "Deselect All" in browser.~~ **Fixed.** Folder nodes (OS, DCC, version) are now checkable. Clicking a folder checkbox propagates the check state to all descendant files, enabling bulk select/deselect at any level.

11. ~~Queue resolution cache.~~ **Accepted.** Not a concern — `GetQueue` is fast and infrequent (only on queue change).

12. ~~No confirmation before closing with pending upload.~~ **Accepted.** The `AsyncTaskRunner` cancels tasks when the parent widget is destroyed, so closing the dialog cancels in-flight uploads cleanly.

### Additional improvements made

- **Browse Folder button.** A "Browse Folder…" button opens `QFileDialog.getExistingDirectory()` and recursively adds all files from the selected directory. This complements drag-and-drop of directories.

- **Drop zone accepts directories.** Dropping a folder recursively adds all files within it.

### Future iterations

1. Integrate plugin upload as a tab in `deadline bundle gui-submit`.
2. Add a "Copy S3 path" button for each uploaded plugin.
3. Add a "Validate plugin" feature that checks file type before upload.
4. Remember last-used OS/DCC/version across sessions (persist to config).
