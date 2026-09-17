# V1 decisions and proof gates

## Fixed decisions

| ID | Decision | Reason |
| --- | --- | --- |
| D-01 | Use a plugin-owned window. | Native docking lacks evidence. |
| D-02 | Default to active layer; Sample merged is a separate scope. | Their extraction and coordinate rules differ. |
| D-03 | Permit source edits, but invalidate points, uploads, and results on a detected change. | Old coordinates may no longer mean the same thing. |
| D-04 | Do not invalidate on selection edits; combine at Apply time. | Preserve other selection work. |
| D-05 | Require a positive point and always send both arrays. | Negative-only behavior is unproved. |
| D-06 | Cancel locally; never call global server interruption or queue-clear APIs. | The backend may be shared. |
| D-07 | Keep one request slot per editor until cancelled work settles or times out. | Bound client and server work. |
| D-08 | Use only supported GIMP/PDB and introspection APIs. | The project has no custom GIMP build. |

## Proof gates

| ID | Question | Required evidence | Blocks |
| --- | --- | --- | --- |
| G-01 | Can target GIMP load the plugin and its window? | Fresh-install target-runtime check | All milestones |
| G-02 | Can source pixel and geometry changes be detected? | Live test of pixels, dimensions, offsets, layer, and image close | Open-source editing |
| G-03 | What pixels do supported source types export? | Fixtures for alpha, opacity, masks, effects, and color conversion | Each source type |
| G-04 | Can selection application preserve source data and undo once? | Live selection-mode and undo tests | Apply |
| G-05 | Does the endpoint support correct positive/negative output and polarity? | Compatibility fixture record | Generation |
| G-06 | What size, memory, and interaction limits are viable? | Repeated baseline measurements | Performance acceptance |

## Deferred work

- Native docking, toolbox tool registration, and main-canvas interception.
- Layer-mask output, multiple selected layers, and source types without G-03 proof.
- WebSocket progress, server-side upload cleanup, and embedding reuse.
- Viewport tiling or multiresolution caches unless measurements require them.
