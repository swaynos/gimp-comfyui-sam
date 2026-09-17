# Architecture

## Status and boundaries

This is the v1 implementation contract. The product behavior in
`REQUIREMENTS.md` is fixed; GIMP and ComfyUI mechanisms are provisional until
their proof gates pass. Python 3 and GIMP introspection bindings are candidates.
Host Python libraries must not be assumed available inside Flatpak GIMP.

```text
GIMP menu -> source adapter -> immutable source snapshot -> point editor
                                      |                       |
                               preview cache          request controller
                                                              |
GIMP selection adapter <- mask validation <- ComfyUI client <-+
```

GIMP-specific objects remain in source and selection adapters. Worker tasks may
encode, request, and decode immutable bytes only. Source reads, GTK updates, and
selection edits run in the supported GIMP main context.

## Source and preview contract

The source adapter returns one immutable snapshot containing pixels, dimensions,
scope, image identity, layer identity where applicable, offset, exported format,
and content-revision token. The preview and uploaded PNG derive only from it.
The active-layer snapshot preserves full layer extent. Sample merged is exactly
the canvas extent.

Cache one bounded display-sized preview per source revision. Draw points and mask
overlays independently. Cache the scaled mask separately from the full-resolution
coverage used by Apply. Do not eagerly retain several full-resolution RGBA
copies. Record ownership and release points for snapshots, encoded uploads,
downloaded bytes, and decoded masks.

## Coordinate contract

Store point positions as source-pixel floating-point values. With preview origin
`(ox, oy)` and effective scales `(sx, sy)`, map pointer coordinates as:

```text
source_x = (pointer_x - ox) / sx
source_y = (pointer_y - oy) / sy
```

The origin includes pan and centering. Reject clicks outside the displayed source
instead of clamping. Use logical widget coordinates; account for device scaling
exactly once in the toolkit layer. At request construction, convert a point once
using the documented rounding rule. Reject converted coordinates outside the
source extent.

For active layer, map source to canvas as `canvas = source + layer_offset`. For
Sample merged, source and canvas coordinates coincide. Never normalize SAM point
coordinates. Resizing or panning the preview never changes source dimensions or
inference coordinates.

## Revisions and validation

At editor creation, Generate, and Apply, validate image existence, source scope,
dimensions, offset, and a content-revision token. The feasibility milestone must
prove a supported token or notification for pixel edits, geometry changes,
selected-layer changes, and document closure. If it cannot, use a documented
synchronous source fingerprint at Generate and Apply before allowing open-source
editing.

A mismatch increments source revision, clears all points, upload references, and
results, and reports that the source changed. Selection changes are not part of
source revision. Upload references are additionally bound to endpoint identity.

## Request lifecycle

Generate captures an immutable identity containing editor session, source
revision, point revision, endpoint, workflow template version, model, threshold,
refinement count, and every other inference setting. A result is current only
when every field matches. Changing any field makes a result stale.

| State | Meaning and transitions |
| --- | --- |
| `idle` | Generate enters `preparing`. |
| `preparing` | Validate, export, or upload. Queue enters `submitted`; failure enters `failed`; Cancel enters `locally_cancelled`. |
| `submitted` | Prompt outcome is unknown. Prompt ID enters `running`; uncertain transport enters `uncertain`; Cancel enters `locally_cancelled`. |
| `running` | Poll known prompt ID. Valid mask enters `current`; error/timeout enters `failed`; Cancel enters `locally_cancelled`. |
| `uncertain` | Prompt may exist server-side. User acknowledgement enters `idle`; never retry automatically. |
| `locally_cancelled` | Ignore callbacks while server work may continue. Settlement or local deadline enters `idle`. |
| `current` | Apply may run; source, point, or setting change enters `stale`. |
| `stale` or `failed` | Generate enters `preparing`; reset enters `idle`. |
| `closed` | No transition. |

One editor has one occupied request slot across preparing, submitted, running,
uncertain, and locally cancelled states. Cancel does not free it until settlement
or deadline. While occupied, Generate records at most one newest snapshot; after
settlement it starts only if still current. Uncertain submission discards queued
generation. Callbacks check editor liveness and request identity before updates.
Never call ComfyUI global interrupt or queue-clear APIs.

## Mask and selection contract

Validate a downloaded mask before preview or Apply: bounded nonzero response,
PNG signature, successful decode, exact source dimensions, expected single
output, documented color conversion, and proven foreground polarity. Invalid
masks never become results.

The selection adapter converts grayscale coverage to GIMP selection coverage,
maps it through the captured offset, and combines it with the Apply-time
selection. It uses supported PDB APIs and a temporary mask/channel if required.
It groups each Apply as one undoable operation and cleans up temporary resources
on success and failure. Preview opacity never changes coverage.

Server upload names are unique and opaque. The standard API may not support
server cleanup; document retention. Always clean up local temporary files.
