"""Time bins: the frames of the blink (Contract v1.0, section 3).

1. Sort exposures by mid-time and start a new bin at every gap longer than ``gap_days``.
2. Split any bin spanning more than ``max_span_days`` into equal parts no longer than ``sub_span_days``.

A normal visit lasts 2-6 weeks and its detectors cross the target on different days, so a visit stays whole.
All times are MJD (UTC) in days.
"""

from __future__ import annotations

import datetime as _dt
import math

import numpy as np

GAP_DAYS = 20.0
MAX_SPAN_DAYS = 60.0
SUB_SPAN_DAYS = 30.0
_MJD_EPOCH = _dt.date(1858, 11, 17)  # MJD 0


def assign_time_bins(
    mjds,
    *,
    gap_days: float = GAP_DAYS,
    max_span_days: float = MAX_SPAN_DAYS,
    sub_span_days: float = SUB_SPAN_DAYS,
) -> np.ndarray:
    """Time-bin id of every exposure, in the input order.

    ``mjds`` are exposure mid-times in MJD days (any order). Ids start at 0, are consecutive and increase
    with time. Returns an int64 array with the shape of the flattened input.
    """
    times = np.asarray(mjds, dtype=np.float64).ravel()
    if not (gap_days > 0.0 and max_span_days > 0.0 and sub_span_days > 0.0):
        raise ValueError("gap_days, max_span_days and sub_span_days must be positive")
    if times.size == 0:
        return np.zeros(0, dtype=np.int64)
    if not np.all(np.isfinite(times)):
        raise ValueError("every MJD must be finite")

    order = np.argsort(times, kind="stable")
    ordered = times[order]
    visit = np.concatenate(([0], np.cumsum(np.diff(ordered) > gap_days)))  # step 1: split at long gaps

    label = np.zeros(ordered.size, dtype=np.int64)
    next_label = 0
    for v in range(int(visit[-1]) + 1):
        members = np.flatnonzero(visit == v)
        start = ordered[members[0]]
        span = ordered[members[-1]] - start
        parts = 1
        if span > max_span_days:  # step 2: equal parts no longer than sub_span_days
            parts = max(1, math.ceil(span / sub_span_days))
        if parts > 1:
            width = span / parts
            part = np.minimum(np.floor((ordered[members] - start) / width).astype(np.int64), parts - 1)
        else:
            part = np.zeros(members.size, dtype=np.int64)
        label[members] = next_label + part
        next_label += parts

    # Renumber so ids are consecutive even if a part holds no exposure.
    _, compact = np.unique(label, return_inverse=True)
    bins = np.empty(times.size, dtype=np.int64)
    bins[order] = compact.astype(np.int64)
    return bins


def mjd_to_date(mjd: float) -> str:
    """ISO 8601 calendar date (``YYYY-MM-DD``, UTC) of an MJD in days."""
    if not math.isfinite(mjd):
        raise ValueError("mjd must be finite")
    return (_MJD_EPOCH + _dt.timedelta(days=math.floor(mjd))).isoformat()
