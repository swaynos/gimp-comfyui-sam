import pathlib
import struct
import sys
import unittest
import zlib


PLUGIN = pathlib.Path(__file__).parents[1] / "plug-ins" / "gimp-comfyui-sam"
sys.path.insert(0, str(PLUGIN))

from sam_png import PNG_SIGNATURE, encode_png  # noqa: E402


class PngTests(unittest.TestCase):
    def test_rgba_encoding(self):
        pixels = bytes([255, 0, 0, 255, 0, 255, 0, 128])
        png = encode_png(2, 1, pixels, 4)
        self.assertTrue(png.startswith(PNG_SIGNATURE))
        width, height, depth, color_type = struct.unpack(">IIBB", png[16:26])
        self.assertEqual((width, height, depth, color_type), (2, 1, 8, 6))
        idat_length = struct.unpack(">I", png[33:37])[0]
        self.assertEqual(zlib.decompress(png[41 : 41 + idat_length]), b"\x00" + pixels)

    def test_rejects_bad_buffer_size(self):
        with self.assertRaises(ValueError):
            encode_png(2, 2, b"short", 3)


if __name__ == "__main__":
    unittest.main()
