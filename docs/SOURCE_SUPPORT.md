# V1 source support record

This record describes the pixels sent by the current implementation. It is not
evidence for source cases that the plug-in rejects.

| Property | Active Layer | Sample Merged |
| --- | --- | --- |
| Extent | Full layer extent, including off-canvas regions | Exact image canvas |
| Canvas mapping | Captured layer offset | Origin `(0, 0)` |
| Alpha | Discarded consistently in upload and preview | Discarded consistently in upload and preview |
| Color conversion | GEGL `R'G'B' u8` | GEGL `R'G'B' u8` |
| Bit depth | Converted to 8-bit per channel | Converted to 8-bit per channel |
| Layer mask | Rejected | Included by visible compositing |
| Layer opacity below 100% | Rejected | Included by visible compositing |
| Layer effects | Rejected | Included by visible compositing |
| Group, text, or vector source | Rejected | Included by visible compositing |

Transparent RGB values are retained rather than flattened, while alpha is
discarded. Preview and upload use the same immutable RGB snapshot. This matches
the ComfyUI `LoadImage` RGB image output connected to SAM3.

The plug-in fingerprints converted pixels, dimensions, identities, scope, and
offset synchronously at Generate and Apply. It does not claim continuous source
change notification between those validation points.
