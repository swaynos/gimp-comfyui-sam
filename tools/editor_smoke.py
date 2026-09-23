"""GTK editor construction smoke test, executed through python-fu-eval."""

from __future__ import annotations

from pathlib import Path
import sys

import gi

gi.require_version("Gegl", "0.4")
gi.require_version("Gimp", "3.0")

from gi.repository import Gegl, Gimp, GLib
import threading


PLUGIN = Path(Gimp.directory()) / "plug-ins" / "gimp-comfyui-sam"
sys.path.insert(0, str(PLUGIN))

from sam_comfy import GenerationResponse, UploadReference  # noqa: E402
from sam_core import Point  # noqa: E402
from sam_editor import PendingGeneration, SamEditor, WorkerResult  # noqa: E402
from sam_gimp import capture_source  # noqa: E402


def main() -> None:
    Gegl.init(None)
    image = Gimp.Image.new(8, 8, Gimp.ImageBaseType.RGB)
    layer = Gimp.Layer.new(
        image,
        "editor fixture",
        8,
        8,
        Gimp.ImageType.RGB_IMAGE,
        100.0,
        Gimp.LayerMode.NORMAL,
    )
    image.insert_layer(layer, None, 0)
    image.set_selected_layers([layer])
    pixels = bytes([40, 80, 120] * 64)
    buffer = layer.get_buffer()
    buffer.set(buffer.get_extent(), "R'G'B' u8", pixels)
    buffer.flush()

    editor = SamEditor(image, capture_source(image, "active"))
    def exercise_apply() -> bool:
        editor.points.append(Point(3.0, 3.0, True))
        editor._points_changed()
        identity = editor._current_identity()
        pending = PendingGeneration(
            identity=identity,
            png=b"",
            pixels=editor.snapshot.pixels,
            width=8,
            height=8,
            positive=[{"x": 3, "y": 3}],
            negative=[],
            endpoint=identity.endpoint,
            threshold=identity.threshold,
            refinement=identity.refinement,
            upload=None,
        )
        assert editor.slot.submit(pending)
        mask = bytes(255 if x == 3 and y == 3 else 0 for y in range(8) for x in range(8))
        response = GenerationResponse("fixture-prompt", UploadReference("fixture.png", "", "input"), b"")
        editor._worker_finished(pending, threading.Event(), WorkerResult(response, mask, b""))
        assert editor.state_label.get_text() == "Current", editor.hint_label.get_text()
        assert editor.apply_button.get_sensitive(), "Apply is disabled despite Current result"
        editor.apply_button.clicked()
        assert editor.state_label.get_text() == "Current", editor.hint_label.get_text()
        assert "1 pixels" in editor.hint_label.get_text(), editor.hint_label.get_text()
        assert editor.apply_feedback.get_visible()
        assert "Show Selection" in editor.apply_feedback.get_text()
        selection = image.get_selection().get_buffer()
        actual = bytes(selection.get(selection.get_extent(), 1.0, "Y u8", Gegl.AbyssPolicy.NONE))
        assert actual[3 * 8 + 3] == 255 and sum(actual) == 255, actual
        editor.threshold.set_value(
            0.25 if abs(editor.threshold.get_value() - 0.25) > 0.001 else 0.75
        )
        assert editor.state_label.get_text() == "Stale"
        assert not editor.apply_button.get_sensitive()
        assert not editor.apply_feedback.get_visible()
        editor._apply(editor.apply_button)
        assert editor.state_label.get_text() == "Failed"
        assert "changed" in editor.hint_label.get_text()
        after_failed_apply = bytes(selection.get(selection.get_extent(), 1.0, "Y u8", Gegl.AbyssPolicy.NONE))
        assert after_failed_apply == actual
        editor._close()
        return GLib.SOURCE_REMOVE

    failures = []

    def checked_apply() -> bool:
        try:
            return exercise_apply()
        except Exception as error:
            failures.append(error)
            editor._close()
            return GLib.SOURCE_REMOVE

    GLib.idle_add(checked_apply)
    editor.run()
    image.delete()
    if failures:
        raise failures[0]
    print("PASS editor-window Current Apply callback selection event-loop close")


main()
