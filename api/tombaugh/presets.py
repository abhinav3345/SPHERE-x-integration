"""Wavelength bins and display presets (Contract v1.0, section 4).

``tombaugh/data/presets.json`` is a byte-identical runtime copy of ``docs/contract/presets.json`` (a test
asserts it). No preset is defined anywhere else. Each of the six detectors is cut into four equal wavelength
sub-bins, giving 24 wave bins with ``id = (detector - 1) * 4 + sub``, ``sub`` running 0..3 from blue to red.
All wavelengths are in micron.
"""

from __future__ import annotations

import json
import math
from bisect import bisect_right
from functools import lru_cache
from pathlib import Path

from tombaugh.models import WaveBin

PRESETS_PATH = Path(__file__).resolve().parent / "data" / "presets.json"
N_DETECTORS = 6
_EDGE_DECIMALS = (
    6  # bin edges are exact to 5 decimals; rounding removes binary noise such as 0.8370000000000001
)


@lru_cache(maxsize=1)
def _document() -> dict:
    return json.loads(PRESETS_PATH.read_text(encoding="utf-8"))


def load_presets() -> dict:
    """The parsed presets document (a fresh copy, safe to modify)."""
    return json.loads(json.dumps(_document()))


def sub_bins_per_detector() -> int:
    """Number of wavelength sub-bins per detector (4 in Contract v1.0)."""
    return int(_document()["sub_bins_per_detector"])


def detector_ranges() -> dict[int, tuple[float, float]]:
    """Wavelength range (lam_min, lam_max) in micron of each detector, keyed by detector number 1..6."""
    return {int(d["det"]): (float(d["lam_min"]), float(d["lam_max"])) for d in _document()["detectors"]}


@lru_cache(maxsize=1)
def _edges() -> dict[int, tuple[float, ...]]:
    """Sub-bin edges per detector: ``sub_bins + 1`` increasing wavelengths in micron."""
    n_sub = sub_bins_per_detector()
    edges: dict[int, tuple[float, ...]] = {}
    for det, (lo, hi) in detector_ranges().items():
        inner = [round(lo + (hi - lo) * i / n_sub, _EDGE_DECIMALS) for i in range(1, n_sub)]
        edges[det] = (lo, *inner, hi)
    return edges


@lru_cache(maxsize=1)
def _wave_bins() -> tuple[WaveBin, ...]:
    n_sub = sub_bins_per_detector()
    bins: list[WaveBin] = []
    for det in sorted(_edges()):
        edges = _edges()[det]
        for sub in range(n_sub):
            bins.append(
                WaveBin(id=(det - 1) * n_sub + sub, detector=det, lam_min=edges[sub], lam_max=edges[sub + 1])
            )
    return tuple(bins)


def wave_bins() -> list[WaveBin]:
    """The 24 wave bins in id order (fresh copies)."""
    return [b.model_copy() for b in _wave_bins()]


def wave_bin_for(det: int, lam_um: float) -> int:
    """Wave-bin id of an exposure of detector ``det`` (1..6) with wavelength ``lam_um`` at the field centre.

    A bin holds ``lam_min <= lam < lam_max``. Wavelengths outside the detector's nominal range are clamped
    into its first or last bin: detector ranges overlap, so the detector decides, never the wavelength alone.
    """
    edges = _edges().get(int(det)) if float(det).is_integer() else None
    if edges is None:
        raise ValueError(f"unknown detector {det!r}; expected 1..{N_DETECTORS}")
    lam = float(lam_um)
    if math.isnan(lam):
        raise ValueError("wavelength is NaN")
    n_sub = len(edges) - 1
    sub = min(bisect_right(edges[1:-1], lam), n_sub - 1)
    return (int(det) - 1) * n_sub + sub


def preset_ids() -> list[str]:
    """Preset ids in the order of presets.json."""
    return [p["id"] for p in _document()["presets"]]


def _select(spec: dict) -> list[int]:
    """Wave-bin ids chosen by a selector: a ``detectors`` list and/or a ``lam_min``..``lam_max`` range.

    A wavelength range selects a bin when the bin's centre lies inside it (limits included). When both
    kinds of selector are given a bin must satisfy both.
    """
    if "detectors" not in spec and "lam_min" not in spec and "lam_max" not in spec:
        raise ValueError(f"preset selector has neither detectors nor a wavelength range: {spec!r}")
    detectors = {int(d) for d in spec["detectors"]} if "detectors" in spec else None
    lam_min = float(spec.get("lam_min", -math.inf))
    lam_max = float(spec.get("lam_max", math.inf))
    chosen: list[int] = []
    for b in _wave_bins():
        centre = 0.5 * (b.lam_min + b.lam_max)
        if detectors is not None and b.detector not in detectors:
            continue
        if lam_min <= centre <= lam_max:
            chosen.append(b.id)
    return chosen


def preset_wave_bins(preset_id: str) -> list[int] | dict[str, list[int]]:
    """Wave bins of a preset: a list of ids for a mono preset, a dict of lists with keys r, g, b for rgb.

    Raises ``KeyError`` for an unknown preset id.
    """
    for preset in _document()["presets"]:
        if preset["id"] == preset_id:
            if preset["kind"] == "rgb":
                return {channel: _select(preset[channel]) for channel in ("r", "g", "b")}
            return _select(preset)
    raise KeyError(f"unknown preset {preset_id!r}")
