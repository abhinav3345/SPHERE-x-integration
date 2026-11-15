"""tombaugh.discovery on a recorded real SIA answer (tests/data/reader/sia_excerpt.csv). No network."""

from __future__ import annotations

import csv
import io
import json
import re
import threading
import time
from pathlib import Path

import pytest

from tombaugh import discovery, http
from tombaugh.types import Exposure

EXCERPT = (Path(__file__).parent / "data" / "reader" / "sia_excerpt.csv").read_text(encoding="utf-8")
HEADER, *ROWS = EXCERPT.splitlines()
RA, DEC = 133.7599, -7.2418


class FakeResponse:
    def __init__(self, text: str, status: int = 200) -> None:
        self.content = text.encode("utf-8")
        self.status_code = status


def table(*rows: str) -> str:
    return "\n".join([HEADER, *rows]) + "\n"


# --------------------------------------------------------------------------- the CSV quirk
def test_the_recording_really_has_unquoted_json() -> None:
    """A plain CSV parser splits the cloud_access cell: every data row gets two cells too many."""
    parsed = list(csv.reader(io.StringIO(EXCERPT)))
    assert len(ROWS) == 8
    assert all(len(row) == len(parsed[0]) + 2 for row in parsed[1:])
    assert all(',{"aws": {"bucket_name": "nasa-irsa-spherex", "key":"' in row for row in ROWS)


def test_every_recorded_row_becomes_an_exposure() -> None:
    exposures, dropped = discovery.parse_sia_csv_counted(EXCERPT, "spherex_dr1")
    assert len(exposures) == 8 and dropped == {}
    assert exposures == discovery.parse_sia_csv(EXCERPT, "spherex_dr1")
    by_uid = {exposure.uid: exposure for exposure in exposures}
    assert len(by_uid) == 8
    for row in ROWS:  # check each exposure against the raw text of its row, cut up by hand
        cloud = json.loads(row[row.index('{"aws"') : row.rindex("}") + 1])["aws"]
        before = dict(zip(HEADER.split(","), row[: row.index(',{"aws"')].split(","), strict=False))
        obs_id, band = before["obs_id"], before["energy_bandpassname"]
        t_min, t_max = float(before["t_min"]), float(before["t_max"])
        exposure = by_uid[f"{obs_id}/D{band[-1]}"]
        assert exposure.det == int(band[-1]) and band == f"SPHEREx-D{exposure.det}"
        assert exposure.mjd == pytest.approx(0.5 * (t_min + t_max), abs=1e-9) and t_min < exposure.mjd < t_max
        assert (exposure.bucket, exposure.region, exposure.key) == (
            "nasa-irsa-spherex",
            "us-east-1",
            cloud["key"],
        )
        assert exposure.collection == "spherex_dr1"
        assert exposure.s_region.startswith("POLYGON ICRS ") and exposure.s_region in row
        assert exposure.url == f"https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/{cloud['key']}"
        assert http.check_url(exposure.url) == "nasa-irsa-spherex.s3.us-east-1.amazonaws.com"


def test_first_recorded_exposure_field_by_field() -> None:
    first = discovery.parse_sia_csv(EXCERPT, "spherex_dr1")[0]
    assert first.obs_id == "2025W19_1B_0116_1" and first.det == 3 and first.uid == "2025W19_1B_0116_1/D3"
    assert first.mjd == pytest.approx((60800.700028 + 60800.701361) / 2, abs=1e-9)
    assert (
        first.key
        == "dr1/level2/2025W19_1B/l2b-v27-2026-197/3/level2_2025W19_1B_0116_1D3_spx_l2b-v27-2026-197.fits"
    )


def test_a_properly_quoted_json_cell_also_parses() -> None:
    """If IRSA ever starts quoting the cell as CSV demands, the same rows must come out."""
    quoted = [
        re.sub(r"(?<=,)(\{.*\})(?=,)", lambda m: '"' + m.group(1).replace('"', '""') + '"', row)
        for row in ROWS
    ]
    assert all(len(next(csv.reader([row]))) == len(HEADER.split(",")) for row in quoted)
    assert discovery.parse_sia_csv(table(*quoted), "spherex_dr1") == discovery.parse_sia_csv(
        EXCERPT, "spherex_dr1"
    )


