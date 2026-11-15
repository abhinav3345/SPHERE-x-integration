"""tombaugh.remote_fits replayed on recorded real bytes (tests/data/reader, see its README). No network.

`http.get_range` is replaced by a stand-in that serves exactly the byte ranges recorded from one real
exposure; a request for anything else fails the test. The expected window comes from an independent
route: the whole file opened by astropy.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

from tombaugh import http
from tombaugh import remote_fits as rf
from tombaugh.types import Cutout, Exposure

pytestmark = pytest.mark.filterwarnings("ignore::astropy.wcs.FITSFixedWarning")

DATA = Path(__file__).parent / "data" / "reader"
SAMPLE = json.loads((DATA / "exposure.json").read_text())
EXP = Exposure(**SAMPLE["exposure"])
RA, DEC, HALF = SAMPLE["request"]["ra"], SAMPLE["request"]["dec"], SAMPLE["request"]["half_px"]
TOTAL = SAMPLE["request"]["total_bytes"]
RANGES = {key: array.tobytes() for key, array in np.load(DATA / "ranges.npz").items()}
EXPECTED = dict(np.load(DATA / "expected.npz"))

HEAD = (0, 34560)
IMAGE_ROWS = (1249920, 1388640)
FLAGS_DESC = (16672320, 16705920)
FLAGS_HEAP = (17579623, 17680098)
ZODI_BLOCK = (46457280, 46489920)
VARIANCE_BLOCK = (29799360, 29832000)
VARIANCE_HEADER = (28514880, 28526400)
ZODI_HEADER = (45172800, 45184320)
COLD = [HEAD, IMAGE_ROWS, FLAGS_DESC, FLAGS_HEAP, ZODI_BLOCK, VARIANCE_BLOCK]

IMAGE_HEADER = fits.Header.fromstring(RANGES["0_34560"][2880:25920].decode("ascii"))
BUNDLED = Path(rf.__file__).parent / "data"


class Replay:
    """Stands in for http.get_range: the recorded ranges of the one recorded object, and nothing else."""

    def __init__(self, total: int | None) -> None:
        self.total = total
        self.calls: list[tuple[int, int]] = []
        self.deadlines: list[http.Deadline | None] = []
        self._lock = threading.Lock()

    def __call__(self, url: str, start: int, end: int, *, deadline: http.Deadline | None = None) -> bytes:
        with self._lock:
            if deadline is not None and deadline.expired:  # as the real get_range: nothing is sent
                raise http.DeadlineExceeded("deadline expired", url=url)
            self.calls.append((start, end))
            self.deadlines.append(deadline)
        if url != EXP.url:
            raise http.UpstreamError("HTTP 404", url=url, status=404, attempts=1)
        body = RANGES.get(f"{start}_{end}")
        assert body is not None, f"the reader asked for bytes [{start}, {end}), which were not recorded"
        return body if self.total is None else http.RangeBytes(body, self.total)


@pytest.fixture
def replay(monkeypatch: pytest.MonkeyPatch):
    """Returns install(total=...) which puts a fresh `Replay` in place of http.get_range."""
    rf.clear_cache()

    def install(total: int | None = TOTAL) -> Replay:
        stand_in = Replay(total)
        monkeypatch.setattr(http, "get_range", stand_in)
        return stand_in

    yield install
    wait_for_idle_workers()
    rf.clear_cache()


def wait_for_idle_workers() -> None:
    """Block until no reader thread is still busy with an exposure of an earlier call."""
    for workers, pool in list(rf._pools.items()):
        together = threading.Barrier(workers, timeout=30)  # passes only when every thread of the pool is free
        for job in [pool.submit(together.wait) for _ in range(workers)]:
            job.result()


def assert_matches_expected(cutout: Cutout | None) -> None:
    assert cutout is not None
    assert cutout.image.dtype == np.float32 and cutout.image.shape == (2 * HALF + 1, 2 * HALF + 1)
    assert np.array_equal(cutout.image, EXPECTED["image"], equal_nan=True)
    assert cutout.flags is not None and cutout.flags.dtype == np.int32
    assert np.array_equal(cutout.flags, EXPECTED["flags"])
    assert (cutout.x0, cutout.y0) == (int(EXPECTED["x0"]), int(EXPECTED["y0"])) == (353, 150)
    assert cutout.lam == pytest.approx(float(EXPECTED["lam"]), abs=1e-6)
    assert cutout.dlam == pytest.approx(float(EXPECTED["dlam"]), abs=1e-6)
    assert cutout.mjd == float(EXPECTED["mjd"]) == 60800.70069465
    assert cutout.psf_fwhm == float(EXPECTED["psf_fwhm"])
    assert cutout.zodi_level == float(EXPECTED["zodi_level"])
    assert cutout.sky_var == float(EXPECTED["sky_var"])
    assert cutout.version == "l2b-v27-2026-197"
    assert cutout.exposure is EXP


# --------------------------------------------------------------------------- the recorded window
def test_the_recording_is_not_trivial() -> None:
    assert np.isfinite(EXPECTED["image"]).all() and np.ptp(EXPECTED["image"]) > 0.5  # MJy/sr: a real source
    assert len(np.unique(EXPECTED["flags"])) == 5 and np.count_nonzero(EXPECTED["flags"]) == 132
    assert sum(len(body) for body in RANGES.values()) == 395675


def test_window_reproduces_the_independent_route_in_six_requests(replay) -> None:
    stand_in = replay()
    assert_matches_expected(rf.read_window(EXP, RA, DEC, HALF))
    assert stand_in.calls == COLD


def test_the_window_is_centred_on_the_pixel_nearest_the_position(replay) -> None:
    replay()
    cutout = rf.read_window(EXP, RA, DEC, HALF)
    x, y = float(EXPECTED["x"]), float(EXPECTED["y"])  # from solving the forward WCS numerically
    assert (cutout.x0 + HALF, cutout.y0 + HALF) == (round(x), round(y)) == (361, 158)
    header = fits.Header.fromstring(cutout.wcs_header, sep="\n")
    assert header["CTYPE1"] == "RA---TAN-SIP" and header["A_ORDER"] == 3  # the distortion terms are kept
    assert header["MJD-AVG"] == cutout.mjd and header["NAXIS1"] == header["NAXIS2"] == 2040
    assert [float(v) for v in WCS(header).all_world2pix(RA, DEC, 0)] == pytest.approx([x, y], abs=1e-4)
    assert rf.wavelength_at(EXP.det, cutout.wcs_header, x, y) == pytest.approx(
        (cutout.lam, cutout.dlam), abs=1e-9
    )


def test_a_second_window_on_the_same_file_needs_fewer_requests(replay) -> None:
    stand_in = replay()
    first = rf.read_window(EXP, RA, DEC, HALF)
    second = rf.read_window(EXP, RA, DEC, HALF)
    assert_matches_expected(first)
    assert_matches_expected(second)
    assert stand_in.calls == COLD + [IMAGE_ROWS, FLAGS_HEAP, ZODI_BLOCK, VARIANCE_BLOCK]
    image_only = rf.read_window(EXP, RA, DEC, HALF, want_flags=False, want_levels=False)
    assert stand_in.calls[10:] == [IMAGE_ROWS]
    assert image_only.flags is None and image_only.zodi_level is None and image_only.sky_var is None
    assert np.array_equal(image_only.image, EXPECTED["image"])


@pytest.mark.parametrize(
    ("want_flags", "want_levels", "calls"),
    [
        (False, False, [HEAD, IMAGE_ROWS]),
        (True, False, [HEAD, IMAGE_ROWS, FLAGS_DESC, FLAGS_HEAP]),
        (
            False,
            True,
            [HEAD, IMAGE_ROWS, FLAGS_DESC, ZODI_BLOCK, VARIANCE_BLOCK],
        ),  # FLAGS header proves the offsets
    ],
)
def test_only_what_is_wanted_is_requested(replay, want_flags: bool, want_levels: bool, calls: list) -> None:
    stand_in = replay()
    cutout = rf.read_window(EXP, RA, DEC, HALF, want_flags=want_flags, want_levels=want_levels)
    assert stand_in.calls == calls
    assert np.array_equal(cutout.image, EXPECTED["image"])
    assert (cutout.flags is not None) == want_flags
    assert (cutout.zodi_level is not None) == (cutout.sky_var is not None) == want_levels
    if want_flags:
        assert np.array_equal(cutout.flags, EXPECTED["flags"])
    if want_levels:
        assert (cutout.zodi_level, cutout.sky_var) == (
            float(EXPECTED["zodi_level"]),
            float(EXPECTED["sky_var"]),
        )


def test_every_request_carries_the_deadline(replay) -> None:
    stand_in = replay()
    deadline = http.Deadline(60.0)
    rf.read_window(EXP, RA, DEC, HALF, deadline=deadline)
    assert len(stand_in.deadlines) == 6 and all(given is deadline for given in stand_in.deadlines)


# --------------------------------------------------------------------------- offsets are verified
def test_offsets_counted_from_the_end_agree_with_the_parsed_flags_header() -> None:
    """The consistency check on the real file: FLAGS header plus heap lands exactly on VARIANCE."""
    desc = RANGES["16672320_16705920"]
    flags_header = fits.Header.fromstring(desc[:17280].decode("ascii"))
    after_flags = 16672320 + 17280 + rf._data_nbytes(flags_header)
    zodi_hdu, variance_hdu = rf._levels_from_end(TOTAL, EXP.det)
    assert after_flags == variance_hdu == VARIANCE_HEADER[0] and zodi_hdu == ZODI_HEADER[0]
    assert rf._levels_from_end(TOTAL, 1)[1] != after_flags  # detector 3 has its own EPSF size
    assert RANGES["28514880_28526400"][:80].startswith(b"XTENSION= 'IMAGE   '")
    assert fits.Header.fromstring(RANGES["28514880_28526400"].decode("ascii"))["EXTNAME"] == "VARIANCE"
    assert fits.Header.fromstring(RANGES["45172800_45184320"].decode("ascii"))["EXTNAME"] == "ZODI"


@pytest.mark.parametrize("total", [None, TOTAL + 2880, TOTAL - 86400])
def test_falls_back_to_walking_the_headers_when_the_end_cannot_be_trusted(replay, total: int | None) -> None:
    """Unknown object size, or a size that fails the consistency check: two header reads replace the guess."""
    stand_in = replay(total)
    assert_matches_expected(rf.read_window(EXP, RA, DEC, HALF))
    assert stand_in.calls == [*COLD[:4], VARIANCE_HEADER, ZODI_HEADER, ZODI_BLOCK, VARIANCE_BLOCK]
    assert_matches_expected(rf.read_window(EXP, RA, DEC, HALF))  # the walk is remembered
    assert stand_in.calls[8:] == [IMAGE_ROWS, FLAGS_HEAP, ZODI_BLOCK, VARIANCE_BLOCK]


def test_a_listing_that_names_the_wrong_detector_is_refused(replay) -> None:
    replay()
    with pytest.raises(rf.ReadError, match="detector 3"):
        rf.read_window(replace(EXP, det=4), RA, DEC, HALF)


def test_bytes_that_are_not_fits_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    rf.clear_cache()
    monkeypatch.setattr(
        http, "get_range", lambda url, start, end, **kw: http.RangeBytes(b"<html>" * 5760, 34560)
    )
    with pytest.raises(rf.ReadError):
        rf.read_window(EXP, RA, DEC, HALF)
    monkeypatch.setattr(
        http, "get_range", lambda url, start, end, **kw: http.RangeBytes(RANGES["0_34560"][:2880], 2880)
    )
    with pytest.raises(rf.ReadError, match="ends before"):
        rf.read_window(EXP, RA, DEC, HALF)
    assert len(rf._cache) == 0  # nothing unusable was remembered


def test_header_helpers_on_the_recorded_head() -> None:
    head = RANGES["0_34560"]
    assert rf._header_end(head) == 2880  # PRIMARY: one block
    assert rf._header_end(head[2880:]) == 23040  # IMAGE header of a detector 3 file
    assert rf._header_end(head[2880:20000]) is None  # the END card of the IMAGE header is not in these bytes
    assert (
        rf._header_end(head[:2000]) == 2880
    )  # END seen: the length is whole blocks even if the padding is cut
    assert rf._split_head(head) == (2880, 23040)
    assert rf._data_nbytes(rf._parse_header(head[:2880])) == 0
    assert rf._data_nbytes(IMAGE_HEADER) == rf.IMAGE_BYTES == 16646400
    rf._check_plane(IMAGE_HEADER, "IMAGE")
    with pytest.raises(rf.ReadError):
        rf._check_plane(IMAGE_HEADER, "VARIANCE")
    with pytest.raises(rf.ReadError):
        rf._parse_header(head[80:2880])


def test_layout_constants() -> None:
    assert (rf.NX, rf.NY, rf.ROW_BYTES, rf.IMAGE_BYTES) == (2040, 2040, 8160, 16646400)
    assert rf.IMAGE_BYTES % rf.BLOCK == 0 and rf.HEAD_BYTES == 12 * rf.BLOCK
    assert rf.FLAGS_HEADER_BYTES + rf.FLAGS_DESC_BYTES == FLAGS_DESC[1] - FLAGS_DESC[0]
    assert rf.EPSF_DATA_BYTES == {1: 3862080, 2: 3862080, 3: 3948480, 4: 3862080, 5: 3862080, 6: 3862080}
    assert rf.META_CACHE_FILES == 2000


# --------------------------------------------------------------------------- off the detector
def test_a_position_off_the_detector_gives_none_after_the_head_alone(replay) -> None:
    stand_in = replay()
    wcs = WCS(IMAGE_HEADER)
    for x, y in [
        (-40.0, 300.0),
        (2100.0, 1000.0),
        (1000.0, -0.6),
        (1000.0, 2039.6),
        (-250.0, -250.0),
        (5000.0, 900.0),
    ]:
        ra, dec = (float(v) for v in wcs.all_pix2world(x, y, 0))
        assert rf.read_window(EXP, ra, dec, HALF) is None
    assert rf.read_window(EXP, RA + 90.0, DEC, HALF) is None
    assert rf.read_window(EXP, (RA + 180.0) % 360.0, -DEC, HALF) is None  # the opposite point of the sky
    assert stand_in.calls == [HEAD]


def test_half_px_is_bounded(replay) -> None:
    stand_in = replay()
    for half_px in (-1, rf.MAX_HALF_PX + 1):
        with pytest.raises(ValueError):
            rf.read_window(EXP, RA, DEC, half_px)
    assert stand_in.calls == []


# --------------------------------------------------------------------------- window geometry (pure maths)
def test_window_inside_the_detector() -> None:
    window = rf._Window(361, 158, 8)
    assert (window.x0, window.y0, window.side) == (353, 150, 17)
    assert window.cols == (353, 370) and window.rows == (150, 167)


def test_parts_beyond_the_edge_are_nan_in_images_and_zero_in_flags() -> None:
    window = rf._Window(1, 2038, 3)  # hangs 2 columns off the left edge and 2 rows off the last row
    assert (window.x0, window.y0, window.side) == (-2, 2035, 7)
    assert window.cols == (0, 5) and window.rows == (2035, 2040)
    synthetic_rows = np.arange(5 * rf.NX, dtype=">f4").reshape(5, rf.NX)
    image = window.paste(synthetic_rows, np.nan, np.float32)
    assert image.shape == (7, 7) and image.dtype == np.float32
    assert np.isnan(image[:, :2]).all() and np.isnan(image[5:, :]).all()
    assert np.array_equal(image[:5, 2:], synthetic_rows[:, :5])
    synthetic_bits = np.full((5, rf.NX), 0x200000, dtype=">i4")
    flags = window.paste(synthetic_bits, 0, np.int32)
    assert flags.dtype == np.int32 and np.count_nonzero(flags) == 25
    assert not flags[:, :2].any() and not flags[5:, :].any() and (flags[:5, 2:] == 0x200000).all()


@pytest.mark.parametrize(("yc", "first_row"), [(0, 0), (1, 0), (158, 156), (2038, 2036), (2039, 2036)])
def test_level_block_is_four_rows_through_the_centre(
    monkeypatch: pytest.MonkeyPatch, yc: int, first_row: int
) -> None:
    asked: list[tuple[int, int]] = []
    synthetic_block = np.arange(rf.LEVEL_ROWS * rf.NX, dtype=">f4").reshape(rf.LEVEL_ROWS, rf.NX)
    synthetic_block[0, 100] = np.nan  # a blank pixel must not poison the median

    def fake_range(url: str, start: int, end: int, **kwargs: object) -> bytes:
        asked.append((start, end))
        return synthetic_block.tobytes()

    monkeypatch.setattr(http, "get_range", fake_range)
    level = rf._level(EXP.url, 1000, rf._Window(101, yc, 1), None)
    assert asked == [(1000 + first_row * 8160, 1000 + (first_row + 4) * 8160)]
    assert first_row <= yc < first_row + 4
    expected = np.nanmedian(synthetic_block[:, 100:103].astype(np.float64))
    assert level == pytest.approx(float(expected))


def test_level_of_a_blank_block_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    synthetic_blank = np.full((rf.LEVEL_ROWS, rf.NX), np.nan, dtype=">f4")
    monkeypatch.setattr(http, "get_range", lambda url, start, end, **kw: synthetic_blank.tobytes())
    assert rf._level(EXP.url, 0, rf._Window(500, 500, 4), None) is None


# --------------------------------------------------------------------------- wavelength
def hand_lookup(det: int, x: float, y: float) -> tuple[float, float]:
    """(wavelength, bandwidth) by a bilinear table lookup written out by hand, independent of wcslib."""
    with fits.open(BUNDLED / f"wcs_wave_D{det}.fits") as hdus:
        row = hdus["WCS-WAVE"].data[0]
        xs, ys, values = row["X"].astype(float), row["Y"].astype(float), row["VALUES"].astype(float)

    def cell(index: np.ndarray, coordinate: float) -> tuple[int, float]:
        k = int(np.clip(np.searchsorted(index, coordinate, side="right") - 1, 0, len(index) - 2))
        return k, (coordinate - index[k]) / (index[k + 1] - index[k])

    (kx, fx), (ky, fy) = cell(xs, x + 1.0), cell(ys, y + 1.0)
    value = (
        values[ky, kx] * (1 - fx) * (1 - fy)
        + values[ky, kx + 1] * fx * (1 - fy)
        + values[ky + 1, kx] * (1 - fx) * fy
        + values[ky + 1, kx + 1] * fx * fy
    )
    return float(value[0]), float(value[1])


def test_wavelength_at_the_recorded_position() -> None:
    x, y = float(EXPECTED["x"]), float(EXPECTED["y"])
    lam, dlam = rf.wavelength_at(3, IMAGE_HEADER, x, y)
    assert (
        lam == pytest.approx(float(EXPECTED["lam"]), abs=1e-6) and 1.636 < lam < 2.421
    )  # detector 3, micron
    assert dlam == pytest.approx(float(EXPECTED["dlam"]), abs=1e-6)
    assert rf.wavelength_at(3, IMAGE_HEADER.tostring(sep="\n"), x, y) == (lam, dlam)


@pytest.mark.parametrize(
    ("x", "y"),
    [
        (0.0, 0.0),
        (2039.0, 2039.0),
        (0.0, 2039.0),
        (1020.5, 139.5),
        (500.25, 1500.75),
        (254.9, 34.9),
        (1784.0, 616.0),
    ],
)
def test_wavelength_at_follows_the_bundled_table_across_the_detector(x: float, y: float) -> None:
    assert rf.wavelength_at(3, IMAGE_HEADER, x, y) == pytest.approx(hand_lookup(3, x, y), abs=1e-6)


def test_wavelength_at_refuses_an_unknown_detector() -> None:
    with pytest.raises(ValueError):
        rf.wavelength_at(7, IMAGE_HEADER, 100.0, 100.0)


CONTRACT_RANGES = {  # Contract v1.0 section 4, micron
    1: (0.744, 1.116),
    2: (1.099, 1.651),
    3: (1.636, 2.421),
    4: (2.423, 3.822),
    5: (3.809, 4.420),
    6: (4.412, 5.002),
}
MEASURED_TABLE_SHA1 = {  # sha1 of the table bytes, measured on 48 files on 14 Nov 2026
    1: "63dd36d1dd061649",
    2: "2c146b391bfc1d96",
    3: "d6efae76ce210c69",
    4: "df3727c8ed2deb37",
    5: "02c01c0d33dfa0c9",
    6: "66e10b18e0ec1839",
}


@pytest.mark.parametrize("det", [1, 2, 3, 4, 5, 6])
def test_bundled_wavelength_tables_are_the_measured_ones(det: int) -> None:
    raw = (BUNDLED / f"wcs_wave_D{det}.fits").read_bytes()
    assert len(raw) == 3 * rf.BLOCK  # an empty primary HDU, then the 5760 bytes that end every file
    assert hashlib.sha1(raw[2 * rf.BLOCK :]).hexdigest()[:16] == MEASURED_TABLE_SHA1[det]
    with fits.open(BUNDLED / f"wcs_wave_D{det}.fits") as hdus:
        assert (
            len(hdus) == 2
            and hdus[1].header["EXTNAME"] == "WCS-WAVE"
            and int(hdus[1].header["DETECTOR"]) == det
        )
        values = hdus[1].data[0]["VALUES"]
    low, high = CONTRACT_RANGES[det]
    wavelength, bandwidth = values[..., 0], values[..., 1]
    assert low - 0.05 < wavelength.min() <= low + 0.001 and high - 0.001 <= wavelength.max() < high + 0.05
    assert 0.01 < bandwidth.min() and bandwidth.max() < 0.12


# --------------------------------------------------------------------------- many exposures
def test_read_windows_collects_cutouts_and_failures_in_order(replay) -> None:
    replay()
    unrecorded = replace(
        EXP, obs_id="2025W19_1B_0116_2", key=EXP.key.replace("0116_1", "0116_2")
    )  # replay says 404
    ticks: list[tuple[int, int]] = []
    cutouts, failures = rf.read_windows(
        [EXP, unrecorded, EXP],
        RA,
        DEC,
        HALF,
        workers=3,
        progress=lambda done, total: ticks.append((done, total)),
    )
    assert len(cutouts) == 2
    for cutout in cutouts:
        assert_matches_expected(cutout)
    assert [(exposure, reason.split(":")[0]) for exposure, reason in failures] == [(unrecorded, "upstream")]
    assert "404" in failures[0][1]
    assert ticks == [(1, 3), (2, 3), (3, 3)]


def test_read_windows_reports_off_detector_exposures(replay) -> None:
    stand_in = replay()
    cutouts, failures = rf.read_windows([EXP, EXP], RA + 90.0, DEC, HALF, workers=2)
    assert cutouts == [] and failures == [(EXP, rf.OFF_DETECTOR), (EXP, rf.OFF_DETECTOR)]
    assert rf.OFF_DETECTOR == "off_detector" and set(stand_in.calls) == {HEAD}


def test_read_windows_submits_nothing_after_the_deadline(replay) -> None:
    stand_in = replay()
    ticks: list[tuple[int, int]] = []
    cutouts, failures = rf.read_windows(
        [EXP] * 5,
        RA,
        DEC,
        HALF,
        deadline=http.Deadline(0.0),
        progress=lambda done, total: ticks.append((done, total)),
    )
    assert cutouts == [] and failures == [(EXP, "deadline")] * 5
    assert stand_in.calls == [] and ticks == []


def test_read_windows_turns_any_error_into_a_reason(replay) -> None:
    replay()
    wrong_detector = replace(EXP, det=4)
    cutouts, failures = rf.read_windows([wrong_detector], RA, DEC, HALF)
    assert cutouts == [] and failures[0][0] is wrong_detector and failures[0][1].startswith("unreadable: ")
    rf.clear_cache()
    cutouts, failures = rf.read_windows([EXP], RA, DEC, 3)  # a window size that was not recorded
    assert cutouts == [] and failures[0][1].startswith("error: AssertionError")


def test_read_windows_stops_when_progress_raises(replay) -> None:
    stand_in = replay()

    def cancel(done: int, total: int) -> None:
        raise KeyError("cancelled by the caller")

    with pytest.raises(KeyError):
        rf.read_windows([EXP] * 40, RA, DEC, HALF, workers=2, progress=cancel)
    with stand_in._lock:
        served = len(stand_in.calls)
    wait_for_idle_workers()
    assert len(stand_in.calls) == served < 40 * 4  # no worker started another request after the cancel


def test_budget_follows_the_callers_deadline_and_can_be_stopped() -> None:
    unlimited = rf._Budget(None)
    assert not unlimited.expired and unlimited.remaining() == rf.NO_LIMIT_S
    unlimited.raise_if_expired()
    unlimited.stop()
    assert unlimited.expired and unlimited.remaining() == 0.0
    with pytest.raises(http.DeadlineExceeded):
        unlimited.raise_if_expired()
    limit = http.Deadline(30.0)
    limited = rf._Budget(limit)
    assert isinstance(limited, http.Deadline) and not limited.expired and 29.0 < limited.remaining() <= 30.0
    limited.stop()
    assert limited.expired and not limit.expired  # the caller's own deadline is never touched
    assert rf._Budget(http.Deadline(0.0)).expired


def test_worker_threads_are_kept_between_calls(replay) -> None:
    replay()
    rf.read_windows([EXP] * 3, RA, DEC, HALF, workers=3)
    pool = rf._pools[3]
    rf.read_windows([EXP] * 3, RA, DEC, HALF, workers=3)
    assert rf._pools[3] is pool and len(pool._threads) <= 3
    rf.read_windows([EXP], RA, DEC, HALF, workers=10_000)
    assert max(rf._pools) <= rf.MAX_WORKERS == 64


def test_read_windows_with_nothing_to_do() -> None:
    assert rf.read_windows([], RA, DEC, HALF) == ([], [])


def test_many_threads_on_one_file_agree(replay) -> None:
    replay()
    cutouts, failures = rf.read_windows([EXP] * 24, RA, DEC, HALF, workers=8)
    assert failures == [] and len(cutouts) == 24
    for cutout in cutouts:
        assert_matches_expected(cutout)


# --------------------------------------------------------------------------- small parts
def test_meta_cache_is_a_bounded_lru() -> None:
    cache = rf._MetaCache(2)
    a, b, c = (rf._FileMeta(total, b"", 0) for total in (1, 2, 3))
    cache.put("a", a)
    cache.put("b", b)
    assert cache.get("a") is a  # touching "a" makes "b" the oldest
    cache.put("c", c)
    assert len(cache) == 2 and cache.get("b") is None and cache.get("a") is a and cache.get("c") is c
    cache.clear()
    assert len(cache) == 0 and cache.get("a") is None


def test_reader_cache_holds_one_entry_per_file(replay) -> None:
    replay()
    rf.read_window(EXP, RA, DEC, HALF)
    rf.read_window(EXP, RA, DEC, HALF)
    assert len(rf._cache) == 1
    rf.clear_cache()
    assert len(rf._cache) == 0


def test_key_version() -> None:
    assert rf.key_version(EXP.key) == "l2b-v27-2026-197"
    assert rf.key_version("qr3/level2/2026W30_1A/l2b-v28-2026-290/1/level2_x.fits") == "l2b-v28-2026-290"
    assert rf.key_version("dr1/level2/elsewhere/level2_x.fits") == ""
