"""Pure domain logic for the GIMP ComfyUI SAM plug-in."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Generic, Iterable, Optional, TypeVar


MAX_SOURCE_PIXELS = 100_000_000
MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
WORKFLOW_VERSION = 1


class SamError(Exception):
    """Base class for errors that can be shown to the user."""


class InvalidMaskError(SamError):
    """Raised when a returned image cannot safely become a selection."""


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    positive: bool


@dataclass(frozen=True)
class GenerationIdentity:
    session_id: str
    source_revision: str
    point_revision: int
    endpoint: str
    threshold: float
    refinement: int
    workflow_version: int = WORKFLOW_VERSION


def round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def points_for_request(
    points: Iterable[Point], width: int, height: int
) -> tuple[list[dict[str, int]], list[dict[str, int]]]:
    positive: list[dict[str, int]] = []
    negative: list[dict[str, int]] = []
    for point in points:
        x = round_half_up(point.x)
        y = round_half_up(point.y)
        if not (0 <= x < width and 0 <= y < height):
            raise SamError("A prompt point is outside the source image.")
        target = positive if point.positive else negative
        target.append({"x": x, "y": y})
    if not positive:
        raise SamError("Add at least one positive point before generating.")
    return positive, negative


@dataclass
class ViewTransform:
    source_width: int
    source_height: int
    viewport_width: int
    viewport_height: int
    zoom: float
    pan_x: float = 0.0
    pan_y: float = 0.0

    @classmethod
    def fitted(
        cls, source_width: int, source_height: int, viewport_width: int, viewport_height: int
    ) -> "ViewTransform":
        zoom = min(viewport_width / source_width, viewport_height / source_height)
        return cls(source_width, source_height, viewport_width, viewport_height, zoom)

    @property
    def origin(self) -> tuple[float, float]:
        return (
            (self.viewport_width - self.source_width * self.zoom) / 2.0 + self.pan_x,
            (self.viewport_height - self.source_height * self.zoom) / 2.0 + self.pan_y,
        )

    def source_to_screen(self, x: float, y: float) -> tuple[float, float]:
        ox, oy = self.origin
        return ox + x * self.zoom, oy + y * self.zoom

    def screen_to_source(self, x: float, y: float) -> Optional[tuple[float, float]]:
        ox, oy = self.origin
        source_x = (x - ox) / self.zoom
        source_y = (y - oy) / self.zoom
        if not (0.0 <= source_x < self.source_width and 0.0 <= source_y < self.source_height):
            return None
        return source_x, source_y

    def zoom_at(self, screen_x: float, screen_y: float, new_zoom: float) -> None:
        source = self.screen_to_source_unbounded(screen_x, screen_y)
        old_center_x = (self.viewport_width - self.source_width * new_zoom) / 2.0
        old_center_y = (self.viewport_height - self.source_height * new_zoom) / 2.0
        self.zoom = new_zoom
        self.pan_x = screen_x - source[0] * new_zoom - old_center_x
        self.pan_y = screen_y - source[1] * new_zoom - old_center_y

    def screen_to_source_unbounded(self, x: float, y: float) -> tuple[float, float]:
        ox, oy = self.origin
        return (x - ox) / self.zoom, (y - oy) / self.zoom


def source_revision(metadata: dict[str, object], pixels: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    digest.update(pixels)
    return digest.hexdigest()


def mask_from_pixels(
    pixels: bytes,
    width: int,
    height: int,
    channels: int,
    rowstride: int,
    expected_width: int,
    expected_height: int,
) -> bytes:
    if width != expected_width or height != expected_height:
        raise InvalidMaskError(
            f"Mask dimensions {width}x{height} do not match source "
            f"{expected_width}x{expected_height}."
        )
    if width <= 0 or height <= 0 or width * height > MAX_SOURCE_PIXELS:
        raise InvalidMaskError("Mask dimensions exceed the configured safety limit.")
    if channels not in (1, 3, 4):
        raise InvalidMaskError(f"Unsupported mask channel count: {channels}.")
    if rowstride < width * channels or len(pixels) < rowstride * height:
        raise InvalidMaskError("Mask pixel buffer is truncated.")

    result = bytearray(width * height)
    output_offset = 0
    for y in range(height):
        row = y * rowstride
        for x in range(width):
            offset = row + x * channels
            value = pixels[offset]
            if channels >= 3 and (
                pixels[offset + 1] != value or pixels[offset + 2] != value
            ):
                raise InvalidMaskError("Returned RGB mask has nonuniform color channels.")
            result[output_offset] = value
            output_offset += 1
    return bytes(result)


T = TypeVar("T")


class RequestSlot(Generic[T]):
    """One active request plus one replaceable newest queued request."""

    def __init__(self) -> None:
        self.state = "idle"
        self.active: Optional[T] = None
        self.queued: Optional[T] = None

    def submit(self, request: T) -> bool:
        if self.state == "uncertain":
            raise SamError("A possibly submitted request must be acknowledged first.")
        if self.active is None:
            self.active = request
            self.state = "active"
            return True
        self.queued = request
        return False

    def cancel(self) -> None:
        if self.active is not None:
            self.state = "cancelled"

    def settle(self, uncertain: bool = False) -> Optional[T]:
        self.active = None
        if uncertain:
            self.queued = None
            self.state = "uncertain"
            return None
        next_request = self.queued
        self.queued = None
        if next_request is None:
            self.state = "idle"
        else:
            self.active = next_request
            self.state = "active"
        return next_request

    def acknowledge(self) -> None:
        if self.state == "uncertain":
            self.state = "idle"

    def invalidate_queued(self) -> None:
        self.queued = None