def test_json_without_spaces_after_commas_still_parses() -> None:
    compact = [
        row.replace('", "key":"', '","key":"').replace('", "region": "', '","region":"') for row in ROWS
    ]
    assert compact != ROWS
    assert discovery.parse_sia_csv(table(*compact), "spherex_dr1") == discovery.parse_sia_csv(
        EXCERPT, "spherex_dr1"
    )


def test_rows_come_out_sorted_by_time_then_detector() -> None:
    shuffled = table(*reversed(ROWS))
    exposures = discovery.parse_sia_csv(shuffled, "spherex_dr1")
    assert [(e.mjd, e.det) for e in exposures] == sorted((e.mjd, e.det) for e in exposures)
    assert exposures == discovery.parse_sia_csv(EXCERPT, "spherex_dr1")


# --------------------------------------------------------------------------- validation
GOOD = ROWS[0]
GOOD_KEY = "dr1/level2/2025W19_1B/l2b-v27-2026-197/3/level2_2025W19_1B_0116_1D3_spx_l2b-v27-2026-197.fits"


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        ('"bucket_name": "nasa-irsa-spherex"', '"bucket_name": "some-other-bucket"', "wrong_bucket"),
        (
            '"bucket_name": "nasa-irsa-spherex"',
            '"bucket_name": "example.org/x?"',
            "wrong_bucket",
        ),  # foreign host
        (
            '"bucket_name": "nasa-irsa-spherex"',
            '"bucket_name": "nasa-irsa-spherex.example.org"',
            "wrong_bucket",
        ),
        ('"region": "us-east-1"', '"region": "us-east-1.example.org/x?"', "wrong_region"),  # foreign host
        ('"region": "us-east-1"', '"region": "eu-west-1"', "wrong_region"),
        ('"key":"dr1/level2/', '"key":"dr1/level2/../level2/', "bad_key"),
        ('"key":"dr1/level2/2025W19_1B/', '"key":"dr1/level2/../', "bad_key"),
        ('"key":"dr1/', '"key":"/dr1/', "bad_key"),
        ('"key":"dr1/', '"key":"https://example.org/dr1/', "bad_key"),
        ('"key":"dr1/', '"key":"dr9/', "bad_key"),
        ('.fits", "region"', '.fits?versionId=1", "region"', "bad_key"),
        ('.fits", "region"', '.fits\\n", "region"', "bad_key"),
        ("/3/level2_2025W19_1B_0116_1D3_spx", "/4/level2_2025W19_1B_0116_1D3_spx", "detector_mismatch"),
        ("/3/level2_2025W19_1B_0116_1D3_spx", "/3/level2_2025W19_1B_0116_1D4_spx", "detector_mismatch"),
        ('{"aws": {"bucket_name"', '{"gcp": {"bucket_name"', "bad_cloud_access"),
        ('"region": "us-east-1"}}', '"region": "us-east-1"}', "bad_cloud_access"),  # unbalanced JSON
        ('"region": "us-east-1"}},,1', '"region": "us-east-1"}}', "malformed_row"),  # a row cut short
        ("SPHEREx-D3", "SPHEREx-D7", "bad_detector"),
        ("SPHEREx-D3", "WISE-W1", "bad_detector"),
        ("60800.700028,", "not-a-time,", "bad_time"),
        ("60800.700028,", "nan,", "bad_time"),
        (",2025W19_1B_0116_1,", ",2025W19 1B/../x,", "bad_obs_id"),
        (",image/fits,", ",image/png,", "not_science_fits"),
        (",science,2,image,", ",auxiliary,2,image,", "not_science_fits"),
        (",science,2,image,", ",science,2,cube,", "not_science_fits"),
    ],
)
def test_a_row_that_fails_validation_is_dropped_and_counted(old: str, new: str, reason: str) -> None:
    assert GOOD.count(old) >= 1 and GOOD_KEY in GOOD
    bad = GOOD.replace(old, new)
    exposures, dropped = discovery.parse_sia_csv_counted(table(bad, ROWS[1]), "spherex_dr1")
    assert dropped == {reason: 1}
    assert [exposure.uid for exposure in exposures] == [
        discovery.parse_sia_csv(table(ROWS[1]), "spherex_dr1")[0].uid
    ]


