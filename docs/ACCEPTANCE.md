# V1 acceptance specification

## Evidence record

For each check, record plugin revision, GIMP/runtime version, endpoint and
ComfyUI version, node/model versions, fixture identity, date, exact command or
manual steps, observed result, and pass/fail. Static checks cannot prove live
GIMP or backend behavior. Use synthetic or approved fixtures only.

## Runtime and source

| ID | Procedure | Pass condition |
| --- | --- | --- |
| A-01 | Install into the GIMP-reported plugin directory, restart GIMP, invoke menu action. | One usable editor opens without host errors. |
| A-02 | Use an active raster layer with negative/nonzero offset and extent outside canvas. | Applied selection aligns after offset and clipping. |
| A-03 | Use a multi-layer visible composite in Sample merged mode. | Source and selection have exact canvas dimensions and alignment. |
| A-04 | Change pixels, size, offset, selected layer, scope, and close image while editor is open. | Points, uploads, and result invalidate; no late UI or document edit occurs. |
| A-05 | Change document selection after generation; Apply every selection mode. | Apply uses Apply-time selection, keeps editor open for successive iterations; Cancel changes nothing. |
| A-06 | Apply each mode then undo once. | Undo restores prior selection; pixels and masks stay unchanged. |

## Editor and lifecycle

| ID | Procedure | Pass condition |
| --- | --- | --- |
| A-07 | Add (Left-click positive, Shift/Right-click negative), move (drag), delete (Del key / Right-click), reset, zoom (wheel, Fit, 1:1), pan, peek toggle (Tab), and opacity slider. | Point coordinates round-trip at all tested transforms; type is not color-only; peek and opacity work without modifying underlying mask data. |
| A-08 | Generate, then change points, source, endpoint, and exposed inference settings. | Each change disables Apply until a matching result finishes. |
| A-09 | Generate repeatedly during upload/inference; Cancel then Generate; force timeout and uncertain submission. | One active slot plus at most newest queued snapshot; no uncertain retry; late results never apply. |
| A-10 | Simulate unavailable server, invalid nodes, queue error, malformed history/PNG, bad dimensions, expired result. | Points remain, error explains next action, document stays unchanged, Apply is disabled. |

## Backend

| ID | Procedure | Pass condition |
| --- | --- |
| A-11 | Inspect endpoint metadata before an upload. | Missing node, input, output, or checkpoint rejects endpoint before upload. |
| A-12 | Use fixture with intended and unwanted regions. | Both arrays are sent; positive selects intended region; negative excludes unwanted region; polarity is recorded. |
| A-13 | Test valid grayscale/RGB plus malformed, oversized, wrong-size, nonuniform RGB, and multi-output responses. | Only one valid same-size result reaches preview. |
| A-14 | Generate then refine points without source change. | Source uploads once; refinement updates prompt coordinates without upload. |

## Performance

G-06 must set numeric budgets before this check can pass. Measure 2048 x 2048,
4096 x 4096, 8192 x 8192, and a non-square fixture, plus a representative larger
fixture if memory permits. Record startup-to-preview, point movement, zoom/pan,
snapshot, scaling, encoding, upload, queue wait, cold/warm inference, download,
decode, apply, client peak memory, repeat-session growth, and server VRAM when
available. Record formats, preview dimensions, network, GPU load, median, and
worst result across repeated runs.

| ID | Procedure | Pass condition |
| --- | --- | --- |
| A-15 | Run the approved G-06 fixture baseline. | Interaction and memory meet its budgets; point movement neither re-exports nor re-uploads source. |
