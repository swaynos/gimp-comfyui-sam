#!/usr/bin/env python3
"""GIMP 3 entry point for point-guided ComfyUI SAM selection."""

from __future__ import annotations

import sys
import traceback

import gi

gi.require_version("Gegl", "0.4")
gi.require_version("Gimp", "3.0")

from gi.repository import Gegl, Gimp, GLib

from sam_core import SamError
from sam_editor import SamEditor
from sam_gimp import capture_source


PROCEDURE_NAME = "python-fu-comfyui-sam-selection"


def run(
    procedure: Gimp.ImageProcedure,
    run_mode: Gimp.RunMode,
    image: Gimp.Image,
    drawables: list[Gimp.Drawable],
    config: object,
    data: object,
) -> object:
    if run_mode != Gimp.RunMode.INTERACTIVE:
        return procedure.new_return_values(
            Gimp.PDBStatusType.CALLING_ERROR,
            GLib.Error("ComfyUI SAM Selection is interactive only."),
        )
    try:
        Gegl.init(None)
        try:
            snapshot = capture_source(image, "active")
        except SamError as active_error:
            Gimp.message(
                "Active Layer is unavailable; opening Sample Merged instead: "
                f"{active_error}"
            )
            snapshot = capture_source(image, "merged")
        SamEditor(image, snapshot).run()
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
    except Exception as error:
        Gimp.message(f"ComfyUI SAM Selection failed: {error}\n\n{traceback.format_exc()}")
        return procedure.new_return_values(
            Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(error))
        )


class ComfyUiSamPlugin(Gimp.PlugIn):
    def do_set_i18n(self, name: str) -> tuple[bool, str, None]:
        return True, "gimp30-python", None

    def do_query_procedures(self) -> list[str]:
        return [PROCEDURE_NAME]

    def do_create_procedure(self, name: str) -> Gimp.Procedure:
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, run, None
        )
        procedure.set_image_types("*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        procedure.set_menu_label("ComfyUI _SAM Selection...")
        procedure.add_menu_path("<Image>/Select")
        procedure.set_documentation(
            "Create a point-guided selection with ComfyUI SAM",
            "Place positive and negative points in a cached preview, run SAM3 in "
            "ComfyUI, and apply the returned mask as an undoable GIMP selection.",
            name,
        )
        procedure.set_attribution("Joe Swaynos", "Joe Swaynos", "2026")
        return procedure


Gimp.main(ComfyUiSamPlugin.__gtype__, sys.argv)


