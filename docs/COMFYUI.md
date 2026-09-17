# ComfyUI contract

## Status

This is the v1 client contract. The earlier standalone same-size-mask result is
not a compatibility guarantee. The implementation must complete `A-11` through
`A-14` in `ACCEPTANCE.md` for each supported endpoint before enabling generation.

## Workflow

The plugin owns this minimal template and does not load a personal workflow file
at runtime. Node IDs are template-owned.

```json
{
  "1": {"class_type": "LoadImage", "inputs": {"image": "<upload>"}},
  "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sam3.1_multiplex_fp16.safetensors"}},
  "5": {"class_type": "SAM3_Detect", "inputs": {"model": ["4", 0], "image": ["1", 0], "positive_coords": "[{\"x\":420,\"y\":310}]", "negative_coords": "[{\"x\":600,\"y\":320}]", "threshold": 0.5, "refine_iterations": 2, "individual_masks": false}},
  "6": {"class_type": "MaskPreview", "inputs": {"mask": ["5", 0]}}
}
```

`positive_coords` and `negative_coords` are stringified JSON arrays of pixel
coordinates. The client serializes both inner arrays and the outer prompt object;
it never concatenates unescaped JSON. It sends both fields, with `"[]"` for an
empty negative set. v1 rejects negative-only generation.

Before upload, inspect the endpoint metadata for `LoadImage`,
`CheckpointLoaderSimple`, `SAM3_Detect`, `MaskPreview`, their required inputs and
outputs, and the selected checkpoint. Reject incompatibility before image upload.

## Transport

| Operation | Route | Contract |
| --- | --- | --- |
| Inspect | `GET /system_stats`, `GET /object_info/{class}` | Establish endpoint compatibility. |
| Upload | `POST /upload/image` | Multipart PNG with unique opaque filename. Preserve returned name, subfolder, and type. |
| Queue | `POST /prompt` | Send `prompt` and a unique client ID; retain returned prompt ID. |
| Monitor | `GET /history/{prompt_id}` | Bounded polling for the submitted prompt only. |
| Retrieve | `GET /view` | URL-encode node 6 filename, subfolder, and type. |

The older `/api/` aliases are evidence only. Select and verify one route
convention per endpoint, then use it consistently. Upload references are valid
only for their endpoint, source revision, and editor session. WebSocket progress
may be added later, but correctness depends on prompt ID and final node 6 output.

## Output and error handling

`MaskPreview` may return a temporary reference. Retrieve it promptly. Accept only
one expected node 6 output with nonzero bounded bytes, PNG signature, successful
decode, and dimensions exactly equal to the source. Reject malformed PNGs,
expired references, unexpected batches, multiple outputs, oversized downloads,
and masks beyond decoded-image limits.

Accept grayscale output. Convert RGB or RGBA only when color channels are equal;
ignore alpha unless a verified node contract says otherwise. Reject nonuniform
color output. A fixture must prove white-foreground polarity before Apply is
enabled.

Every operation has a finite configured timeout and the request has a separate
total deadline. An unavailable server, queue or inference error, malformed
response, retrieval failure, or validation failure preserves points and produces
no applicable result. A transport failure after `/prompt` may have succeeded
enters `uncertain` in `ARCHITECTURE.md`; it never retries automatically.

Diagnostics may record endpoint origin, safe error class or status, prompt ID
when known, dimensions, timing, and software versions. They must not record
image bytes, source contents, or private upload URLs.
