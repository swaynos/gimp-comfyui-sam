"""GIMP-specific source, mask, and selection adapters."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import struct
from typing import Optional

import gi

gi.require_version("Babl", "0.1")
gi.require_version("Gegl", "0.4")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gimp", "3.0")

from gi.repository import Gegl, GdkPixbuf, Gimp, GLib

from sam_core import MAX_SOURCE_PIXELS, InvalidMaskError, SamError, mask_from_pixels, source_revision
from sam_png import encode_png


PIXEL_FORMAT = "R'G'B' u8"
SETTINGS_NAME = "gimp-comfyui-sam.json"


@dataclass(frozen=True)
class SourceSnapshot:
    scope: str
    image_id: int
    layer_id: Optional[int]
    name: str
    width: int
    height: int
    offset_x: int
    offset_y: int
    pixels: bytes
    png: bytes
    revision: str


def _ensure_size(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise SamError("The selected source is empty.")
    if width * height > MAX_SOURCE_PIXELS:
        raise SamError(
            f"The source contains {width * height:,} pixels; the safety limit is "
            f"{MAX_SOURCE_PIXELS:,}."
        )


def _offsets(drawable: Gimp.Drawable) -> tuple[int, int]:
    values = drawable.get_offsets()
    if not isinstance(values, tuple):
        raise SamError("GIMP did not return drawable offsets.")
    if len(values) == 2:
        return int(values[0]), int(values[1])
    if len(values) == 3:
        return int(values[-2]), int(values[-1])
    raise SamError("GIMP returned an unexpected drawable-offset value.")


def _read_pixels(drawable: Gimp.Drawable, width: int, height: int) -> bytes:
    buffer = drawable.get_buffer()
    rectangle = buffer.get_extent()
    pixels = bytes(buffer.get(rectangle, 1.0, PIXEL_FORMAT, Gegl.AbyssPolicy.NONE))
    expected = width * height * 3
    if len(pixels) != expected:
        raise SamError(
            f"GIMP returned {len(pixels)} source bytes; expected {expected}."
        )
    return pixels


def _active_layer(image: Gimp.Image) -> Gimp.Layer:
    drawables = list(image.get_selected_drawables())
    if len(drawables) != 1:
        raise SamError("Active Layer requires exactly one selected raster layer.")
    layer = drawables[0]
    if not isinstance(layer, Gimp.Layer):
        raise SamError("The selected item is not a raster layer.")
    if layer.is_group_layer() or layer.is_text_layer() or layer.is_vector_layer():
        raise SamError("Groups, text layers, and vector layers are not supported as Active Layer sources.")
    if layer.get_mask() is not None:
        raise SamError("Active Layer does not yet support layer masks; use Sample Merged.")
    if list(layer.get_filters()):
        raise SamError("Active Layer does not yet support layer effects; use Sample Merged.")
    if abs(float(layer.get_opacity()) - 100.0) > 0.001:
        raise SamError("Active Layer requires 100% opacity; use Sample Merged for composited opacity.")
    return layer


def capture_source(
    image: Gimp.Image, scope: str, include_png: bool = False
) -> SourceSnapshot:
    if image is None or not image.is_valid():
        raise SamError("The GIMP image is no longer available.")
    image_id = int(image.get_id())

    temporary: Optional[Gimp.Layer] = None
    if scope == "active":
        drawable = _active_layer(image)
        layer_id: Optional[int] = int(drawable.get_id())
        width = int(drawable.get_width())
        height = int(drawable.get_height())
        offset_x, offset_y = _offsets(drawable)
        name = drawable.get_name() or "Active Layer"
    elif scope == "merged":
        width = int(image.get_width())
        height = int(image.get_height())
        offset_x = 0
        offset_y = 0
        layer_id = None
        name = "Sample Merged"
        temporary = Gimp.Layer.new_from_visible(image, image, "SAM source snapshot")
        if temporary is None:
            raise SamError("GIMP could not render the visible image.")
        drawable = temporary
    else:
        raise SamError(f"Unknown source scope: {scope}.")

    _ensure_size(width, height)
    try:
        pixels = _read_pixels(drawable, width, height)
    finally:
        if temporary is not None and temporary.is_valid():
            temporary.delete()

    metadata: dict[str, object] = {
        "scope": scope,
        "image_id": image_id,
        "layer_id": layer_id,
        "width": width,
        "height": height,
        "offset_x": offset_x,
        "offset_y": offset_y,
        "format": PIXEL_FORMAT,
    }
    revision = source_revision(metadata, pixels)
    return SourceSnapshot(
        scope=scope,
        image_id=image_id,
        layer_id=layer_id,
        name=name,
        width=width,
        height=height,
        offset_x=offset_x,
        offset_y=offset_y,
        pixels=pixels,
        png=encode_png(width, height, pixels, 3) if include_png else b"",
        revision=revision,
    )


def decode_mask(png: bytes, expected_width: int, expected_height: int) -> bytes:
    if len(png) < 33 or not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise InvalidMaskError("Returned mask is not a complete PNG image.")
    chunk_length = struct.unpack(">I", png[8:12])[0]
    if png[12:16] != b"IHDR" or chunk_length != 13:
        raise InvalidMaskError("Returned PNG does not begin with a valid IHDR chunk.")
    width, height, bit_depth, color_type = struct.unpack(">IIBB", png[16:26])
    if width != expected_width or height != expected_height:
        raise InvalidMaskError(
            f"Mask dimensions {width}x{height} do not match source "
            f"{expected_width}x{expected_height}."
        )
    if width <= 0 or height <= 0 or width * height > MAX_SOURCE_PIXELS:
        raise InvalidMaskError("Mask dimensions exceed the configured safety limit.")
    valid_depths = {
        0: (1, 2, 4, 8, 16),
        2: (8, 16),
        4: (8, 16),
        6: (8, 16),
    }
    if color_type not in valid_depths or bit_depth not in valid_depths[color_type]:
        raise InvalidMaskError("Returned PNG uses an unsupported pixel format.")
    loader = GdkPixbuf.PixbufLoader.new_with_type("png")
    try:
        if not loader.write(png):
            raise InvalidMaskError("GdkPixbuf rejected the returned PNG.")
        loader.close()
        pixbuf = loader.get_pixbuf()
        if pixbuf is None:
            raise InvalidMaskError("GdkPixbuf did not decode the returned PNG.")
        return mask_from_pixels(
            bytes(pixbuf.get_pixels()),
            int(pixbuf.get_width()),
            int(pixbuf.get_height()),
            int(pixbuf.get_n_channels()),
            int(pixbuf.get_rowstride()),
            expected_width,
            expected_height,
        )
    except GLib.Error as error:
        raise InvalidMaskError(f"Could not decode returned mask PNG: {error.message}") from error


def apply_selection(
    image: Gimp.Image,
    snapshot: SourceSnapshot,
    mask: bytes,
    operation: Gimp.ChannelOps,
) -> int:
    if image is None or not image.is_valid() or int(image.get_id()) != snapshot.image_id:
        raise SamError("The source image is no longer available.")
    if len(mask) != snapshot.width * snapshot.height:
        raise SamError("Mask data no longer matches the source dimensions.")

    _ensure_size(int(image.get_width()), int(image.get_height()))
    selected_layers = list(image.get_selected_layers())
    selection = image.get_selection()
    selection_buffer = selection.get_buffer()
    selection_extent = selection_buffer.get_extent()
    previous_selection = bytes(
        selection_buffer.get(
            selection_extent, 1.0, "Y u8", Gegl.AbyssPolicy.NONE
        )
    )
    expected_selection_size = int(image.get_width()) * int(image.get_height())
    if len(previous_selection) != expected_selection_size:
        raise SamError("GIMP returned an unexpected selection buffer size.")

    channel: Optional[Gimp.Channel] = None
    inserted = False
    undo_started = False
    selection_changed = False
    selected_pixels = 0
    try:
        channel = Gimp.Channel.new(
            image,
            "Temporary SAM selection",
            snapshot.width,
            snapshot.height,
            100.0,
            Gegl.Color.new("black"),
        )
        if channel is None:
            raise SamError("GIMP could not create a temporary selection channel.")
        channel_buffer = channel.get_buffer()
        channel_buffer.set(channel_buffer.get_extent(), "Y u8", mask)
        channel_buffer.flush()

        started = image.undo_group_start()
        if started is False:
            raise SamError("GIMP could not start a selection undo group.")
        undo_started = True
        inserted_result = image.insert_channel(channel, None, 0)
        if inserted_result is False:
            raise SamError("GIMP could not insert the temporary selection channel.")
        inserted = True
        if not selection.combine_masks(
            channel, operation, snapshot.offset_x, snapshot.offset_y
        ):
            raise SamError("GIMP could not combine the SAM mask with the selection.")
        selection_changed = True
        result_buffer = selection.get_buffer()
        result_coverage = bytes(
            result_buffer.get(
                result_buffer.get_extent(), 1.0, "Y u8", Gegl.AbyssPolicy.NONE
            )
        )
        if len(result_coverage) != expected_selection_size:
            raise SamError("GIMP returned an unexpected selection after Apply.")
        selected_pixels = len(result_coverage) - result_coverage.count(0)
        if operation == Gimp.ChannelOps.REPLACE and selected_pixels == 0:
            # An all-zero mask is a valid empty result, but a nonempty in-canvas
            # mask must not silently become an empty GIMP selection.
            source_x0 = max(0, -snapshot.offset_x)
            source_y0 = max(0, -snapshot.offset_y)
            source_x1 = min(snapshot.width, image.get_width() - snapshot.offset_x)
            source_y1 = min(snapshot.height, image.get_height() - snapshot.offset_y)
            expected_coverage = any(
                any(mask[y * snapshot.width + source_x0 : y * snapshot.width + source_x1])
                for y in range(source_y0, source_y1)
            )
            if expected_coverage:
                raise SamError(
                    "GIMP reported success, but the applied selection is empty."
                )
        removed = image.remove_channel(channel)
        if removed is False:
            raise SamError("GIMP could not remove the temporary selection channel.")
        inserted = False
        if selected_layers and [item.get_id() for item in image.get_selected_layers()] != [
            item.get_id() for item in selected_layers
        ]:
            if image.set_selected_layers(selected_layers) is False:
                raise SamError("GIMP could not restore the selected source layer.")
        final_buffer = selection.get_buffer()
        final_coverage = bytes(
            final_buffer.get(
                final_buffer.get_extent(), 1.0, "Y u8", Gegl.AbyssPolicy.NONE
            )
        )
        if len(final_coverage) != expected_selection_size:
            raise SamError("GIMP returned an invalid finalized selection.")
        finalized_pixels = len(final_coverage) - final_coverage.count(0)
        if finalized_pixels != selected_pixels:
            raise SamError("GIMP changed the selection while removing its temporary channel.")
        ended = image.undo_group_end()
        undo_started = False
        if ended is False:
            raise SamError("GIMP could not finish the selection undo group.")
        Gimp.displays_flush()
        return selected_pixels
    except Exception as original_error:
        restoration_error: Optional[Exception] = None
        if selection_changed:
            restore: Optional[Gimp.Channel] = None
            restore_inserted = False
            try:
                restore = Gimp.Channel.new(
                    image,
                    "Restore previous selection",
                    int(image.get_width()),
                    int(image.get_height()),
                    100.0,
                    Gegl.Color.new("black"),
                )
                if restore is None:
                    raise SamError("GIMP could not create a selection restore channel.")
                restore_buffer = restore.get_buffer()
                restore_buffer.set(
                    restore_buffer.get_extent(), "Y u8", previous_selection
                )
                restore_buffer.flush()
                if image.insert_channel(restore, None, 0) is False:
                    raise SamError("GIMP could not insert the selection restore channel.")
                restore_inserted = True
                if not selection.combine_masks(
                    restore, Gimp.ChannelOps.REPLACE, 0, 0
                ):
                    raise SamError("GIMP could not restore the previous selection.")
            except Exception as error:
                restoration_error = error
            finally:
                if restore_inserted and restore is not None and restore.is_valid():
                    image.remove_channel(restore)
                if restore is not None and restore.is_valid():
                    restore.delete()
        if restoration_error is not None:
            raise SamError(
                f"Apply failed and the previous selection could not be restored: "
                f"{restoration_error}"
            ) from original_error
        raise
    finally:
        if inserted and channel is not None and channel.is_valid():
            image.remove_channel(channel)
        if undo_started:
            image.undo_group_end()
        if channel is not None and channel.is_valid():
            channel.delete()


def settings_path() -> Path:
    directory = Path(Gimp.directory()) / "plug-in-settings"
    return directory / SETTINGS_NAME


def load_settings() -> dict[str, object]:
    path = settings_path()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def save_settings(settings: dict[str, object]) -> None:
    path = settings_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
