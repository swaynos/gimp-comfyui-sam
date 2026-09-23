"""Small dependency-free PNG encoder for 8-bit RGB/RGBA snapshots."""

from __future__ import annotations

import struct
import zlib


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind)
    checksum = zlib.crc32(payload, checksum)
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def _append_chunk(result: bytearray, kind: bytes, payload: bytes | bytearray) -> None:
    result.extend(struct.pack(">I", len(payload)))
    result.extend(kind)
    result.extend(payload)
    checksum = zlib.crc32(kind)
    checksum = zlib.crc32(payload, checksum)
    result.extend(struct.pack(">I", checksum))


def encode_png(width: int, height: int, pixels: bytes, channels: int) -> bytes:
    if width <= 0 or height <= 0:
        raise ValueError("PNG dimensions must be positive")
    if channels not in (3, 4):
        raise ValueError("Only RGB and RGBA PNG encoding is supported")
    row_bytes = width * channels
    if len(pixels) != row_bytes * height:
        raise ValueError("Pixel buffer size does not match PNG dimensions")

    compressor = zlib.compressobj(6)
    compressed = bytearray()
    for y in range(height):
        source = y * row_bytes
        compressed.extend(compressor.compress(b"\x00" + pixels[source : source + row_bytes]))
    compressed.extend(compressor.flush())

    color_type = 2 if channels == 3 else 6
    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    result = bytearray(PNG_SIGNATURE)
    _append_chunk(result, b"IHDR", header)
    _append_chunk(result, b"IDAT", compressed)
    _append_chunk(result, b"IEND", b"")
    return bytes(result)
