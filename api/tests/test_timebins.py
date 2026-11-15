"""Time bins (Contract v1.0, section 3) on the visit patterns of real SPHEREx fields.

``REAL_VISITS`` holds the real exposure mid-times (header MJD-AVG, rounded to 0.01 day) of three fields read
from the public archive on 14 Nov 2026. Arrays named ``synthetic_`` are made-up times that probe the
thresholds.
"""

from __future__ import annotations

import numpy as np
import pytest

from tombaugh.timebins import assign_time_bins, mjd_to_date

# Hundredths of a day after MJD 60000, sorted.
# fmt: off
REAL_VISITS = {
    "wise0855": [
        80070, 80070, 80070, 80070, 80084, 80084, 80111, 80111, 80111, 80111, 80111, 80111, 80111, 80111,
        80145, 80145, 80145, 80145, 80145, 80145, 80145, 80145, 80151, 80151, 80152, 80152, 80152, 80152,
        80152, 80152, 97972, 97972, 97972, 97972, 97973, 97973, 97973, 97973, 97979, 97979, 97979, 97979,
        97979, 97979, 97979, 97979, 97979, 97979, 97979, 97979, 97986, 97986, 97986, 97986, 98244, 98244,
        98251, 98251, 98251, 98251, 98251, 98251, 98251, 98251, 98271, 98271, 98624, 98624, 98624, 98624,
        98624, 98624, 98625, 98625, 98638, 98638, 98638, 98638, 98678, 98678, 98678, 98678, 98679, 98679,
        98679, 98679, 98685, 98685, 98686, 98686, 98686, 98686, 98692, 98692, 98692, 98692, 98692, 98692,
        98693, 98693, 98719, 98719, 98930, 98930, 98930, 98930, 98930, 98930, 98930, 98930, 98937, 98937,
        98937, 98937, 98937, 98937, 98944, 98944, 98998, 98998, 98998, 98998, 99351, 99351, 99351, 99351,
        99351, 99351, 99351, 99351, 99357, 99357, 99358, 99358, 99358, 99358, 99358, 99358, 99391, 99391,
        102080, 102080, 102108, 102108, 102128, 102128, 102135, 102135, 102182, 102182, 102189, 102189,
        102203, 102203, 102223, 102223, 102237, 102237, 115120, 115120, 115120, 115120, 115120, 115120,
        115276, 115276, 115276, 115276, 115276, 115276, 115344, 115344, 115344, 115344, 115344, 115344,
        115344, 115344, 115609, 115609, 115615, 115615, 115615, 115615, 115649, 115649, 115650, 115650,
        116077, 116077, 116159, 116159, 116159, 116159, 116159, 116159, 116159, 116159, 116166, 116166,
        116233, 116233, 116234, 116234, 116234, 116234, 116240, 116240, 116240, 116240, 116267, 116267,
        116268, 116268, 116322, 116322, 116322, 116322, 116328, 116328, 116329, 116329, 116329, 116329,
        116329, 116329, 116457, 116457, 116464, 116464, 116464, 116464, 116532, 116532, 116559, 116559,
        116559, 116559, 116899, 116899, 116919, 116919, 116953, 116953, 116993, 116993, 117110, 117110,
        117157, 117157, 117218, 117218, 117306, 117306, 117368, 117368, 117429, 117429
    ],
    "barnard": [
        90287, 90287, 90287, 90287, 90287, 90287, 90314, 90314, 90314, 90314, 90585, 90585, 90586, 90586,
        90586, 90864, 90864, 90864, 90864, 90864, 90864, 90864, 90864, 90898, 90898, 91149, 91149, 91149,
        91149, 91149, 91149, 91150, 91150, 91204, 91204, 91204, 91204, 91204, 91204, 91204, 91204, 91271,
        91271, 91272, 91272, 91272, 91272, 91272, 91272, 91421, 91421, 91428, 91428, 91428, 91428, 91428,
        91428, 91428, 91428, 91448, 91448, 91448, 91448, 91543, 91543, 91543, 91543, 91543, 91543, 91544,
        91544, 91666, 91666, 91666, 91666, 91666, 91666, 91666, 91666, 91672, 91672, 91672, 91672, 91673,
        91673, 91673, 91673, 91767, 91767, 91795, 91795, 91795, 91795, 91795, 91795, 91795, 91862, 91862,
        91863, 91863, 91863, 91863, 91863, 91863, 91910, 91910, 92311, 92311, 94859, 94859, 94865, 94865,
        94899, 94899, 94913, 94913, 94927, 94927, 111009, 111009, 111009, 111009, 111010, 111010, 111016,
        111016, 111043, 111043, 111044, 111044, 111044, 111044, 111044, 111044, 111057, 111057, 111057,
        111057, 111057, 111057, 111057, 111057, 111063, 111063, 111064, 111064, 111064, 111064, 111064,
        111064, 111070, 111070, 111077, 111077, 111403, 111403, 111403, 111403, 111404, 111404, 111404,
        111404, 111410, 111410, 111410, 111410, 111410, 111410, 111410, 111410, 111430, 111430, 111431,
        111431, 111668, 111668, 111668, 111668, 111668, 111668, 111669, 111669, 111831, 111831, 111831,
        111831, 111831, 111831, 111831, 111831, 111838, 111838, 111838, 111838, 111838, 111838, 111838,
        111838, 112028, 112028, 112028, 112028, 112055, 112055, 112055, 112055, 112055, 112055, 112055,
        112123, 112123, 112136, 112136, 112137, 112137, 112137, 112137, 112137, 112137, 112265, 112265,
        112266, 112266, 112266, 112266, 112266, 112266, 112489, 112489, 114003, 114003, 116413, 116413,
        116461, 116461, 116488, 116488, 116508, 116508, 126863, 126863, 126903, 126903, 126904, 126904,
        126904, 126904, 126904, 126904, 126985, 126985, 126985, 126985, 127019, 127019, 127019, 127060,
        127060, 127060, 127060, 127060, 127060, 127060, 127060, 127087, 127087, 127087, 127087, 127087,
        127087, 127121, 127121, 127121, 127121, 127121, 127121, 127121, 127121, 127134, 127134, 127134,
        127291, 127291, 127338, 127338, 127338, 127338, 127338, 127338, 127351, 127351, 127352, 127352,
        127352, 127352, 127352, 127352, 127365, 127365, 127365, 127365, 127365, 127365, 127365, 127365,
        127372, 127372, 127372, 127372, 127372, 127372, 127379, 127379, 127379, 127379, 127596, 127596,
        127596, 127596, 127596, 127596, 127617, 127617, 127623, 127623, 127637, 127637, 127637, 127637,
        127637, 127637, 127637, 127637, 127644, 127644, 127725, 127725, 127779, 127779, 127779, 127779,
        127779, 127779, 127780, 127780, 128017, 128017, 128166, 128166, 128166, 128166, 128166, 128166,
        128166, 128166, 128526, 128526, 130319, 130563, 130563
    ],
    "r_dra": [
        81196, 81196, 81196, 81196, 81196, 81569, 82813, 82813, 82813, 83119, 83119, 83214, 83247, 83248,
        83248, 83248, 83248, 83479, 83479, 83554, 83554, 83554, 83554, 83601, 83601, 83601, 83602, 83730,
        83825, 83825, 83826, 83826, 83826, 83826, 83826, 83866, 83866, 83866, 83866, 83867, 83867, 83887,
        83887, 84145, 84145, 84145, 84145, 84865, 84865, 84865, 85157, 85157, 85157, 85157, 85157, 85157,
        85164, 85164, 85164, 85768, 85768, 85769, 85769, 85884, 85891, 85891, 85891, 85891, 86054, 86196,
        86196, 86346, 87073, 87073, 87344, 87345, 87345, 87345, 87345, 87467, 87467, 87487, 87677, 87677,
        87861, 87861, 96562, 96562, 96562, 96562, 96562, 96691, 96697, 96697, 96697, 96704, 96704, 96704,
        96704, 96704, 96704, 96745, 96745, 96745, 96745, 96745, 97295, 97295, 97356, 98429, 98429, 98429,
        98429, 98429, 98483, 98483, 98484, 98484, 98484, 98484, 98748, 98748, 98748, 98749, 98762, 98762,
        99325, 99326, 99326, 99326, 99346, 99346, 99346, 99346, 99536, 99536, 99773, 99774, 99774, 99774,
        99774, 100758, 100758, 100758, 100948, 100948, 100949, 101002, 101003, 101125, 101125, 101988,
        101988, 101988, 102123, 102136, 102136, 102136, 102137, 102137, 102137, 102150, 102150, 102150,
        102150, 102150, 102150, 102150, 102164, 102164, 102164, 102279, 102374, 103522, 103522, 103556,
        103556, 103556, 103556, 103915, 103915, 103915, 103916, 103916, 104119, 104119, 104357, 104357,
        104357, 105341, 105341, 105341, 105341, 115233, 115233, 115233, 115234, 115281, 115281, 115281,
        115464, 115464, 115464, 116625, 116999, 117080, 117080, 117094, 117128, 117128, 117128, 117324,
        117325, 117325, 117325, 117325, 117636, 117637, 117637, 118173, 118173, 118213, 118213, 118214,
        118214, 118214, 118349, 118350, 118350, 119897, 119958, 119958, 119958, 119958, 120386, 120386,
        120386, 120386, 121214, 121214, 121214, 121262, 121262, 121262, 121269, 121269, 121323, 121411,
        121411, 121411, 121425, 121445, 121445, 122749, 122749, 122749, 122749, 122973, 122973, 122973,
        123095, 123095, 123095, 123095, 123237, 123244, 123407, 123407, 123407, 123407, 123590, 123590,
        123624, 123787
    ],
}
# fmt: on


