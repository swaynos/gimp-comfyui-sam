"""Headless GIMP adapter smoke test, executed through python-fu-eval."""

from __future__ import annotations

from pathlib import Path
import sys

import gi

gi.require_version("Gegl", "0.4")
gi.require_version("Gimp", "3.0")

from gi.repository import Gegl, Gimp


PLUGIN = Path(Gimp.directory()) / "plug-ins" / "gimp-comfyui-sam"
sys.path.insert(0, str(PLUGIN))

from sam_gimp import apply_selection, capture_source, decode_mask  # noqa: E402
from sam_png import encode_png  # noqa: E402


def selection_bytes(image: Gimp.Image) -> bytes:
    buffer = image.get_selection().get_buffer()
    return bytes(
        buffer.get(buffer.get_extent(), 1.0, "Y u8", Gegl.AbyssPolicy.NONE)
    )


def assert_selected(image: Gimp.Image, expected: set[tuple[int, int]]) -> None:
    pixels = selection_bytes(image)
    width = int(image.get_width())
    actual = {
        (x, y)
        for y in range(int(image.get_height()))
        for x in range(width)
        if pixels[y * width + x] == 255
    }
    if actual != expected:
        raise AssertionError(f"selection mismatch: expected={expected}, actual={actual}")


def main() -> None:
    Gegl.init(None)
    image = Gimp.Image.new(4, 4, Gimp.ImageBaseType.RGB)
    layer = Gimp.Layer.new(
        image,
        "fixture",
        3,
        3,
        Gimp.ImageType.RGB_IMAGE,
        100.0,
        Gimp.LayerMode.NORMAL,
    )
    if image.insert_layer(layer, None, 0) is False:
        raise AssertionError("could not insert fixture layer")
    if layer.set_offsets(-1, 1) is False:
        raise AssertionError("could not set fixture offset")
    image.set_selected_layers([layer])

    source_pixels = bytes(
        [
            255,
            0,
            0,
            0,
            255,
            0,
            0,
            0,
            255,
        ]
        * 3
    )
    buffer = layer.get_buffer()
    buffer.set(buffer.get_extent(), "R'G'B' u8", source_pixels)
    buffer.flush()

    active = capture_source(image, "active")
    if (active.width, active.height, active.offset_x, active.offset_y) != (3, 3, -1, 1):
        raise AssertionError("active-layer geometry was not preserved")
    if active.pixels != source_pixels:
        raise AssertionError("active-layer pixels changed during capture")

    merged = capture_source(image, "merged")
    if (merged.width, merged.height, merged.offset_x, merged.offset_y) != (4, 4, 0, 0):
        raise AssertionError("sample-merged geometry is not canvas-sized")

    first = bytearray(9)
    first[0] = 255  # Clipped at canvas x=-1.
    first[4] = 255  # Source (1, 1) -> canvas (0, 2).
    apply_selection(image, active, bytes(first), Gimp.ChannelOps.REPLACE)
    assert_selected(image, {(0, 2)})

    second = bytearray(9)
    second[5] = 255  # Source (2, 1) -> canvas (1, 2).
    apply_selection(image, active, bytes(second), Gimp.ChannelOps.ADD)
    assert_selected(image, {(0, 2), (1, 2)})
    apply_selection(image, active, bytes(first), Gimp.ChannelOps.SUBTRACT)
    assert_selected(image, {(1, 2)})
    apply_selection(image, active, bytes(second), Gimp.ChannelOps.INTERSECT)
    assert_selected(image, {(1, 2)})

    if bytes(buffer.get(buffer.get_extent(), 1.0, "R'G'B' u8", Gegl.AbyssPolicy.NONE)) != source_pixels:
        raise AssertionError("selection application modified source pixels")

    changed_pixels = bytearray(source_pixels)
    changed_pixels[0] = 17
    buffer.set(buffer.get_extent(), "R'G'B' u8", bytes(changed_pixels))
    buffer.flush()
    changed = capture_source(image, "active")
    if changed.revision == active.revision:
        raise AssertionError("pixel edit did not change the source revision")
    layer.set_offsets(0, 1)
    moved = capture_source(image, "active")
    if moved.revision == changed.revision:
        raise AssertionError("offset edit did not change the source revision")

    mask_rgb = bytes([0, 0, 0] * 15 + [255, 255, 255])
    decoded = decode_mask(encode_png(4, 4, mask_rgb, 3), 4, 4)
    if decoded != bytes([0] * 15 + [255]):
        raise AssertionError("mask decode changed grayscale coverage")

    image.delete()
    print("PASS active-offset merged selection-modes clipping revision mask-decode pixels")


main()