def test_only_the_public_bucket_can_ever_be_addressed() -> None:
    """Whatever the listing says, a parsed exposure points at the one allow-listed bucket host."""
    hostile = [
        GOOD.replace('"bucket_name": "nasa-irsa-spherex"', '"bucket_name": "example.org#"'),
        GOOD.replace('"region": "us-east-1"', '"region": "x.example.org/"'),
        GOOD.replace('"key":"dr1/', '"key":"../../other-bucket/dr1/'),
        GOOD.replace(
            "https://irsa.ipac.caltech.edu/ibe/", "https://example.org/ibe/"
        ),  # access_url is never used
    ]
    exposures, dropped = discovery.parse_sia_csv_counted(table(*hostile), "spherex_dr1")
    assert dropped == {"wrong_bucket": 1, "wrong_region": 1, "bad_key": 1}
    assert [urlhost(e.url) for e in exposures] == ["nasa-irsa-spherex.s3.us-east-1.amazonaws.com"]


def urlhost(url: str) -> str:
    return url.split("/")[2]


def test_dropped_rows_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    bad = GOOD.replace('"bucket_name": "nasa-irsa-spherex"', '"bucket_name": "some-other-bucket"')
    with caplog.at_level("WARNING", logger="tombaugh.discovery"):
        assert len(discovery.parse_sia_csv(table(bad, ROWS[1]), "spherex_dr1")) == 1
    assert "dropped 1 row" in caplog.text and "wrong_bucket" in caplog.text


def test_a_table_with_only_its_header_is_a_normal_empty_answer() -> None:
    assert discovery.parse_sia_csv_counted(HEADER + "\n", "spherex_qr3") == ([], {})
    assert discovery.parse_sia_csv(HEADER, "spherex_qr3") == []


@pytest.mark.parametrize(
    "text", ["", "\n\n", "<html><body>503 Service Unavailable</body></html>", "obs_id,t_min\n"]
)
def test_something_that_is_not_an_sia_table_is_an_error(text: str) -> None:
    with pytest.raises(ValueError):
        discovery.parse_sia_csv(text, "spherex_dr1")


# --------------------------------------------------------------------------- merging
def test_duplicates_keep_the_dr1_copy_whatever_the_order() -> None:
    dr1 = discovery.parse_sia_csv(EXCERPT, "spherex_dr1")
    qr3 = discovery.parse_sia_csv(EXCERPT, "spherex_qr3")
    deep = discovery.parse_sia_csv(table(*ROWS[:3]), "spherex_dr1_deep")
    for mixed in (dr1 + qr3 + deep, qr3 + deep + dr1, deep + qr3 + dr1):
        merged = discovery.merge_exposures(mixed)
        assert merged == dr1  # spherex_dr1 is preferred to spherex_dr1_deep, and both to qr3
    only_later = discovery.merge_exposures(qr3 + deep)
    assert [e.collection for e in only_later].count("spherex_dr1_deep") == 3
    assert [e.collection for e in only_later].count("spherex_qr3") == 5
    assert [(e.mjd, e.det) for e in only_later] == [(e.mjd, e.det) for e in dr1]


def test_the_same_pointing_on_another_detector_is_not_a_duplicate() -> None:
    exposures = discovery.parse_sia_csv(EXCERPT, "spherex_dr1")
    first = exposures[0]
    sibling = Exposure(first.obs_id, 6, first.mjd, first.collection, first.bucket, first.region, first.key)
    assert len(discovery.merge_exposures([*exposures, sibling])) == 9


# --------------------------------------------------------------------------- discover()
def install_sia(monkeypatch: pytest.MonkeyPatch, answers: dict[str, str | Exception]) -> list[dict]:
    """Replace http.get with a fake SIA that answers per collection; returns the list of calls made."""
    calls: list[dict] = []
    lock = threading.Lock()
    state = {"in_flight": 0}

    def fake_get(
        url: str, *, params: dict[str, str], deadline: http.Deadline | None = None, **kwargs: object
    ):
        with lock:
            state["in_flight"] += 1
            calls.append(
                {"url": url, "params": dict(params), "deadline": deadline, "in_flight": state["in_flight"]}
            )
        time.sleep(0.01)
        with lock:
            state["in_flight"] -= 1
        answer = answers[params["COLLECTION"]]
        if isinstance(answer, Exception):
            raise answer
        return FakeResponse(answer)

    monkeypatch.setattr(http, "get", fake_get)
    return calls


