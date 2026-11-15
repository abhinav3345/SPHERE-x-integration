"""The binary frame file ``frames.bin`` (Contract v1.0, section 6).

The planes concatenated in ``planes[].index`` order and nothing else: no header. Each plane is ``ny x nx``
little-endian IEEE float16, row-major, row 0 north, column 0 east. NaN means "no data". Values are surface
brightness in MJy/sr.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

import numpy as np

from tombaugh.types import StackedPlane

FRAME_DTYPE = np.dtype("<f2")  # little-endian IEEE float16
BYTES_PER_PIXEL = 2
FLOAT16_MAX = float(np.finfo(np.float16).max)  # 65504.0, the largest finite float16


def plane_offset(index: int, ny: int, nx: int) -> int:
    """Byte offset of plane ``index`` in frames.bin: ``index * ny * nx * 2``."""
    return int(index) * int(ny) * int(nx) * BYTES_PER_PIXEL


def _as_array(plane) -> np.ndarray:
    data = plane.data if isinstance(plane, StackedPlane) else plane
    return np.asarray(data)


def encode_planes(planes: Iterable) -> bytes:
    """Encode planes (2-D arrays or ``StackedPlane``s, all of one shape) as the bytes of frames.bin.

    Values beyond the float16 range, including infinities, are clipped to the largest finite float16
    (65504 MJy/sr in absolute value), so the file holds only finite numbers and NaN. NaN is preserved.
    """
    chunks: list[bytes] = []
    shape: tuple[int, ...] | None = None
    for plane in planes:
        data = _as_array(plane)
        if data.ndim != 2:
            raise ValueError(f"every plane must be 2-D, got shape {data.shape}")
        if shape is None:
            shape = data.shape
        elif data.shape != shape:
            raise ValueError(f"planes differ in shape: {data.shape} and {shape}")
        clipped = np.clip(
            data.astype(np.float64, copy=False), -FLOAT16_MAX, FLOAT16_MAX
        )  # NaN passes through
        chunks.append(np.ascontiguousarray(clipped).astype(FRAME_DTYPE).tobytes(order="C"))
    return b"".join(chunks)


def decode_planes(buf: bytes, n_planes: int, ny: int, nx: int) -> np.ndarray:
    """Decode the bytes of frames.bin into a float32 array of shape (n_planes, ny, nx)."""
    expected = plane_offset(n_planes, ny, nx)
    if len(buf) != expected:
        raise ValueError(
            f"frames buffer holds {len(buf)} bytes, expected {expected} for {n_planes} x {ny} x {nx}"
        )
    flat = np.frombuffer(buf, dtype=FRAME_DTYPE)
    return flat.astype(np.float32).reshape(int(n_planes), int(ny), int(nx))


def sha256_hex(buf: bytes) -> str:
    """Lower-case hexadecimal SHA-256 of the uncompressed frame bytes."""
    return hashlib.sha256(buf).hexdigest()
