"""Read-only-on-disk XCF selection probe for GIMP's batch interpreter.

Run with ``exec(open(...).read()); probe('/path/to/project.xcf')``. The loaded
image is changed only in memory and explicitly discarded without saving.
"""

from pathlib import Path
import sys

import gi

gi.require_version("Gegl", "0.4")
gi.require_version("Gimp", "3.0")
from gi.repository import Gegl, Gimp, Gio

sys.path.insert(0, str(Path(Gimp.directory()) / "plug-ins" / "gimp-comfyui-sam"))
from sam_gimp import apply_selection, capture_source  # noqa: E402


def _selected(image):
    return [(item.get_id(), item.get_name()) for item in image.get_selected_drawables()]


def _coverage(image):
    buffer = image.get_selection().get_buffer()
    data = bytes(buffer.get(buffer.get_extent(), 1.0, "Y u8", Gegl.AbyssPolicy.NONE))
    return len(data) - data.count(0)


def probe(path):
    Gegl.init(None)
    image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(path))
    assert image is not None, "GIMP could not load the XCF"
    try:
        print("PROJECT", image.get_width(), image.get_height())
        print("LAYERS", [(layer.get_id(), layer.get_name(), layer.get_width(), layer.get_height()) for layer in image.get_layers()])
        print("SELECTED_BEFORE", _selected(image), "COVERAGE", _coverage(image), "BOUNDS", Gimp.Selection.bounds(image))
        try:
            snapshot = capture_source(image, "active")
        except Exception as error:
            print("ACTIVE_SOURCE_UNAVAILABLE", str(error))
            snapshot = capture_source(image, "merged")
        print("SOURCE", snapshot.scope, snapshot.width, snapshot.height, snapshot.offset_x, snapshot.offset_y, snapshot.revision)
        x0, x1 = snapshot.width // 3, 2 * snapshot.width // 3
        y0, y1 = snapshot.height // 3, 2 * snapshot.height // 3
        mask = bytearray(snapshot.width * snapshot.height)
        for y in range(y0, y1):
            mask[y * snapshot.width + x0 : y * snapshot.width + x1] = b"\xff" * (x1 - x0)
        count = apply_selection(image, snapshot, bytes(mask), Gimp.ChannelOps.REPLACE)
        print("APPLY_RETURN", count)
        print("SELECTED_AFTER", _selected(image), "COVERAGE", _coverage(image), "BOUNDS", Gimp.Selection.bounds(image))
        assert _coverage(image) == count, "Selection vanished after Apply returned"
        try:
            after = capture_source(image, snapshot.scope)
            print("SOURCE_AFTER", after.revision, "SAME", after.revision == snapshot.revision)
        except Exception as error:
            print("SOURCE_AFTER_ERROR", str(error))
    finally:
        image.delete()
