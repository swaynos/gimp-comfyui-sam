# Requirements

## Status and terms

This is the normative v1 product specification. It defines required behavior,
not implemented behavior. `ACCEPTANCE.md` defines the evidence needed to meet
these requirements, and `DECISIONS.md` records v1 choices and proof gates.

**Source** is the exact pixel image sent to ComfyUI. **Source revision** is the
source identity plus every property that affects pixels, dimensions, or canvas
placement. A **current result** matches the active source revision and all
generation settings. A stale result cannot be applied.

## Goal and constraints

Provide point-guided selection in an existing GIMP installation through ComfyUI
SAM inference. Users place positive and negative points before one explicit
generation request. The plugin must not require a custom GIMP build, replace
Fuzzy Select, or intercept arbitrary main-canvas mouse events.

Large assets are a primary use case. Point editing must not repeatedly export,
encode, render, or upload the full-resolution source. The initial target is
Flatpak GIMP 3.2.6 on Linux Mint. The backend endpoint is configurable and must
be confirmed before the first upload to a new endpoint.

## Editor

The plugin opens a plugin-owned, non-modal editor window from a GIMP menu action,
configured as a utility window kept transient-for and floating above the GIMP
main canvas. Native docking is not a v1 claim. Detailed interaction rules are
specified in `EDITOR_UX.md`. The editor provides:

- Positive and negative points with labels, index numbers, and distinct shapes as
  well as color (green circle for positive, red square for negative).
- Direct mouse and keyboard bindings: Left-click adds Positive, Shift+Left-click
  or Right-click adds Negative, dragging repositions points, and Delete key or
  Right-click on an existing point deletes it.
- Zoom (cursor-centered via scroll wheel, plus `Fit` and `1:1` buttons) and pan
  (middle-click drag or Spacebar+drag) with correct point placement at every scale.
- A returned-mask overlay with an alpha opacity slider and an instant Peek /
  Toggle button (`Tab` key) to compare mask boundaries against source pixels.
- Collapsible inference settings allowing configuration of endpoint URL (with
  connection test), threshold (`0.00` – `1.00`), and refinement passes (`0` – `5`).
- Explicit Generate, Cancel request, Apply, and Close actions.
- A status bar with a lifecycle state pill (`Ready`, `Preparing`, `Inferring`,
  `Current`, `Stale`, `Failed`), an activity spinner, and contextual guidance hints.

Point editing never queues inference. `Reset points` removes both point sets and
invalidates the result. `Cancel request` stops local waiting, retains points,
and makes late responses unusable. `Close` does the same, releases local
resources, and makes all later callbacks unusable. These actions never edit the
GIMP document.

## Source scope

Active layer is the default source. v1 supports exactly one selected ordinary
raster layer, exported at its full dimensions and mapped to canvas coordinates
through its captured layer offset. Negative offsets and off-canvas layer regions
must work. Sample merged uses the visible composite at exact canvas dimensions.

Layer groups, multiple selected layers, text or other non-raster layers, and any
unproved mask/effect representation are rejected with a clear explanation. A
source-support record must state whether every enabled source type includes layer
masks, opacity, effects, alpha, color conversion, and bit-depth conversion.

Preview and inference derive from one immutable source snapshot. The preview may
scale that snapshot but must not have different compositing, crop, alpha, or
color behavior. The implementation records its exported format and transparent-
pixel treatment.

v1 permits source edits while the editor is open. At Generate and Apply, the
plugin validates that the image exists and the source revision is unchanged. A
detected source change clears points, upload references, and results. A change to
the document selection alone does not invalidate a result.

## Result and document behavior

Apply supports Replace, Add, Subtract, and Intersect. It maps source coverage to
the canvas, clips off-canvas active-layer regions, and creates one undoable
selection change. It preserves source pixels and layer masks.

Generation, preview, cancellation, reset, and close do not change the document
selection. Apply is enabled only for a current, validated result, and rechecks
the source just before editing. It combines with the selection current at Apply
time, keeping the editor window open for iterative workflows until the user
explicitly closes the window. A stale or failed Apply changes nothing.

## Reliability, limits, and privacy

The configured endpoint must implement the contract in `COMFYUI.md`. The plugin
uses finite per-operation and total-job deadlines and gives actionable errors for
unavailable servers, incompatible nodes/models, queue and inference errors,
malformed images, oversized data, and dimension mismatches. A failed request
preserves points and creates no applicable result.

v1 requires one positive point. It always sends both coordinate arrays, using an
empty negative array when needed. The plugin bounds request queues and memory;
it documents or exposes timeouts, maximum download size, decoded-mask limits,
and source-size or memory-admission limits.

The user must be told that source images are sent to the selected server and may
remain in its input storage. Ordinary diagnostics must not contain image bytes or
source-image contents.