def _real_mjds(name: str) -> np.ndarray:
    return 60000.0 + np.array(REAL_VISITS[name], dtype=np.float64) / 100.0


def _summary(mjds: np.ndarray, bins: np.ndarray) -> list[tuple[str, str, int]]:
    """(first date, last date, number of exposures) of every bin, in id order."""
    return [
        (mjd_to_date(mjds[bins == b].min()), mjd_to_date(mjds[bins == b].max()), int((bins == b).sum()))
        for b in np.unique(bins)
    ]


def _spans(mjds: np.ndarray, bins: np.ndarray) -> list[float]:
    return [float(np.ptp(mjds[bins == b])) for b in np.unique(bins)]


def test_wise0855_has_four_bins():
    mjds = _real_mjds("wise0855")
    bins = assign_time_bins(mjds)
    assert mjds.size == 258
    assert bins.dtype == np.int64 and bins.shape == mjds.shape
    assert _summary(mjds, bins) == [
        ("2025-05-05", "2025-05-06", 30),
        ("2025-10-31", "2025-11-14", 110),
        ("2025-12-11", "2025-12-13", 18),
        ("2026-04-21", "2026-05-14", 100),
    ]
    assert max(_spans(mjds, bins)) < 24.0  # every visit stays whole


def test_barnard_37_day_visit_stays_whole():
    mjds = _real_mjds("barnard")
    bins = assign_time_bins(mjds)
    assert _summary(mjds, bins) == [
        ("2025-08-15", "2025-09-05", 108),
        ("2025-09-30", "2025-10-01", 10),
        ("2026-03-11", "2026-04-10", 113),
        ("2026-05-04", "2026-05-05", 8),
        ("2026-08-16", "2026-09-22", 121),
    ]
    assert _spans(mjds, bins)[4] == pytest.approx(
        37.0, abs=0.01
    )  # longer than 30 days, shorter than 60: one bin


