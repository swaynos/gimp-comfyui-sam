# Editor UI/UX and Interaction Specification

## Overview

The SAM selection editor is a dedicated, non-modal plugin window that allows users to place point prompts on an immutable source snapshot, submit inference to ComfyUI, inspect the returned mask overlay, and apply the result to GIMP as an undoable selection.

```text
+----------------------------------------------------------------------------------------------------+
|  GIMP SAM Selection                                                             [Settings ⚙]  [ x ]|
+----------------------------------------------------------------------------------------------------+
|  Source: [ Active Layer | Sample Merged ]    Tool: [ (+) Positive | (-) Negative ]   [ Reset Points ]|
|  View:   [ 🔍 Fit | 1:1 ]    Mask: [ 👁 Peek (Tab) ]  Opacity: [====o====] 50%                     |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|                                       PREVIEW CANVAS                                               |
|                                                                                                    |
|     • Mouse wheel: Zoom (cursor-centered)         [+] Point 1 (Green circle/plus)                  |
|     • Middle-drag / Space+drag: Pan               [-] Point 2 (Red square/dash)                    |
|     • Left-click: Add Positive point                                                               |
|     • Shift+Left / Right-click: Add Negative                                                       |
|     • Drag point: Move / Reposition                [ Semi-transparent mask overlay ]               |
|     • Delete key / Right-click point: Delete                                                       |
|                                                                                                    |
+----------------------------------------------------------------------------------------------------+
|  [⚙ Collapsible Settings: Server URL | Threshold (0.50) | Refinement Passes (2) | Test Connection] |
+----------------------------------------------------------------------------------------------------+
|  Status: [ 🟢 Ready ] Active layer: "Background" (2048x2048)            |   [ Cancel ] [ Generate ]|
|  Mode:   [ Replace | Add | Subtract | Intersect ]                       |   [ Apply ]  [ Close ]   |
+----------------------------------------------------------------------------------------------------+
```

---

## Window Management and Modality

- **Window Type**: Top-level `Gtk.Window` configured as a utility dialog (`transient-for` the GIMP main window).
- **Modality**: Non-modal. The user can interact with the GIMP canvas (e.g. pan, zoom, inspect layers) while the editor is open.
- **Window Positioning**: Floats above the GIMP main window so it is not hidden behind the document canvas.
- **Closure**: Closing the window cancels active requests locally, cleans up temporary local files, and terminates the editor session without modifying the GIMP document.

---

## Canvas and Viewport Interaction

### Navigation
- **Zoom**: Mouse scroll wheel zooms centered on the current cursor position.
- **Pan**: Middle-mouse drag or `Spacebar` + Left-mouse drag.
- **Quick Zoom Buttons**:
  - `Fit`: Scales the entire source image to fit within the visible viewport.
  - `1:1`: Sets display scale to 100% (1 preview pixel = 1 source pixel).

### Point Placement and Manipulation
- **Add Positive Point**:
  - Left-click on the canvas when in Positive tool mode, or Left-click directly.
  - Rendered as a green circle with a `+` symbol and numeric order index.
- **Add Negative Point**:
  - `Shift` + Left-click or Right-click on empty canvas, or Left-click when in Negative tool mode.
  - Rendered as a red square with a `-` symbol and numeric order index.
- **Move Point**:
  - Left-click and drag any existing point marker to reposition it.
- **Delete Point**:
  - Click on a point marker and press `Delete` / `Backspace`, or Right-click on an existing point marker.
- **Reset Points**:
  - Dedicated `Reset Points` toolbar button removes all positive and negative points and invalidates any existing mask result.

---

## Mask Visualization and Inspection

- **Overlay**: Semi-transparent tinted overlay (default translucent cyan / ruby) rendered on top of the source image.
- **Opacity Slider**: Interactive slider (range 0% to 100%, default 50%) adjusting the alpha channel of the preview mask overlay. Does not alter the full-resolution mask data.
- **Peek / Toggle**:
  - `Peek` toolbar button or `Tab` keyboard shortcut toggles the visibility of the mask overlay instantly to allow comparing mask edges against source pixels.

---

## Source Scope Switching

- **Selector**: Top toolbar segmented control: `[ Active Layer | Sample Merged ]`.
- **Confirmation on Change**: If points or an active/stale result exist, switching source scope prompts the user for confirmation before discarding points and resetting the preview snapshot.
- **Snapshot Refresh**: Switching source captures a fresh immutable snapshot from GIMP and resets the preview cache.

---

## Settings and Parameters

Accessed via a collapsible drawer or popover (`Settings ⚙`):
- **Server Endpoint**: Text entry with validation and a `Test Connection` button (`GET /system_stats`).
- **Threshold**: Slider and numerical entry (range `0.00` – `1.00`, step `0.01`, default `0.50`).
- **Refinement Passes**: Spin box (range `0` – `5`, step `1`, default `2`).
- Changing any parameter marks any current result as `stale`.

---

## Status and Lifecycle Feedback

Located in the bottom status bar:
- **State Pill**:
  - `🟢 Ready`: Ready for point placement or generation.
  - `🔵 Preparing / Uploading`: Generating source PNG and uploading to endpoint.
  - `⏳ Inferring (ComfyUI)`: Prompt queued or executing in SAM3 node.
  - `🟡 Stale (Points/Settings Changed)`: Result exists but parameters or points have changed; Apply is disabled.
  - `🔴 Failed / Error`: Request failed or timed out; shows actionable tooltip.
- **Progress Spinner**: Active during network operations (`preparing`, `submitted`, `running`).
- **Contextual Hint**: Displays guidance (e.g. *"Click on the image to add at least 1 positive point"* or *"Click Apply to update GIMP selection"*).

---

## Selection Application and Actions

- **Selection Modes**: Segmented radio group: `[ Replace | Add | Subtract | Intersect ]` (default: `Replace`).
- **Generate Button**: Submits the current point set and settings to ComfyUI. Disabled if there are no positive points.
- **Cancel Button**: Enabled during active requests (`preparing`, `submitted`, `running`); halts local waiting and ignores late responses.
- **Apply Button**:
  - Enabled only when status is `current` and source revision is validated.
  - Commits the selection to the GIMP image as a single undoable step.
  - **Keeps the editor window open** to allow progressive multi-part selections without reopening the tool.
- **Close Button**: Dismisses the editor window, cleans up resources, and leaves the GIMP selection intact.