def test_discover_asks_each_collection_once_and_merges(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_sia(
        monkeypatch,
        {
            "spherex_dr1": table(*ROWS[:6]),
            "spherex_dr1_deep": HEADER + "\n",
            "spherex_qr3": table(*reversed(ROWS[4:])),  # two rows repeat dr1, two are new
            "spherex_qr3_deep": HEADER + "\n",
        },
    )
    deadline = http.Deadline(30.0)
    found = discovery.discover(RA, DEC, deadline=deadline)
    assert sorted(call["params"]["COLLECTION"] for call in calls) == sorted(discovery.COLLECTIONS)
    for call in calls:
        assert call["url"] == discovery.SIA_URL == "https://irsa.ipac.caltech.edu/SIA"
        assert call["params"]["POS"] == "circle 133.759900 -7.241800 0.010000"
        assert call["params"]["RESPONSEFORMAT"] == "csv"
        assert call["deadline"] is deadline
    assert max(call["in_flight"] for call in calls) <= 2
    assert len(found) == 8 and len({e.uid for e in found}) == 8
    assert [(e.mjd, e.det) for e in found] == sorted((e.mjd, e.det) for e in found)
    assert [e.collection for e in found].count("spherex_dr1") == 6
    assert [e.collection for e in found].count("spherex_qr3") == 2


def test_discover_with_no_coverage_returns_an_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_sia(monkeypatch, {name: HEADER + "\n" for name in discovery.COLLECTIONS})
    assert discovery.discover(10.0, 20.0, radius_deg=0.5) == []
    assert {call["params"]["POS"] for call in calls} == {"circle 10.000000 20.000000 0.500000"}
    assert all(call["deadline"] is not None for call in calls)  # a deadline is always in force


def test_discover_raises_when_a_collection_cannot_be_read(monkeypatch: pytest.MonkeyPatch) -> None:
    failure = http.UpstreamError(
        "gave up after 5 attempts: HTTP 503", url=discovery.SIA_URL, status=503, attempts=5
    )
    answers: dict[str, str | Exception] = {name: table(*ROWS) for name in discovery.COLLECTIONS}
    answers["spherex_qr3"] = failure
    install_sia(monkeypatch, answers)
    with pytest.raises(http.UpstreamError) as caught:
        discovery.discover(RA, DEC)
    assert caught.value is failure


def test_discover_treats_a_non_table_answer_as_an_upstream_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    answers: dict[str, str | Exception] = {name: HEADER + "\n" for name in discovery.COLLECTIONS}
    answers["spherex_dr1"] = "<html><body>maintenance</body></html>"
    install_sia(monkeypatch, answers)
    with pytest.raises(http.UpstreamError) as caught:
        discovery.discover(RA, DEC)
    assert caught.value.url == discovery.SIA_URL and caught.value.status == 200


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ra": float("nan"), "dec": 0.0},
        {"ra": 361.0, "dec": 0.0},
        {"ra": -1.0, "dec": 0.0},
        {"ra": 10.0, "dec": 91.0},
        {"ra": 10.0, "dec": 0.0, "radius_deg": 0.0},
        {"ra": 10.0, "dec": 0.0, "radius_deg": 50.0},
        {"ra": 10.0, "dec": 0.0, "collections": ("spherex_dr1&x=1",)},
    ],
)
def test_discover_refuses_requests_that_must_not_go_upstream(
    monkeypatch: pytest.MonkeyPatch, kwargs: dict
) -> None:
    calls = install_sia(monkeypatch, {name: HEADER + "\n" for name in discovery.COLLECTIONS})
    with pytest.raises(ValueError):
        discovery.discover(**kwargs)
    assert calls == []


def test_collections_are_the_four_searchable_ones() -> None:
    assert discovery.COLLECTIONS == ("spherex_dr1", "spherex_dr1_deep", "spherex_qr3", "spherex_qr3_deep")
