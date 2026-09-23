"""GTK editor and request orchestration for point-guided SAM selection."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
import threading
from typing import Callable, Optional
import uuid

import cairo
import gi

gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gimp", "3.0")
gi.require_version("GimpUi", "3.0")
gi.require_version("Gtk", "3.0")

from gi.repository import Gdk, GdkPixbuf, Gimp, GimpUi, GLib, Gtk

from sam_comfy import (
    CancelledError,
    ComfyClient,
    DEFAULT_ENDPOINT,
    GenerationResponse,
    SubmissionUncertainError,
    UploadReference,
    get_default_endpoint,
    normalize_endpoint,
)
from sam_core import (
    GenerationIdentity,
    Point,
    RequestSlot,
    SamError,
    ViewTransform,
    points_for_request,
)
from sam_gimp import (
    SourceSnapshot,
    apply_selection,
    capture_source,
    decode_mask,
    load_settings,
    save_settings,
)
from sam_png import encode_png


DEFAULT_ENDPOINT = get_default_endpoint()
PREVIEW_MAX_DIMENSION = 2048


@dataclass(frozen=True)
class PendingGeneration:
    identity: GenerationIdentity
    png: bytes
    pixels: bytes
    width: int
    height: int
    positive: list[dict[str, int]]
    negative: list[dict[str, int]]
    endpoint: str
    threshold: float
    refinement: int
    upload: Optional[UploadReference]


@dataclass(frozen=True)
class WorkerResult:
    response: GenerationResponse
    mask: bytes
    source_png: bytes


class PointCanvas(Gtk.DrawingArea):
    def __init__(
        self,
        snapshot: SourceSnapshot,
        points: list[Point],
        points_changed: Callable[[], None],
    ) -> None:
        super().__init__()
        self.snapshot = snapshot
        self.points = points
        self.points_changed = points_changed
        self.tool_positive = True
        self.mask_visible = True
        self.mask_opacity = 0.5
        self._source_bytes: Optional[GLib.Bytes] = None
        self._source_pixbuf: Optional[GdkPixbuf.Pixbuf] = None
        self._preview_pixbuf: Optional[GdkPixbuf.Pixbuf] = None
        self._mask_data: Optional[bytearray] = None
        self._mask_surface: Optional[cairo.ImageSurface] = None
        self._mask_preview_surface: Optional[cairo.ImageSurface] = None
        self.mask_toggle_changed: Optional[Callable[[bool], None]] = None
        self._transform: Optional[ViewTransform] = None
        self._fit_on_allocate = True
        self._drag_point: Optional[int] = None
        self._pan_button: Optional[int] = None
        self._last_pointer = (0.0, 0.0)
        self._space_down = False
        self.selected_point: Optional[int] = None

        self.set_can_focus(True)
        self.set_size_request(640, 420)
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.SCROLL_MASK
            | Gdk.EventMask.SMOOTH_SCROLL_MASK
            | Gdk.EventMask.KEY_PRESS_MASK
            | Gdk.EventMask.KEY_RELEASE_MASK
        )
        self.connect("draw", self._draw)
        self.connect("size-allocate", self._size_allocate)
        self.connect("button-press-event", self._button_press)
        self.connect("button-release-event", self._button_release)
        self.connect("motion-notify-event", self._motion)
        self.connect("scroll-event", self._scroll)
        self.connect("key-press-event", self._key_press)
        self.connect("key-release-event", self._key_release)
        self.set_source(snapshot)

    def set_source(self, snapshot: SourceSnapshot) -> None:
        self.snapshot = snapshot
        self._source_bytes = GLib.Bytes.new(snapshot.pixels)
        self._source_pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
            self._source_bytes,
            GdkPixbuf.Colorspace.RGB,
            False,
            8,
            snapshot.width,
            snapshot.height,
            snapshot.width * 3,
        )
        scale = min(1.0, PREVIEW_MAX_DIMENSION / max(snapshot.width, snapshot.height))
        preview_width = max(1, round(snapshot.width * scale))
        preview_height = max(1, round(snapshot.height * scale))
        if scale < 1.0:
            self._preview_pixbuf = self._source_pixbuf.scale_simple(
                preview_width, preview_height, GdkPixbuf.InterpType.BILINEAR
            )
        else:
            self._preview_pixbuf = self._source_pixbuf
        self.clear_mask()
        self._fit_on_allocate = True
        self.queue_draw()

    def set_mask(self, mask: bytes) -> None:
        if len(mask) != self.snapshot.width * self.snapshot.height:
            raise SamError("Returned mask no longer matches the displayed source.")
        stride = cairo.ImageSurface.format_stride_for_width(
            cairo.FORMAT_A8, self.snapshot.width
        )
        data = bytearray(stride * self.snapshot.height)
        for y in range(self.snapshot.height):
            source = y * self.snapshot.width
            destination = y * stride
            data[destination : destination + self.snapshot.width] = mask[
                source : source + self.snapshot.width
            ]
        self._mask_data = data
        self._mask_surface = cairo.ImageSurface.create_for_data(
            data,
            cairo.FORMAT_A8,
            self.snapshot.width,
            self.snapshot.height,
            stride,
        )
        preview_width = self._preview_pixbuf.get_width()
        preview_height = self._preview_pixbuf.get_height()
        if preview_width == self.snapshot.width and preview_height == self.snapshot.height:
            self._mask_preview_surface = self._mask_surface
        else:
            preview = cairo.ImageSurface(cairo.FORMAT_A8, preview_width, preview_height)
            preview_context = cairo.Context(preview)
            preview_context.scale(
                preview_width / self.snapshot.width,
                preview_height / self.snapshot.height,
            )
            preview_context.set_source_rgba(1.0, 1.0, 1.0, 1.0)
            preview_context.mask_surface(self._mask_surface, 0, 0)
            self._mask_preview_surface = preview
        self.mask_visible = True
        if self.mask_toggle_changed:
            self.mask_toggle_changed(True)
        self.queue_draw()

    def clear_mask(self) -> None:
        self._mask_surface = None
        self._mask_preview_surface = None
        self._mask_data = None
        self.queue_draw()

    def fit(self) -> None:
        allocation = self.get_allocation()
        if allocation.width <= 1 or allocation.height <= 1:
            return
        self._transform = ViewTransform.fitted(
            self.snapshot.width,
            self.snapshot.height,
            allocation.width,
            allocation.height,
        )
        self._fit_on_allocate = False
        self.queue_draw()

    def one_to_one(self) -> None:
        allocation = self.get_allocation()
        self._transform = ViewTransform(
            self.snapshot.width,
            self.snapshot.height,
            allocation.width,
            allocation.height,
            1.0,
        )
        self._fit_on_allocate = False
        self.queue_draw()

    def toggle_mask(self) -> None:
        if self._mask_surface is not None:
            self.mask_visible = not self.mask_visible
            if self.mask_toggle_changed:
                self.mask_toggle_changed(self.mask_visible)
            self.queue_draw()

    def _size_allocate(self, _widget: Gtk.Widget, allocation: Gdk.Rectangle) -> None:
        if self._fit_on_allocate or self._transform is None:
            self.fit()
        else:
            self._transform.viewport_width = allocation.width
            self._transform.viewport_height = allocation.height

    def _draw(self, _widget: Gtk.Widget, context: cairo.Context) -> bool:
        allocation = self.get_allocation()
        context.set_source_rgb(0.08, 0.09, 0.11)
        context.paint()
        if self._transform is None or self._source_pixbuf is None or self._preview_pixbuf is None:
            return False
        ox, oy = self._transform.origin
        zoom = self._transform.zoom

        context.save()
        context.rectangle(0, 0, allocation.width, allocation.height)
        context.clip()
        context.translate(ox, oy)
        context.scale(zoom, zoom)
        source = self._source_pixbuf if zoom >= 0.75 else self._preview_pixbuf
        context.save()
        context.scale(
            self.snapshot.width / source.get_width(),
            self.snapshot.height / source.get_height(),
        )
        Gdk.cairo_set_source_pixbuf(context, source, 0, 0)
        context.paint()
        context.restore()
        if self.mask_visible and self._mask_surface is not None:
            mask_surface = (
                self._mask_surface if zoom >= 0.75 else self._mask_preview_surface
            )
            context.set_source_rgba(0.0, 0.85, 0.95, self.mask_opacity)
            if mask_surface is self._mask_surface:
                context.mask_surface(mask_surface, 0, 0)
            else:
                context.save()
                context.scale(
                    self.snapshot.width / mask_surface.get_width(),
                    self.snapshot.height / mask_surface.get_height(),
                )
                context.mask_surface(mask_surface, 0, 0)
                context.restore()
        context.restore()

        for index, point in enumerate(self.points):
            x, y = self._transform.source_to_screen(point.x, point.y)
            self._draw_point(context, index, point, x, y)
        return False

    def _draw_point(
        self, context: cairo.Context, index: int, point: Point, x: float, y: float
    ) -> None:
        radius = 8.0
        context.save()
        context.set_line_width(2.0)
        if point.positive:
            context.set_source_rgb(0.1, 0.9, 0.35)
            context.arc(x, y, radius, 0, 2 * math.pi)
        else:
            context.set_source_rgb(0.95, 0.2, 0.2)
            context.rectangle(x - radius, y - radius, radius * 2, radius * 2)
        context.fill_preserve()
        context.set_source_rgb(0.05, 0.05, 0.05)
        context.stroke()
        context.set_line_width(2.0)
        context.move_to(x - 4, y)
        context.line_to(x + 4, y)
        if point.positive:
            context.move_to(x, y - 4)
            context.line_to(x, y + 4)
        context.stroke()
        context.set_source_rgb(1.0, 1.0, 1.0)
        context.move_to(x + 11, y - 8)
        context.show_text(str(index + 1))
        if self.selected_point == index:
            context.set_source_rgb(1.0, 1.0, 1.0)
            context.set_line_width(1.5)
            context.arc(x, y, radius + 4, 0, 2 * math.pi)
            context.stroke()
        context.restore()

    def _hit_test(self, x: float, y: float) -> Optional[int]:
        if self._transform is None:
            return None
        for index in range(len(self.points) - 1, -1, -1):
            px, py = self._transform.source_to_screen(self.points[index].x, self.points[index].y)
            if math.hypot(px - x, py - y) <= 12.0:
                return index
        return None

    def _button_press(self, _widget: Gtk.Widget, event: Gdk.EventButton) -> bool:
        self.grab_focus()
        self._last_pointer = (event.x, event.y)
        if event.button == 2 or (event.button == 1 and self._space_down):
            self._pan_button = event.button
            return True
        hit = self._hit_test(event.x, event.y)
        if hit is not None:
            if event.button == 3:
                del self.points[hit]
                self.selected_point = None
                self.points_changed()
                self.queue_draw()
                return True
            if event.button == 1:
                self.selected_point = hit
                self._drag_point = hit
                self.queue_draw()
                return True
        if self._transform is None:
            return False
        source = self._transform.screen_to_source(event.x, event.y)
        if source is None:
            return True
        if event.button in (1, 3):
            positive = self.tool_positive
            if event.button == 3 or event.state & Gdk.ModifierType.SHIFT_MASK:
                positive = False
            self.points.append(Point(source[0], source[1], positive))
            self.selected_point = len(self.points) - 1
            self.points_changed()
            self.queue_draw()
            return True
        return False

    def _button_release(self, _widget: Gtk.Widget, event: Gdk.EventButton) -> bool:
        if self._pan_button == event.button:
            self._pan_button = None
        if event.button == 1:
            self._drag_point = None
        return True

    def _motion(self, _widget: Gtk.Widget, event: Gdk.EventMotion) -> bool:
        if self._transform is None:
            return False
        if self._pan_button is not None:
            self._transform.pan_x += event.x - self._last_pointer[0]
            self._transform.pan_y += event.y - self._last_pointer[1]
            self._last_pointer = (event.x, event.y)
            self.queue_draw()
            return True
        if self._drag_point is not None and self._drag_point < len(self.points):
            source = self._transform.screen_to_source(event.x, event.y)
            if source is not None:
                old = self.points[self._drag_point]
                self.points[self._drag_point] = Point(source[0], source[1], old.positive)
                self.points_changed()
                self.queue_draw()
            return True
        return False

    def _scroll(self, _widget: Gtk.Widget, event: Gdk.EventScroll) -> bool:
        if self._transform is None:
            return False
        if event.direction == Gdk.ScrollDirection.UP:
            factor = 1.2
        elif event.direction == Gdk.ScrollDirection.DOWN:
            factor = 1.0 / 1.2
        else:
            _ok, _dx, dy = event.get_scroll_deltas()
            factor = math.exp(-dy * 0.2)
        new_zoom = min(16.0, max(0.01, self._transform.zoom * factor))
        self._transform.zoom_at(event.x, event.y, new_zoom)
        self._fit_on_allocate = False
        self.queue_draw()
        return True

    def _key_press(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        if event.keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            if self.selected_point is not None and self.selected_point < len(self.points):
                del self.points[self.selected_point]
                self.selected_point = None
                self.points_changed()
                self.queue_draw()
            return True
        if event.keyval == Gdk.KEY_Tab:
            self.toggle_mask()
            return True
        if event.keyval == Gdk.KEY_space:
            self._space_down = True
            return True
        return False

    def _key_release(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        if event.keyval == Gdk.KEY_space:
            self._space_down = False
            return True
        return False


class SamEditor:
    def __init__(self, image: Gimp.Image, snapshot: SourceSnapshot) -> None:
        GimpUi.init("gimp-comfyui-sam")
        self.image = image
        self.snapshot = snapshot
        self.session_id = uuid.uuid4().hex
        self.points: list[Point] = []
        self.point_revision = 0
        self.result_identity: Optional[GenerationIdentity] = None
        self.result_mask: Optional[bytes] = None
        self.slot: RequestSlot[PendingGeneration] = RequestSlot()
        self.active_cancel: Optional[threading.Event] = None
        self.upload_cache: dict[tuple[str, str], UploadReference] = {}
        self.confirmed_endpoints: set[str] = set()
        self.closed = False
        self.source_available = True
        self._changing_scope = False
        self.settings = load_settings()

        self.window = Gtk.Window(title="ComfyUI SAM Selection")
        self.window.set_default_size(1024, 760)
        self.window.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.window.set_keep_above(True)
        GimpUi.window_set_transient(self.window)
        self.window.connect("delete-event", self._close)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        root.set_border_width(8)
        self.window.add(root)

        source_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        root.pack_start(source_row, False, False, 0)
        source_row.pack_start(Gtk.Label(label="Source:"), False, False, 0)
        self.active_source = Gtk.RadioButton.new_with_label_from_widget(None, "Active Layer")
        self.merged_source = Gtk.RadioButton.new_with_label_from_widget(
            self.active_source, "Sample Merged"
        )
        source_row.pack_start(self.active_source, False, False, 0)
        source_row.pack_start(self.merged_source, False, False, 0)
        source_row.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 4)
        source_row.pack_start(Gtk.Label(label="Tool:"), False, False, 0)
        self.positive_tool = Gtk.RadioButton.new_with_label_from_widget(None, "+ Positive")
        self.negative_tool = Gtk.RadioButton.new_with_label_from_widget(
            self.positive_tool, "- Negative"
        )
        source_row.pack_start(self.positive_tool, False, False, 0)
        source_row.pack_start(self.negative_tool, False, False, 0)
        self.reset_button = Gtk.Button(label="Reset Points")
        source_row.pack_end(self.reset_button, False, False, 0)

        view_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        root.pack_start(view_row, False, False, 0)
        fit_button = Gtk.Button(label="Fit")
        one_button = Gtk.Button(label="1:1")
        self.peek_button = Gtk.ToggleButton(label="Mask (Tab)")
        self.peek_button.set_active(True)
        view_row.pack_start(Gtk.Label(label="View:"), False, False, 0)
        view_row.pack_start(fit_button, False, False, 0)
        view_row.pack_start(one_button, False, False, 0)
        view_row.pack_start(self.peek_button, False, False, 8)
        view_row.pack_start(Gtk.Label(label="Opacity:"), False, False, 0)
        opacity = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.05)
        opacity.set_value(0.5)
        opacity.set_size_request(180, -1)
        view_row.pack_start(opacity, False, False, 0)
        self.source_label = Gtk.Label()
        self.source_label.set_xalign(1.0)
        view_row.pack_end(self.source_label, True, True, 0)

        self.canvas = PointCanvas(snapshot, self.points, self._points_changed)
        self.canvas.mask_toggle_changed = self.peek_button.set_active
        frame = Gtk.Frame()
        frame.add(self.canvas)
        root.pack_start(frame, True, True, 0)

        settings_expander = Gtk.Expander(label="Inference Settings")
        settings_expander.set_expanded(True)
        settings_grid = Gtk.Grid(column_spacing=8, row_spacing=6, margin=8)
        settings_expander.add(settings_grid)
        root.pack_start(settings_expander, False, False, 0)
        settings_grid.attach(Gtk.Label(label="Server URL", xalign=0), 0, 0, 1, 1)
        self.endpoint_entry = Gtk.Entry()
        self.endpoint_entry.set_text(str(self.settings.get("endpoint", get_default_endpoint())))
        settings_grid.attach(self.endpoint_entry, 1, 0, 1, 1)
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.test_button = Gtk.Button(label="Test Connection")
        self.save_button = Gtk.Button(label="Save URL")
        btn_box.pack_start(self.test_button, False, False, 0)
        btn_box.pack_start(self.save_button, False, False, 0)
        settings_grid.attach(btn_box, 2, 0, 1, 1)
        settings_grid.attach(Gtk.Label(label="Threshold", xalign=0), 0, 1, 1, 1)
        self.threshold = Gtk.SpinButton.new_with_range(0.0, 1.0, 0.01)
        self.threshold.set_value(float(self.settings.get("threshold", 0.5)))
        settings_grid.attach(self.threshold, 1, 1, 1, 1)
        settings_grid.attach(Gtk.Label(label="Refinement passes", xalign=0), 0, 2, 1, 1)
        self.refinement = Gtk.SpinButton.new_with_range(0, 5, 1)
        self.refinement.set_value(float(self.settings.get("refinement", 2)))
        settings_grid.attach(self.refinement, 1, 2, 1, 1)

        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        root.pack_start(status_row, False, False, 0)
        self.spinner = Gtk.Spinner()
        self.state_label = Gtk.Label(label="Ready")
        self.hint_label = Gtk.Label(label="Click the image to add a positive point.")
        self.hint_label.set_xalign(0.0)
        status_row.pack_start(self.spinner, False, False, 0)
        status_row.pack_start(self.state_label, False, False, 0)
        status_row.pack_start(self.hint_label, True, True, 0)

        self.apply_feedback = Gtk.Label(xalign=0)
        self.apply_feedback.set_line_wrap(True)
        self.apply_feedback.set_no_show_all(True)
        root.pack_start(self.apply_feedback, False, False, 0)

        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        root.pack_start(action_row, False, False, 0)
        action_row.pack_start(Gtk.Label(label="Selection mode:"), False, False, 0)
        self.selection_mode = Gtk.ComboBoxText()
        for name in ("Replace", "Add", "Subtract", "Intersect"):
            self.selection_mode.append_text(name)
        self.selection_mode.set_active(0)
        action_row.pack_start(self.selection_mode, False, False, 0)
        self.close_button = Gtk.Button(label="Close")
        self.apply_button = Gtk.Button(label="Apply")
        self.generate_button = Gtk.Button(label="Generate")
        self.cancel_button = Gtk.Button(label="Cancel Request")
        action_row.pack_end(self.close_button, False, False, 0)
        action_row.pack_end(self.apply_button, False, False, 0)
        action_row.pack_end(self.generate_button, False, False, 0)
        action_row.pack_end(self.cancel_button, False, False, 0)

        self.active_source.set_active(snapshot.scope == "active")
        self.merged_source.set_active(snapshot.scope == "merged")
        self.active_source.connect("toggled", self._source_toggled, "active")
        self.merged_source.connect("toggled", self._source_toggled, "merged")
        self.positive_tool.connect("toggled", self._tool_toggled)
        self.reset_button.connect("clicked", self._reset_points)
        fit_button.connect("clicked", lambda _button: self.canvas.fit())
        one_button.connect("clicked", lambda _button: self.canvas.one_to_one())
        self.peek_button.connect("toggled", self._peek_toggled)
        opacity.connect("value-changed", self._opacity_changed)
        self.endpoint_entry.connect("changed", self._settings_changed)
        self.threshold.connect("value-changed", self._settings_changed)
        self.refinement.connect("value-changed", self._settings_changed)
        self.test_button.connect("clicked", self._test_connection)
        self.save_button.connect("clicked", self._save_endpoint_clicked)
        self.generate_button.connect("clicked", self._generate)
        self.cancel_button.connect("clicked", self._cancel)
        self.apply_button.connect("clicked", self._apply)
        self.close_button.connect("clicked", self._close)

        self._update_source_label()
        self._update_actions()

    def run(self) -> None:
        self.window.show_all()
        self.canvas.grab_focus()
        Gtk.main()

    def _current_identity(self) -> GenerationIdentity:
        return GenerationIdentity(
            session_id=self.session_id,
            source_revision=self.snapshot.revision,
            point_revision=self.point_revision,
            endpoint=normalize_endpoint(self.endpoint_entry.get_text()),
            threshold=round(self.threshold.get_value(), 2),
            refinement=self.refinement.get_value_as_int(),
        )

    def _update_source_label(self) -> None:
        self.source_label.set_text(
            f'{self.snapshot.name} ({self.snapshot.width} x {self.snapshot.height})'
        )

    def _set_status(self, state: str, hint: str, busy: bool = False) -> None:
        self.state_label.set_text(state)
        self.hint_label.set_text(hint)
        if state != "Current":
            self.apply_feedback.hide()
        if busy:
            self.spinner.start()
        else:
            self.spinner.stop()
        self._update_actions()

    def _update_actions(self) -> None:
        has_positive = any(point.positive for point in self.points)
        self.generate_button.set_sensitive(has_positive and self.slot.state != "uncertain")
        self.cancel_button.set_sensitive(self.slot.active is not None and self.slot.state != "cancelled")
        blocker = self._apply_blocker()
        self.apply_button.set_sensitive(blocker is None)
        if self.state_label.get_text() == "Current" and blocker is not None:
            self.state_label.set_text("Stale")
            self.hint_label.set_text(blocker)
            self.apply_feedback.hide()

    def _apply_blocker(self) -> Optional[str]:
        if not self.source_available:
            return "The source is unavailable; refresh it before applying."
        if self.result_mask is None or self.result_identity is None:
            return "No validated mask is available. Generate a mask first."
        try:
            if self.result_identity != self._current_identity():
                return "Points or settings changed; generate a matching mask."
        except SamError as error:
            return str(error)
        return None

    def _mark_stale(self, reason: str) -> None:
        if self.result_mask is not None:
            self._set_status("Stale", reason)
        else:
            self._update_actions()

    def _points_changed(self) -> None:
        self.point_revision += 1
        self._mark_stale("Points changed; generate a matching mask.")

    def _settings_changed(self, _widget: Gtk.Widget) -> None:
        self._mark_stale("Settings changed; generate a matching mask.")

    def _tool_toggled(self, button: Gtk.ToggleButton) -> None:
        if button.get_active():
            self.canvas.tool_positive = True
        else:
            self.canvas.tool_positive = False

    def _peek_toggled(self, button: Gtk.ToggleButton) -> None:
        self.canvas.mask_visible = button.get_active()
        self.canvas.queue_draw()

    def _opacity_changed(self, scale: Gtk.Range) -> None:
        self.canvas.mask_opacity = scale.get_value()
        self.canvas.queue_draw()

    def _reset_points(self, _button: Gtk.Button) -> None:
        self.points.clear()
        self.point_revision += 1
        self.result_identity = None
        self.result_mask = None
        self.canvas.selected_point = None
        self.canvas.clear_mask()
        self._set_status("Ready", "Click the image to add a positive point.")

    def _confirm_discard(self) -> bool:
        if not self.points and self.result_mask is None:
            return True
        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Changing source discards all points and the current result.",
        )
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK

    def _source_toggled(self, button: Gtk.ToggleButton, scope: str) -> None:
        if not button.get_active() or self._changing_scope or scope == self.snapshot.scope:
            return
        if not self._confirm_discard():
            self._changing_scope = True
            (self.active_source if self.snapshot.scope == "active" else self.merged_source).set_active(True)
            self._changing_scope = False
            return
        try:
            snapshot = capture_source(self.image, scope)
        except SamError as error:
            self._show_error("Cannot use that source", str(error))
            self._changing_scope = True
            (self.active_source if self.snapshot.scope == "active" else self.merged_source).set_active(True)
            self._changing_scope = False
            return
        self.snapshot = snapshot
        self.session_id = uuid.uuid4().hex
        self.source_available = True
        self.points.clear()
        self.point_revision += 1
        self.result_identity = None
        self.result_mask = None
        self.upload_cache.clear()
        self.slot.invalidate_queued()
        if self.active_cancel is not None:
            self.slot.cancel()
            self.active_cancel.set()
        self.canvas.set_source(snapshot)
        self._update_source_label()
        self._set_status("Ready", "Click the image to add a positive point.")

    def _validate_source(self) -> bool:
        try:
            current = capture_source(
                self.image, self.snapshot.scope, include_png=False
            )
        except SamError as error:
            self._invalidate_source(str(error))
            return False
        if current.revision == self.snapshot.revision:
            self.source_available = True
            return True
        old = self.snapshot
        if current.layer_id != old.layer_id:
            change = "The selected source layer changed."
        elif (current.width, current.height, current.offset_x, current.offset_y) != (
            old.width, old.height, old.offset_x, old.offset_y
        ):
            change = "The source dimensions or layer position changed."
        elif current.pixels != old.pixels:
            change = "The source pixels changed."
        else:
            change = "The source identity changed."
        self.snapshot = current
        self.session_id = uuid.uuid4().hex
        self.source_available = True
        self.points.clear()
        self.point_revision += 1
        self.result_identity = None
        self.result_mask = None
        self.upload_cache.clear()
        self.slot.invalidate_queued()
        if self.active_cancel is not None:
            self.slot.cancel()
            self.active_cancel.set()
        self.canvas.set_source(self.snapshot)
        self._update_source_label()
        self._set_status(
            "Ready", f"{change} Points and results were cleared; add new points."
        )
        return False

    def _invalidate_source(self, reason: str) -> None:
        self.source_available = False
        self.session_id = uuid.uuid4().hex
        self.points.clear()
        self.point_revision += 1
        self.result_identity = None
        self.result_mask = None
        self.upload_cache.clear()
        self.slot.invalidate_queued()
        if self.active_cancel is not None:
            self.slot.cancel()
            self.active_cancel.set()
        self.canvas.clear_mask()
        self._set_status("Failed", f"{reason} Points and results were cleared.")

    def _confirm_endpoint(self, endpoint: str) -> bool:
        if endpoint in self.confirmed_endpoints:
            return True
        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Send the source image to this ComfyUI server?",
        )
        dialog.format_secondary_text(
            f"{endpoint}\n\nThe full source image will be uploaded and may remain in the "
            "server's input storage."
        )
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            self.confirmed_endpoints.add(endpoint)
            return True
        return False

    def _generate(self, _button: Gtk.Button) -> None:
        if not self._validate_source():
            return
        try:
            identity = self._current_identity()
            positive, negative = points_for_request(
                self.points, self.snapshot.width, self.snapshot.height
            )
        except SamError as error:
            self._set_status("Failed", str(error))
            return
        if not self._confirm_endpoint(identity.endpoint):
            return
        try:
            self._save_settings()
        except OSError:
            pass
        key = (identity.endpoint, identity.source_revision)
        pending = PendingGeneration(
            identity=identity,
            png=self.snapshot.png,
            pixels=self.snapshot.pixels,
            width=self.snapshot.width,
            height=self.snapshot.height,
            positive=positive,
            negative=negative,
            endpoint=identity.endpoint,
            threshold=identity.threshold,
            refinement=identity.refinement,
            upload=self.upload_cache.get(key),
        )
        try:
            start_now = self.slot.submit(pending)
        except SamError as error:
            self._set_status("Failed", str(error))
            return
        if start_now:
            self._launch(pending)
        else:
            self._set_status(
                "Queued", "The newest point/settings snapshot will run after the active request.", True
            )

    def _launch(self, pending: PendingGeneration) -> None:
        pending = replace(
            pending,
            upload=self.upload_cache.get(
                (pending.endpoint, pending.identity.source_revision), pending.upload
            ),
        )
        cancel = threading.Event()
        self.active_cancel = cancel
        self._set_status("Preparing", "Checking ComfyUI and preparing the request.", True)

        def work() -> None:
            try:
                client = ComfyClient(pending.endpoint)
                source_png = pending.png
                if pending.upload is None and not source_png:
                    GLib.idle_add(
                        self._worker_progress, pending.identity, "encoding"
                    )
                    source_png = encode_png(
                        pending.width, pending.height, pending.pixels, 3
                    )
                    if cancel.is_set():
                        raise CancelledError("Request cancelled locally.")
                response = client.generate(
                    png=source_png,
                    positive=pending.positive,
                    negative=pending.negative,
                    threshold=pending.threshold,
                    refinement=pending.refinement,
                    client_id=pending.identity.session_id,
                    cancel=cancel,
                    upload=pending.upload,
                    progress=lambda stage: GLib.idle_add(
                        self._worker_progress, pending.identity, stage
                    ),
                )
                if cancel.is_set():
                    raise CancelledError("Request cancelled locally.")
                mask = decode_mask(response.mask_png, pending.width, pending.height)
                if cancel.is_set():
                    raise CancelledError("Request cancelled locally.")
                result: object = WorkerResult(response, mask, source_png)
            except Exception as error:
                result = error
            GLib.idle_add(self._worker_finished, pending, cancel, result)

        threading.Thread(target=work, name="gimp-sam-request", daemon=True).start()

    def _worker_progress(self, identity: GenerationIdentity, stage: str) -> bool:
        if self.closed or self.slot.active is None:
            return GLib.SOURCE_REMOVE
        if self.slot.active.identity != identity or self.slot.state == "cancelled":
            return GLib.SOURCE_REMOVE
        states = {
            "encoding": ("Preparing", "Encoding the immutable source snapshot."),
            "uploading": ("Preparing", "Uploading the immutable source snapshot."),
            "submitting": ("Preparing", "Submitting the SAM3 prompt."),
            "inferring": ("Inferring", "ComfyUI is running the SAM3 prompt."),
            "downloading": ("Inferring", "Downloading and validating the mask."),
        }
        state, hint = states.get(stage, ("Preparing", "Preparing the request."))
        self._set_status(state, hint, True)
        return GLib.SOURCE_REMOVE

    def _worker_finished(
        self,
        pending: PendingGeneration,
        cancel: threading.Event,
        result: object,
    ) -> bool:
        if self.closed:
            return GLib.SOURCE_REMOVE
        self.active_cancel = None
        if cancel.is_set() and isinstance(result, WorkerResult):
            result = CancelledError("Request cancelled locally.")
        uncertain = isinstance(result, SubmissionUncertainError)

        try:
            if isinstance(result, WorkerResult):
                same_source = (
                    self.source_available
                    and pending.identity.session_id == self.session_id
                    and pending.identity.source_revision == self.snapshot.revision
                    and pending.width == self.snapshot.width
                    and pending.height == self.snapshot.height
                )
                if not same_source:
                    self._set_status(
                        "Ready", "Ignored a result from an earlier source snapshot."
                    )
                else:
                    if result.source_png and not self.snapshot.png:
                        self.snapshot = replace(self.snapshot, png=result.source_png)
                    self.upload_cache[
                        (pending.endpoint, pending.identity.source_revision)
                    ] = result.response.upload
                    self.result_identity = pending.identity
                    self.result_mask = result.mask
                    self.canvas.set_mask(result.mask)
                    try:
                        is_current = pending.identity == self._current_identity()
                    except SamError:
                        is_current = False
                    if is_current:
                        self._set_status(
                            "Current", "Inspect the mask, then Apply it to the selection."
                        )
                    else:
                        self._set_status(
                            "Stale", "A result arrived for older points or settings."
                        )
            elif isinstance(result, CancelledError):
                self._set_status(
                    "Ready", "Request cancelled locally; server work may continue."
                )
            elif isinstance(result, SubmissionUncertainError):
                self._set_status("Failed", str(result))
            else:
                self._set_status("Failed", str(result))
        except Exception as error:
            self._set_status("Failed", f"Could not accept the returned mask: {error}")

        next_request = self.slot.settle(uncertain=uncertain)
        if uncertain:
            dialog = Gtk.MessageDialog(
                transient_for=self.window,
                modal=True,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK,
                text="Prompt submission outcome is unknown.",
            )
            dialog.format_secondary_text(str(result))
            dialog.run()
            dialog.destroy()
            self.slot.acknowledge()
        elif next_request is not None:
            try:
                still_current = next_request.identity == self._current_identity()
            except SamError:
                still_current = False
            if still_current:
                self._launch(next_request)
            else:
                self.slot.settle()
                self._set_status("Stale", "Queued generation was discarded after newer edits.")
        self._update_actions()
        return GLib.SOURCE_REMOVE

    def _cancel(self, _button: Gtk.Button) -> None:
        self.slot.cancel()
        if self.active_cancel is not None:
            self.active_cancel.set()
        self._set_status(
            "Cancelled", "Waiting for the local worker to settle; late server output is ignored.", True
        )

    def _apply(self, _button: Gtk.Button) -> None:
        try:
            blocker = self._apply_blocker()
            if blocker is not None:
                raise SamError(blocker)
            if not self._validate_source():
                return
            operations = (
                Gimp.ChannelOps.REPLACE,
                Gimp.ChannelOps.ADD,
                Gimp.ChannelOps.SUBTRACT,
                Gimp.ChannelOps.INTERSECT,
            )
            selected_pixels = apply_selection(
                self.image,
                self.snapshot,
                self.result_mask,
                operations[self.selection_mode.get_active()],
            )
            _ok, nonempty, x1, y1, x2, y2 = Gimp.Selection.bounds(self.image)
            if selected_pixels and not nonempty:
                raise SamError("GIMP no longer reports a selection after Apply.")
            if nonempty:
                detail = (
                    f"GIMP selection: {selected_pixels:,} pixels, bounds "
                    f"({x1}, {y1})–({x2}, {y2}). "
                    "If no outline is visible, check View → Show Selection."
                )
            else:
                detail = "GIMP selection is empty; the chosen mode or mask selected no pixels."
            self._set_status(
                "Current",
                detail,
            )
            self.apply_feedback.set_text(
                f"Applied to GIMP: {selected_pixels:,} selected pixels. "
                "If the outline is hidden, enable View → Show Selection (Ctrl+T) in GIMP."
            )
            self.apply_feedback.show()
        except Exception as error:
            self._set_status("Failed", f"Apply failed: {error}")

    def _test_connection(self, _button: Gtk.Button) -> None:
        try:
            endpoint = normalize_endpoint(self.endpoint_entry.get_text())
        except SamError as error:
            self._set_status("Failed", str(error))
            return
        self.test_button.set_sensitive(False)
        self._set_status("Testing", f"Checking {endpoint}.", True)

        def work() -> None:
            try:
                metadata: object = ComfyClient(endpoint).inspect()
            except Exception as error:
                metadata = error
            GLib.idle_add(done, metadata)

        def done(metadata: object) -> bool:
            if self.closed:
                return GLib.SOURCE_REMOVE
            self.test_button.set_sensitive(True)
            if isinstance(metadata, Exception):
                self._set_status("Failed", str(metadata))
            else:
                self._save_settings()
                self._set_status("Ready", f"ComfyUI is compatible; Server URL saved: {endpoint}")
            return GLib.SOURCE_REMOVE

        threading.Thread(target=work, name="gimp-sam-test", daemon=True).start()

    def _save_endpoint_clicked(self, _button: Gtk.Button) -> None:
        try:
            endpoint = normalize_endpoint(self.endpoint_entry.get_text())
            self.endpoint_entry.set_text(endpoint)
        except SamError as error:
            self._set_status("Failed", str(error))
            return
        self._save_settings()
        self._set_status("Ready", f"Server URL saved: {endpoint}")

    def _show_error(self, title: str, detail: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text=title,
        )
        dialog.format_secondary_text(detail)
        dialog.run()
        dialog.destroy()

    def _save_settings(self) -> None:
        try:
            endpoint = normalize_endpoint(self.endpoint_entry.get_text())
        except SamError:
            endpoint = get_default_endpoint()
        save_settings(
            {
                "endpoint": endpoint,
                "threshold": round(self.threshold.get_value(), 2),
                "refinement": self.refinement.get_value_as_int(),
            }
        )

    def _close(self, *_args: object) -> bool:
        if self.closed:
            return True
        self.closed = True
        if self.active_cancel is not None:
            self.active_cancel.set()
        try:
            self._save_settings()
        except OSError:
            pass
        finally:
            self.window.destroy()
            Gtk.main_quit()
        return True