def test_r_dra_continuous_stretches_split_into_bins_of_at_most_30_days():
    mjds = _real_mjds("r_dra")  # near the north ecliptic pole: three long stretches of coverage
    bins = assign_time_bins(mjds)
    assert _summary(mjds, bins) == [
        ("2025-05-16", "2025-06-06", 17),
        ("2025-06-08", "2025-06-25", 42),
        ("2025-07-01", "2025-07-22", 27),
        ("2025-10-17", "2025-11-14", 48),
        ("2025-11-16", "2025-12-14", 39),
        ("2025-12-26", "2026-01-13", 20),
        ("2026-04-22", "2026-05-16", 26),
        ("2026-05-21", "2026-06-12", 19),
        ("2026-06-21", "2026-07-16", 36),
    ]
    assert max(_spans(mjds, bins)) <= 30.0
    # The 88-day stretch from 2025-10-17 to 2026-01-13 is cut into three equal parts of 29.3 days.
    stretch = mjds[(bins >= 3) & (bins <= 5)]
    width = float(np.ptp(stretch)) / 3.0
    assert float(np.ptp(stretch)) == pytest.approx(87.8, abs=0.05) and width <= 30.0
    for part, b in enumerate((3, 4, 5)):
        inside = mjds[bins == b] - stretch.min()
        assert part * width <= inside.min() and inside.max() <= (part + 1) * width


@pytest.mark.parametrize("name", sorted(REAL_VISITS))
def test_bin_ids_follow_the_input_order_and_increase_with_time(name):
    mjds = _real_mjds(name)
    expected = assign_time_bins(mjds)
    assert np.all(np.diff(expected) >= 0) and np.all(
        np.diff(expected) <= 1
    )  # sorted input: ids step by 0 or 1
    assert expected[0] == 0
    shuffle = np.random.default_rng(7).permutation(mjds.size)
    shuffled = assign_time_bins(mjds[shuffle])
    assert np.array_equal(shuffled, expected[shuffle])
    assert np.array_equal(assign_time_bins(list(mjds[::-1])), expected[::-1])


