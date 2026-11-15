"""Wavelength bins and presets (Contract v1.0, section 4)."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest

from tombaugh import presets
from tombaugh.models import WaveBin
from tombaugh.presets import (
    detector_ranges,
    load_presets,
    preset_ids,
    preset_wave_bins,
    sub_bins_per_detector,
    wave_bin_for,
    wave_bins,
)

CONTRACT_PRESETS = Path(__file__).resolve().parents[2] / "docs" / "contract" / "presets.json"


def test_runtime_copy_is_byte_identical_to_the_contract_file():
    assert presets.PRESETS_PATH.name == "presets.json"
    assert presets.PRESETS_PATH.read_bytes() == CONTRACT_PRESETS.read_bytes()


def test_detector_ranges_match_the_contract_table():
    assert sub_bins_per_detector() == 4
    assert detector_ranges() == {
        1: (0.744, 1.116),
        2: (1.099, 1.651),
        3: (1.636, 2.421),
        4: (2.423, 3.822),
        5: (3.809, 4.42),
        6: (4.412, 5.002),
    }


def test_there_are_24_wave_bins_with_contract_ids():
    bins = wave_bins()
    assert len(bins) == 24
    assert all(isinstance(b, WaveBin) for b in bins)
    assert [b.id for b in bins] == list(range(24))
    for b in bins:
        sub = b.id % 4
        assert b.id == (b.detector - 1) * 4 + sub
        assert 1 <= b.detector <= 6
        assert b.lam_min < b.lam_max


def test_sub_bins_are_equal_width_and_tile_each_detector():
    bins = wave_bins()
    for det, (lo, hi) in detector_ranges().items():
        four = [b for b in bins if b.detector == det]
        assert len(four) == 4
        assert four[0].lam_min == lo and four[3].lam_max == hi
        for left, right in pairwise(four):
            assert left.lam_max == right.lam_min  # no gap and no overlap inside a detector
        for b in four:
            assert b.lam_max - b.lam_min == pytest.approx((hi - lo) / 4.0, abs=1e-9)


def test_bins_quoted_in_the_contract():
    bins = wave_bins()
    assert bins[0].model_dump() == {"id": 0, "detector": 1, "lam_min": 0.744, "lam_max": 0.837}
    assert (bins[20].detector, bins[20].lam_min, bins[20].lam_max) == (6, 4.412, 4.5595)
    assert (bins[23].lam_min, bins[23].lam_max) == (4.8545, 5.002)


def test_wave_bins_returns_fresh_copies():
    first = wave_bins()
    first[0].lam_min = 99.0
    first.pop()
    assert wave_bins()[0].lam_min == 0.744 and len(wave_bins()) == 24


def test_wave_bin_for_every_bin_centre_and_edge():
    for b in wave_bins():
        assert wave_bin_for(b.detector, 0.5 * (b.lam_min + b.lam_max)) == b.id
        assert wave_bin_for(b.detector, b.lam_min) == b.id  # lam_min belongs to the bin
        assert wave_bin_for(b.detector, b.lam_max - 1e-9) == b.id
    assert wave_bin_for(6, 4.49) == 20  # the plane of the contract example


def test_wave_bin_for_clamps_into_the_detector():
    assert wave_bin_for(1, 0.2) == 0
    assert wave_bin_for(1, 0.744) == 0
    assert wave_bin_for(1, 1.116) == 3  # the top edge stays in the last bin
    assert wave_bin_for(1, 3.0) == 3
    assert wave_bin_for(6, 4.0) == 20
    assert wave_bin_for(6, 5.002) == 23
    assert wave_bin_for(6, 9.9) == 23
    assert wave_bin_for(4, float("inf")) == 15
    assert wave_bin_for(4, float("-inf")) == 12


def test_overlapping_detectors_are_told_apart_by_the_detector():
    assert wave_bin_for(1, 1.105) == 3
    assert wave_bin_for(2, 1.105) == 4
    assert wave_bin_for(5, 4.415) == 19
    assert wave_bin_for(6, 4.415) == 20


def test_wave_bin_for_rejects_bad_input():
    for bad_det in (0, 7, -1, 2.5):
        with pytest.raises(ValueError):
            wave_bin_for(bad_det, 1.2)
    with pytest.raises(ValueError):
        wave_bin_for(3, float("nan"))


def test_mono_presets():
    assert preset_ids() == ["all", "d1", "d2", "d3", "d4", "d5", "d6", "cold", "rgb"]
    assert preset_wave_bins("all") == list(range(24))
    for det in range(1, 7):
        assert preset_wave_bins(f"d{det}") == [(det - 1) * 4 + sub for sub in range(4)]


def test_cold_preset_selects_bins_whose_centre_is_inside_4_to_5_micron():
    cold = preset_wave_bins("cold")
    assert cold == [17, 18, 19, 20, 21, 22, 23]
    bins = {b.id: b for b in wave_bins()}
    for bin_id, b in bins.items():
        centre = 0.5 * (b.lam_min + b.lam_max)
        assert (bin_id in cold) == (4.0 <= centre <= 5.002)
    assert bins[16].lam_max > 3.9 and 16 not in cold  # reaches past 3.96 um but its centre is at 3.885


def test_rgb_preset_has_three_channels_that_partition_the_bins():
    rgb = preset_wave_bins("rgb")
    assert isinstance(rgb, dict) and list(rgb) == ["r", "g", "b"]
    assert rgb["r"] == list(range(16, 24))
    assert rgb["g"] == list(range(8, 16))
    assert rgb["b"] == list(range(8))
    assert sorted(rgb["r"] + rgb["g"] + rgb["b"]) == list(range(24))


def test_unknown_preset_raises_key_error():
    with pytest.raises(KeyError):
        preset_wave_bins("w3")


def test_every_preset_and_legacy_pair_resolves():
    document = load_presets()
    assert document["contract"] == "1.0"
    assert document["weighting"] == {"default": "uniform", "options": ["uniform", "ivar"]}
    for preset in document["presets"]:
        chosen = preset_wave_bins(preset["id"])
        flat = chosen if isinstance(chosen, list) else [i for ids in chosen.values() for i in ids]
        assert flat and all(0 <= i < 24 for i in flat)
    for pair in document["legacy_pairs"]:
        assert isinstance(preset_wave_bins(pair["spherex_preset"]), list)


def test_load_presets_returns_a_copy():
    document = load_presets()
    document["presets"].clear()
    assert len(load_presets()["presets"]) == 9
