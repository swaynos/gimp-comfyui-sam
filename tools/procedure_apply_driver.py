"""Batch interpreter driver for isolated procedure_apply_probe.py."""

import os
import gi

gi.require_version("Gegl", "0.4")
gi.require_version("Gimp", "3.0")
from gi.repository import Gegl, Gio, Gimp


def drive(path):
    Gegl.init(None)
    image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(path))
    assert image is not None
    try:
        proc = Gimp.get_pdb().lookup_procedure("python-fu-comfyui-sam-selection")
        assert proc is not None
        print("DRIVER_PROCEDURE", proc.get_menu_label(), flush=True)
        config = proc.create_config()
        config.set_property("run-mode", Gimp.RunMode.INTERACTIVE)
        config.set_property("image", image)
        config.set_core_object_array("drawables", image.get_selected_drawables())
        result = proc.run(config)
        print("DRIVER_RESULT", result.index(0), flush=True)
        buffer = image.get_selection().get_buffer()
        data = bytes(buffer.get(buffer.get_extent(), 1.0, "Y u8", Gegl.AbyssPolicy.NONE))
        count = len(data) - data.count(0)
        expected = (2 * image.get_width() // 3 - image.get_width() // 3) * (
            2 * image.get_height() // 3 - image.get_height() // 3
        )
        if os.environ.get("GIMP_SAM_PROBE_REAL") == "1":
            assert count > 0
        else:
            assert count == expected, (count, expected)
        print("DRIVER_AFTER_RETURN", count, flush=True)
    finally:
        image.delete()