def test_continuous_88_days_splits_into_three_bins_of_at_most_30_days():
    synthetic_mjds = 60900.0 + np.linspace(0.0, 88.0, 353)  # an exposure every 6 hours for 88 days
    bins = assign_time_bins(synthetic_mjds)
    assert sorted(np.unique(bins)) == [0, 1, 2]
    spans = _spans(synthetic_mjds, bins)
    assert max(spans) <= 30.0
    assert min(spans) > 28.0  # equal parts of 88 / 3 = 29.3 days
    assert np.all(np.diff(bins) >= 0)
    edges = [synthetic_mjds[bins == b].min() - 60900.0 for b in (1, 2)]
    assert edges == pytest.approx([88.0 / 3.0, 2.0 * 88.0 / 3.0], abs=0.25)


def test_a_37_day_visit_stays_whole():
    synthetic_mjds = 61000.0 + np.linspace(0.0, 37.0, 80)
    assert np.all(assign_time_bins(synthetic_mjds) == 0)


def test_gap_must_be_longer_than_20_days():
    assert assign_time_bins([61000.0, 61020.0]).tolist() == [0, 0]  # exactly 20 days: same bin
    assert assign_time_bins([61000.0, 61020.01]).tolist() == [0, 1]
    assert assign_time_bins([61020.01, 61000.0]).tolist() == [1, 0]


def test_span_must_exceed_60_days_to_split():
    whole = 61000.0 + np.linspace(0.0, 60.0, 61)
    assert np.all(assign_time_bins(whole) == 0)
    longer = 61000.0 + np.linspace(0.0, 61.0, 123)
    bins = assign_time_bins(longer)
    assert sorted(np.unique(bins)) == [0, 1, 2]  # ceil(61 / 30) = 3 equal parts of 20.3 days
    assert max(_spans(longer, bins)) <= 30.0


def test_long_stretch_next_to_a_normal_visit():
    synthetic_mjds = np.concatenate(
        [60800.0 + np.linspace(0.0, 1.5, 6), 60900.0 + np.linspace(0.0, 100.0, 201)]
    )
    bins = assign_time_bins(synthetic_mjds)
    assert sorted(np.unique(bins)) == [0, 1, 2, 3, 4]  # one visit, then ceil(100 / 30) = 4 parts of 25 days
    assert np.all(bins[:6] == 0)
    assert max(_spans(synthetic_mjds, bins)) <= 30.0


def test_binning_numbers_can_be_tuned():
    synthetic_mjds = np.array([0.0, 4.0, 8.0, 30.0, 34.0]) + 61000.0
    assert assign_time_bins(synthetic_mjds).tolist() == [0, 0, 0, 1, 1]
    assert assign_time_bins(synthetic_mjds, gap_days=3.0).tolist() == [0, 1, 2, 3, 4]
    assert assign_time_bins(synthetic_mjds, gap_days=25.0).tolist() == [0, 0, 0, 0, 0]
    two_parts = assign_time_bins(synthetic_mjds, gap_days=25.0, max_span_days=30.0, sub_span_days=20.0)
    assert two_parts.tolist() == [0, 0, 0, 1, 1]  # 34 days in two parts of 17
    four_parts = assign_time_bins(synthetic_mjds, gap_days=25.0, max_span_days=30.0, sub_span_days=10.0)
    assert four_parts.tolist() == [
        0,
        0,
        0,
        1,
        1,
    ]  # four parts of 8.5 days, two of them empty: ids stay consecutive


def test_edge_cases():
    assert assign_time_bins([]).shape == (0,)
    assert assign_time_bins([61000.5]).tolist() == [0]
    assert assign_time_bins([61000.5, 61000.5, 61000.5]).tolist() == [0, 0, 0]
    with pytest.raises(ValueError):
        assign_time_bins([61000.0, float("nan")])
    with pytest.raises(ValueError):
        assign_time_bins([61000.0], gap_days=0.0)


def test_mjd_to_date_matches_the_contract_examples():
    assert mjd_to_date(60979.72) == "2025-10-31"
    assert mjd_to_date(60993.91) == "2025-11-14"
    assert mjd_to_date(61174.29) == "2026-05-14"
    assert mjd_to_date(61318.0) == "2026-10-05"
    assert mjd_to_date(51544.0) == "2000-01-01"
    assert mjd_to_date(51543.99999) == "1999-12-31"
