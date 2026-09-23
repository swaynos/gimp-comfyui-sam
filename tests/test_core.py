import pathlib
import sys
import unittest


PLUGIN = pathlib.Path(__file__).parents[1] / "plug-ins" / "gimp-comfyui-sam"
sys.path.insert(0, str(PLUGIN))

from sam_core import (  # noqa: E402
    GenerationIdentity,
    InvalidMaskError,
    Point,
    RequestSlot,
    ViewTransform,
    mask_from_pixels,
    points_for_request,
    round_half_up,
    source_revision,
)


class CoordinateTests(unittest.TestCase):
    def test_half_up_rounding(self):
        self.assertEqual(round_half_up(0.49), 0)
        self.assertEqual(round_half_up(0.5), 1)
        self.assertEqual(round_half_up(99.5), 100)

    def test_point_arrays_and_bounds(self):
        positive, negative = points_for_request(
            [Point(4.5, 8.49, True), Point(2.2, 3.8, False)], 10, 10
        )
        self.assertEqual(positive, [{"x": 5, "y": 8}])
        self.assertEqual(negative, [{"x": 2, "y": 4}])

    def test_view_transform_round_trip_and_cursor_zoom(self):
        transform = ViewTransform.fitted(1000, 500, 500, 500)
        screen = transform.source_to_screen(250.25, 120.75)
        source = transform.screen_to_source(*screen)
        self.assertIsNotNone(source)
        self.assertAlmostEqual(source[0], 250.25)
        self.assertAlmostEqual(source[1], 120.75)
        anchor_before = transform.screen_to_source_unbounded(100, 200)
        transform.zoom_at(100, 200, 1.25)
        anchor_after = transform.screen_to_source_unbounded(100, 200)
        self.assertAlmostEqual(anchor_before[0], anchor_after[0])
        self.assertAlmostEqual(anchor_before[1], anchor_after[1])


class MaskTests(unittest.TestCase):
    def test_rgb_mask_with_padded_rows(self):
        pixels = bytes([0, 0, 0, 255, 255, 255, 9, 9, 128, 128, 128, 64, 64, 64, 9, 9])
        self.assertEqual(mask_from_pixels(pixels, 2, 2, 3, 8, 2, 2), bytes([0, 255, 128, 64]))

    def test_rejects_nonuniform_rgb(self):
        with self.assertRaises(InvalidMaskError):
            mask_from_pixels(bytes([10, 11, 10]), 1, 1, 3, 3, 1, 1)

    def test_ignores_rgba_alpha(self):
        self.assertEqual(
            mask_from_pixels(bytes([10, 10, 10, 100]), 1, 1, 4, 4, 1, 1),
            bytes([10]),
        )


class LifecycleTests(unittest.TestCase):
    def test_slot_keeps_only_newest_queue(self):
        slot = RequestSlot[str]()
        self.assertTrue(slot.submit("one"))
        self.assertFalse(slot.submit("two"))
        self.assertFalse(slot.submit("three"))
        self.assertEqual(slot.settle(), "three")
        self.assertEqual(slot.active, "three")
        self.assertIsNone(slot.settle())
        self.assertEqual(slot.state, "idle")

    def test_uncertain_discards_queue(self):
        slot = RequestSlot[str]()
        slot.submit("one")
        slot.submit("two")
        self.assertIsNone(slot.settle(uncertain=True))
        self.assertEqual(slot.state, "uncertain")
        self.assertIsNone(slot.queued)
        slot.acknowledge()
        self.assertEqual(slot.state, "idle")

    def test_source_revision_includes_metadata(self):
        first = source_revision({"offset": 1}, b"pixels")
        second = source_revision({"offset": 2}, b"pixels")
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
