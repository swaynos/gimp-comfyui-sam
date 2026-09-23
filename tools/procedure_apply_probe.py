#!/usr/bin/env python3
"""Isolated test plug-in for the real GIMP ImageProcedure lifetime.

Install ONLY in an isolated GIMP3_DIRECTORY plug-in folder beside copies of
sam_*.py. It makes an in-memory selection and never saves the loaded project.
"""

import os
import sys
import threading

import gi

gi.require_version("Gegl", "0.4")
gi.require_version("Gimp", "3.0")
from gi.repository import Gegl, Gimp, GLib

from sam_comfy import GenerationResponse, UploadReference
from sam_core import Point
from sam_editor import PendingGeneration, SamEditor, WorkerResult
from sam_gimp import capture_source


NAME = "python-fu-comfyui-sam-selection"


def count_selection(image):
    buffer = image.get_selection().get_buffer()
    data = bytes(buffer.get(buffer.get_extent(), 1.0, "Y u8", Gegl.AbyssPolicy.NONE))
    return len(data) - data.count(0)


def run(procedure, run_mode, image, drawables, config, data):
    Gegl.init(None)
    snapshot = capture_source(image, "active")
    editor = SamEditor(image, snapshot)
    failure = []
    print("PROBE_BEFORE", count_selection(image), snapshot.revision, flush=True)
    expected_count = (
        (2 * snapshot.width // 3 - snapshot.width // 3)
        * (2 * snapshot.height // 3 - snapshot.height // 3)
    )

    def finish_real():
        print("PROBE_REAL_READY", editor.state_label.get_text(), editor.apply_button.get_sensitive(), flush=True)
        assert editor.apply_button.get_sensitive(), editor.hint_label.get_text()
        editor.apply_button.clicked()
        first_count = count_selection(image)
        print("PROBE_REAL_FIRST", first_count, editor.state_label.get_text(), editor.hint_label.get_text(), flush=True)
        assert first_count > 0
        assert editor.state_label.get_text() == "Current"
        editor.apply_button.clicked()
        print("PROBE_REAL_SECOND", count_selection(image), editor.state_label.get_text(), len(editor.points), flush=True)
        assert len(editor.points) == 2
        assert capture_source(image, "active").revision == snapshot.revision
        editor._close()
        return GLib.SOURCE_REMOVE

    def poll_real():
        state = editor.state_label.get_text()
        if state == "Current" and editor.slot.active is None:
            return finish_real()
        if state in ("Failed", "Stale"):
            raise AssertionError(f"Generation failed: {state}: {editor.hint_label.get_text()}")
        return GLib.SOURCE_CONTINUE

    def guarded(callback):
        try:
            return callback()
        except Exception as error:
            failure.append(error)
            print("PROBE_ERROR", repr(error), flush=True)
            editor._close()
            return GLib.SOURCE_REMOVE

    def generate_real():
        selection_buffer = image.get_selection().get_buffer()
        data = bytes(selection_buffer.get(selection_buffer.get_extent(), 1.0, "Y u8", Gegl.AbyssPolicy.NONE))
        inside = [index for index, value in enumerate(data) if value > 128]
        outside = next(index for index, value in enumerate(data) if value == 0)
        chosen = inside[len(inside) // 2]
        editor.points.append(Point(chosen % snapshot.width, chosen // snapshot.width, True))
        editor.points.append(Point(outside % snapshot.width, outside // snapshot.width, False))
        editor._points_changed()
        editor.confirmed_endpoints.add(editor._current_identity().endpoint)
        editor._generate(editor.generate_button)
        GLib.timeout_add(250, lambda: guarded(poll_real))
        return GLib.SOURCE_REMOVE

    def exercise():
        editor.points.append(Point(snapshot.width / 2, snapshot.height / 2, True))
        editor._points_changed()
        identity = editor._current_identity()
        pending = PendingGeneration(
            identity=identity,
            png=b"",
            pixels=snapshot.pixels,
            width=snapshot.width,
            height=snapshot.height,
            positive=[{"x": snapshot.width // 2, "y": snapshot.height // 2}],
            negative=[],
            endpoint=identity.endpoint,
            threshold=identity.threshold,
            refinement=identity.refinement,
            upload=None,
        )
        assert editor.slot.submit(pending)
        mask = bytearray(snapshot.width * snapshot.height)
        x0, x1 = snapshot.width // 3, 2 * snapshot.width // 3
        y0, y1 = snapshot.height // 3, 2 * snapshot.height // 3
        for y in range(y0, y1):
            mask[y * snapshot.width + x0 : y * snapshot.width + x1] = b"\xff" * (x1 - x0)
        result = WorkerResult(
            GenerationResponse("probe", UploadReference("probe.png", "", "input"), b""),
            bytes(mask),
            b"",
        )
        editor._worker_finished(pending, threading.Event(), result)
        print("PROBE_READY", editor.state_label.get_text(), editor.apply_button.get_sensitive(), flush=True)
        editor.apply_button.clicked()
        print("PROBE_FIRST", count_selection(image), editor.state_label.get_text(), editor.hint_label.get_text(), flush=True)
        assert count_selection(image) == expected_count
        assert editor.state_label.get_text() == "Current"
        editor.apply_button.clicked()
        print("PROBE_SECOND", count_selection(image), editor.state_label.get_text(), len(editor.points), flush=True)
        assert count_selection(image) == expected_count
        assert len(editor.points) == 1
        assert capture_source(image, "active").revision == snapshot.revision
        editor._close()
        return GLib.SOURCE_REMOVE

    if os.environ.get("GIMP_SAM_PROBE_REAL") == "1":
        GLib.idle_add(lambda: guarded(generate_real))
    else:
        GLib.idle_add(lambda: guarded(exercise))
    editor.run()
    if failure:
        raise failure[0]
    if os.environ.get("GIMP_SAM_PROBE_REAL") != "1":
        assert count_selection(image) == expected_count
    print("PROBE_RETURN", count_selection(image), flush=True)
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


class ProbePlugin(Gimp.PlugIn):
    def do_set_i18n(self, name):
        return True, "gimp30-python", None

    def do_query_procedures(self):
        return [NAME]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run, None)
        procedure.set_image_types("*")
        procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
        procedure.set_menu_label("SAM Procedure Probe")
        procedure.add_menu_path("<Image>/Select")
        return procedure


Gimp.main(ProbePlugin.__gtype__, sys.argv)
