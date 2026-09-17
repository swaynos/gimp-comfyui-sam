# Development and verification

## Current status

The repository contains specifications only. No plugin code, executable test
suite, installation layout, or backend proof has been imported. An earlier
standalone same-size-mask experiment is background evidence only; it did not
prove GIMP integration, output quality, negative points, or large-image speed.

Do not invent installation commands. Locate the actual plugin directory through
GIMP preferences and verify available bindings and UI libraries inside the
installed Flatpak runtime.

## Milestones

| Stage | Deliverable | Exit evidence |
| --- | --- | --- |
| 1. Runtime feasibility | Minimal procedure, plugin window, source and selection adapters | A-01 through A-06; G-01 through G-04 resolved for enabled scopes |
| 2. Backend compatibility | Minimal owned workflow and client | A-11 through A-14; G-05 compatibility record |
| 3. Point editor | Cached preview, coordinate transforms, point controls | A-07 and measured baseline sufficient to set G-06 budgets |
| 4. Integrated workflow | State machine, mask preview, Apply and invalidation | A-08 through A-10 and A-15 |
| 5. Release packaging | Installation/removal docs, diagnostics, verification record | Fresh install, full acceptance record, compatible-version and limitation list |

Do not start a stage whose listed proof gate blocks it. A later discovery that
invalidates a previous gate reopens the affected acceptance checks.

## Test design

Keep coordinate transforms, prompt construction, request identity, state
transitions, output validation, and selection-combination decisions isolated
from GIMP and covered by deterministic tests. Cover zoom, pan, preview size,
device scale, negative offsets, out-of-bounds clicks, source changes, late
responses, cancellation, uncertain submission, deadlines, and malformed output.

Use live GIMP and ComfyUI checks only for adapter, UI, runtime, and backend
behavior. A valid same-size PNG is not enough: check intended selection quality,
negative-point exclusion, polarity, alignment, and document safety separately.

## Performance method

Use the fixtures and measurements specified by `A-15`. Establish numeric
interaction, source-size, decoded-mask, and memory limits after the initial
baseline, then add them to `DECISIONS.md` and use them as stage-3 and stage-4
exit criteria. Separate client responsiveness from snapshot, upload, queue wait,
inference, download, decode, and Apply time. Confirm that refinements do not
upload an unchanged source.

## Delivery record

Before calling a release ready, provide the completed acceptance evidence, tested
installation and removal paths, supported GIMP/ComfyUI/node/model versions,
configured limits, known unsupported source cases, endpoint retention behavior,
and performance report. Keep requirements and decisions current when evidence
changes a design choice. Leave changes uncommitted unless the user requests a
commit.
