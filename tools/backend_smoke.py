#!/usr/bin/env python3
"""Exercise the configured ComfyUI SAM endpoint with a synthetic fixture."""

from __future__ import annotations

import pathlib
import sys
import threading


ROOT = pathlib.Path(__file__).parents[1]
PLUGIN = ROOT / "plug-ins" / "gimp-comfyui-sam"
sys.path.insert(0, str(PLUGIN))

from sam_comfy import ComfyClient, get_default_endpoint  # noqa: E402
from sam_gimp import decode_mask  # noqa: E402
from sam_png import encode_png  # noqa: E402


class CountingClient(ComfyClient):
    def __init__(self, endpoint: str) -> None:
        super().__init__(endpoint)
        self.upload_count = 0

    def upload(self, png: bytes, deadline: float | None = None):
        self.upload_count += 1
        return super().upload(png, deadline)


def fixture(size: int = 512) -> bytes:
    pixels = bytearray([245, 245, 245]) * (size * size)
    for y in range(128, 384):
        for x in range(128, 384):
            offset = (y * size + x) * 3
            pixels[offset : offset + 3] = bytes([190, 35, 35])
    return encode_png(size, size, bytes(pixels), 3)


def main() -> int:
    endpoint = sys.argv[1] if len(sys.argv) > 1 else get_default_endpoint()
    client = CountingClient(endpoint)
    result = client.generate(
        png=fixture(),
        positive=[{"x": 256, "y": 256}],
        negative=[{"x": 32, "y": 32}],
        threshold=0.5,
        refinement=2,
        client_id="gimp-sam-backend-smoke",
        cancel=threading.Event(),
    )
    mask = decode_mask(result.mask_png, 512, 512)
    center = mask[256 * 512 + 256]
    corner = mask[32 * 512 + 32]
    if center <= corner:
        raise RuntimeError(
            f"Unexpected mask polarity or point behavior: center={center}, corner={corner}"
        )
    refined = client.generate(
        png=fixture(),
        positive=[{"x": 256, "y": 256}, {"x": 320, "y": 320}],
        negative=[{"x": 32, "y": 32}],
        threshold=0.5,
        refinement=2,
        client_id="gimp-sam-backend-smoke",
        cancel=threading.Event(),
        upload=result.upload,
    )
    refined_mask = decode_mask(refined.mask_png, 512, 512)
    if refined_mask[256 * 512 + 256] <= refined_mask[32 * 512 + 32]:
        raise RuntimeError("Refined prompt returned unexpected polarity.")
    if client.upload_count != 1:
        raise RuntimeError(f"Expected one source upload, got {client.upload_count}.")
    print(
        f"PASS prompts={result.prompt_id},{refined.prompt_id} dimensions=512x512 "
        f"center={center} corner={corner} uploads={client.upload_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
