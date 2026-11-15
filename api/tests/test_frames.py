"""frames.bin encoding (Contract v1.0, section 6). Arrays here are synthetic: this is pure number handling."""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from tombaugh.frames import FLOAT16_MAX, decode_planes, encode_planes, plane_offset, sha256_hex
from tombaugh.types import StackedPlane


def test_bytes_are_little_endian_float16_in_c_order():
    synthetic_plane = np.array([[1.0, -2.0, 0.5], [0.0, 65504.0, np.nan]], dtype=np.float32)
    buf = encode_planes([synthetic_plane])
    assert isinstance(buf, bytes) and len(buf) == 2 * 3 * 2
    assert buf[0:2] == b"\x00\x3c"  # 1.0 is 0x3C00, low byte first
    assert buf[2:4] == b"\x00\xc0"  # -2.0 is 0xC000: the second value of row 0 comes second (row-major)
    assert buf[4:6] == b"\x00\x38"  # 0.5
    assert buf[6:8] == b"\x00\x00"
    assert buf[8:10] == b"\xff\x7b"  # 65504, the largest finite float16
    assert np.isnan(np.frombuffer(buf[10:12], dtype="<f2")[0])


def test_round_trip_preserves_values_and_nan():
    rng = np.random.default_rng(3)
    synthetic_planes = rng.normal(0.0, 0.05, size=(4, 7, 5)).astype(np.float32)
    synthetic_planes[1, 2, 3] = np.nan
    synthetic_planes[3, 0, 0] = np.nan
    buf = encode_planes(synthetic_planes)
    out = decode_planes(buf, 4, 7, 5)
    assert out.dtype == np.float32 and out.shape == (4, 7, 5)
    assert np.array_equal(np.isnan(out), np.isnan(synthetic_planes))
    finite = np.isfinite(synthetic_planes)
    # float16 keeps 11 significant bits; below 6e-5 it is subnormal with a fixed step of 2^-24.
    allowed = np.maximum(np.abs(synthetic_planes[finite]) * 2.0**-11, 2.0**-25) * 1.001
    assert np.all(np.abs(out[finite].astype(np.float64) - synthetic_planes[finite]) <= allowed)
    assert np.array_equal(out, decode_planes(encode_planes(out), 4, 7, 5), equal_nan=True)  # idempotent


def test_planes_are_concatenated_at_the_contract_offsets():
    ny, nx = 3, 4
    synthetic_planes = [np.full((ny, nx), float(i), dtype=np.float32) for i in range(5)]
    buf = encode_planes(synthetic_planes)
    assert len(buf) == plane_offset(5, ny, nx) == 5 * ny * nx * 2
    for index in range(5):
        start = plane_offset(index, ny, nx)
        assert start == index * ny * nx * 2
        one = np.frombuffer(buf[start : start + ny * nx * 2], dtype="<f2").reshape(ny, nx)
        assert np.all(one == index)
    assert np.array_equal(decode_planes(buf, 5, ny, nx), np.stack(synthetic_planes))


def test_values_beyond_float16_are_clipped_not_turned_into_infinity():
    synthetic_plane = np.array(
        [[1e6, -1e6, 65519.99, 65520.0], [np.inf, -np.inf, 3.0e38, np.nan]], dtype=np.float64
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # no overflow warning may escape
        out = decode_planes(encode_planes([synthetic_plane]), 1, 2, 4)[0]
    assert FLOAT16_MAX == 65504.0
    assert out[0].tolist() == [65504.0, -65504.0, 65504.0, 65504.0]
    assert out[1, :3].tolist() == [65504.0, -65504.0, 65504.0]
    assert np.isnan(out[1, 3])
    assert np.all(np.isfinite(out) | np.isnan(out))


def test_tiny_values_do_not_warn_or_fail():
    synthetic_plane = np.array([[1e-30, -1e-30, 6e-8, 0.0]], dtype=np.float32)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = decode_planes(encode_planes([synthetic_plane]), 1, 1, 4)
    assert np.all(np.abs(out) < 1e-6)


def test_accepts_stacked_planes_and_any_float_dtype():
    synthetic_data = np.arange(6, dtype=np.float64).reshape(2, 3)
    plane = StackedPlane(
        time_bin=0,
        wave_bin=20,
        data=synthetic_data.astype(np.float32),
        n_exposures=3,
        sigma=0.02,
        lam_eff=4.49,
        mjd_mid=60990.1,
        mjd_min=60986.2,
        mjd_max=60993.9,
    )
    assert encode_planes([plane]) == encode_planes([synthetic_data]) == encode_planes(synthetic_data[None])
    big_endian = synthetic_data.astype(">f4")
    assert encode_planes([big_endian]) == encode_planes([synthetic_data])
    not_contiguous = np.asfortranarray(synthetic_data)
    assert encode_planes([not_contiguous]) == encode_planes([synthetic_data])


def test_no_planes_is_an_empty_file():
    assert encode_planes([]) == b""
    assert decode_planes(b"", 0, 119, 119).shape == (0, 119, 119)


def test_shape_errors():
    with pytest.raises(ValueError):
        encode_planes([np.zeros((2, 3)), np.zeros((3, 2))])
    with pytest.raises(ValueError):
        encode_planes([np.zeros(6)])
    with pytest.raises(ValueError):
        decode_planes(b"\x00" * 10, 1, 2, 3)


def test_sha256_hex():
    assert sha256_hex(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert sha256_hex(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    synthetic_plane = np.zeros((2, 2), dtype=np.float32)
    assert sha256_hex(encode_planes([synthetic_plane])) == sha256_hex(b"\x00" * 8)
