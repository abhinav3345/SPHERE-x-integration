"""The pydantic models against the JSON examples written in docs/CONTRACT_FIELDS.md (sections 5 and 7)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from tombaugh import models
from tombaugh.grid import Grid
from tombaugh.models import (
    BuildingResponse,
    CatwiseSource,
    ErrorResponse,
    ExposuresInfo,
    FixtureStar,
    GaiaSource,
    GridModel,
    Manifest,
    Mover,
    OverlaysResponse,
    Plane,
    Progress,
    ResolveResponse,
    SpectrumResponse,
    StatusResponse,
    TimeBinning,
    TrackPoint,
    export_schema,
)

CONTRACT_MD = (Path(__file__).resolve().parents[2] / "docs" / "CONTRACT_FIELDS.md").read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    """Remove ``// ...`` and ``/* ... */`` comments that are outside string literals."""
    out: list[str] = []
    i, in_string = 0, False
    while i < len(text):
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\":
                out.append(text[i + 1])
                i += 1
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
            out.append(ch)
        elif text.startswith("//", i):
            i = text.find("\n", i)
            if i < 0:
                break
            continue
        elif text.startswith("/*", i):
            i = text.index("*/", i) + 2
            continue
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _section(number: int) -> str:
    """Text of one top-level section (``## N. ...`` up to the next ``## ``)."""
    match = re.search(rf"^## {number}\. .*?(?=^## \d+\. |\Z)", CONTRACT_MD, flags=re.DOTALL | re.MULTILINE)
    assert match, f"section {number} not found in the contract"
    return match.group(0)


def _json_examples() -> list[dict]:
    """Every fenced json / jsonc example of sections 5 and 7, comments and ellipses removed."""
    found = []
    for number in (5, 7):
        for block in re.findall(r"```jsonc?\n(.*?)```", _section(number), flags=re.DOTALL):
            found.append(json.loads(_strip_comments(block)))
    return found


EXAMPLES = _json_examples()


def _example(key: str) -> dict:
    matches = [e for e in EXAMPLES if key in e]
    assert len(matches) == 1, f"expected one contract example with key {key!r}, found {len(matches)}"
    return matches[0]


EXAMPLE_MODELS = [
    pytest.param("grid", Manifest, id="manifest"),
    pytest.param("progress", BuildingResponse, id="building"),
    pytest.param("points", SpectrumResponse, id="spectrum"),
    pytest.param("query", ResolveResponse, id="resolve"),
    pytest.param("gaia", OverlaysResponse, id="overlays"),
    pytest.param("pipeline_version", StatusResponse, id="status"),
]


def test_the_contract_holds_the_six_examples():
    assert len(EXAMPLES) == 6
    assert _strip_comments('{"url": "http://x//y", "a": 1} // gone') == '{"url": "http://x//y", "a": 1} '
    assert _strip_comments("[1 /* … 24 */, 2]") == "[1 , 2]"


@pytest.mark.parametrize("key, model", EXAMPLE_MODELS)
def test_contract_example_validates_and_serialises_back_exactly(key, model):
    example = _example(key)
    parsed = model.model_validate(example)
    assert parsed.model_dump(mode="json") == example  # same keys, same nulls, same values
    assert json.loads(parsed.model_dump_json()) == example
    assert list(parsed.model_dump(mode="json")) == list(example)  # top-level keys in the contract's order


@pytest.mark.parametrize("key, model", EXAMPLE_MODELS)
def test_contract_example_survives_unknown_keys(key, model):
    example = dict(_example(key), future_field={"added": "in 1.1"})
    assert model.model_validate(example).model_dump(mode="json") == _example(key)


def _sci_plane(**changes) -> dict:
    plane = dict(_example("grid")["planes"][0])
    plane.update(changes)
    return plane


def test_sci_plane_has_band_null_and_no_scaled_key():
    dumped = Plane.model_validate(_sci_plane()).model_dump(mode="json")
    assert dumped["band"] is None and "band" in dumped
    assert "scaled" not in dumped
    assert dumped["offset"] == 0 and dumped["kind"] == "sci" and dumped["mission"] == "SPHEREx"


def test_legacy_plane_shape():
    legacy = Plane(
        index=72,
        kind="legacy",
        mission="AllWISE",
        time_bin=None,
        wave_bin=None,
        band="W2",
        lam_min=4.0,
        lam_max=5.3,
        lam_eff=4.6,
        n_exposures=1,
        sigma=0.01,
        mjd_mid=55400.0,
        date_start="2010-05-10",
        date_end="2010-11-12",
        offset=72 * 119 * 119 * 2,
        scaled="field_stars",
    )
    dumped = legacy.model_dump(mode="json")
    assert dumped["time_bin"] is None and dumped["wave_bin"] is None
    assert dumped["band"] == "W2" and dumped["scaled"] == "field_stars"
    assert Plane.model_validate(dumped) == legacy


@pytest.mark.parametrize(
    "changes",
    [
        {"time_bin": None},
        {"wave_bin": None},
        {"band": "W1"},
        {"scaled": "field_stars"},
        {"mission": "2MASS"},
        {"kind": "legacy"},
        {"kind": "legacy", "mission": "AllWISE", "time_bin": None, "wave_bin": None},  # no band
        {"kind": "legacy", "mission": "AllWISE", "band": "W1", "wave_bin": None},  # still has a time bin
        {"kind": "raw"},
        {"sigma": float("nan")},
        {"lam_eff": float("inf")},
    ],
)
def test_inconsistent_planes_are_refused(changes):
    with pytest.raises(ValidationError):
        Plane.model_validate(_sci_plane(**changes))


def test_empty_manifest_has_no_planes_and_frames_null():
    example = _example("grid")
    empty = dict(
        example,
        status="empty",
        time_bins=[],
        planes=[],
        frames=None,
        exposures={
            "found": 0,
            "used": 0,
            "sampled": False,
            "collections": {},
            "newest_mjd": None,
            "newest_date": None,
        },
    )
    dumped = Manifest.model_validate(empty).model_dump(mode="json")
    assert dumped["frames"] is None and "frames" in dumped
    assert dumped["planes"] == [] and dumped["status"] == "empty"
    assert dumped["exposures"]["newest_mjd"] is None and dumped["exposures"]["newest_date"] is None
    assert "fixture_stars" not in dumped
    with pytest.raises(ValidationError):
        Manifest.model_validate(dict(example, status="empty"))  # planes and frames present
    with pytest.raises(ValidationError):
        Manifest.model_validate(dict(example, frames=None))  # planes without frames


def test_fixture_stars_appear_only_in_fixture_manifests():
    example = _example("grid")
    assert "fixture_stars" not in Manifest.model_validate(example).model_dump(mode="json")
    stars = [{"source_id": "4472832130942575872", "ra": 269.4462, "dec": 4.7672, "x": 59.0, "y": 59.0}]
    fixture = Manifest.model_validate(dict(example, fixture_stars=stars))
    dumped = fixture.model_dump(mode="json")
    assert dumped["fixture_stars"] == stars
    assert list(dumped)[-1] == "fixture_stars"
    assert isinstance(fixture.fixture_stars[0], FixtureStar)
    assert isinstance(fixture.fixture_stars[0].source_id, str)  # 19 digits do not fit a JavaScript number


def test_manifest_defaults_follow_the_contract():
    example = _example("grid")
    minimal = {
        k: v for k, v in example.items() if k not in ("contract", "epoch_ref", "time_binning", "warnings")
    }
    manifest = Manifest.model_validate(minimal)
    assert manifest.contract == "1.0" and manifest.epoch_ref == 2026.0 and manifest.warnings == []
    assert manifest.time_binning.model_dump(mode="json") == {
        "gap_days": 20,
        "max_span_days": 60,
        "sub_span_days": 30,
    }
    assert manifest.model_dump(mode="json") == example
    assert TimeBinning(gap_days=12.5).model_dump(mode="json")["gap_days"] == 12.5


def test_grid_model_from_grid():
    grid = Grid.for_field(133.7599, -7.2418, 6)
    assert GridModel.from_grid(grid).model_dump(mode="json") == _example("grid")["grid"]
    with pytest.raises(ValidationError):
        GridModel(nx=119, ny=119, cx=59, cy=59, projection="SIN")


def test_exposures_info_requires_the_newest_fields():
    with pytest.raises(ValidationError):
        ExposuresInfo(found=1, used=1, sampled=False, collections={"spherex_dr1": 1})


def test_building_response():
    building = BuildingResponse(progress=Progress(stage="fetch", done=120, total=258))
    assert building.model_dump(mode="json") == _example("progress")
    for stage in ("discover", "fetch", "stack"):
        assert Progress(stage=stage, done=0, total=1).stage == stage
    with pytest.raises(ValidationError):
        Progress(stage="upload", done=0, total=1)


def test_error_codes_of_the_contract_table():
    rows = re.findall(r"^\| (\d{3}) \| `(\w+)` \|", _section(7), flags=re.MULTILINE)
    assert {code: int(http) for http, code in rows} == {
        "bad_request": 400,
        "not_found": 404,
        "busy": 429,
        "upstream_unavailable": 503,
        "internal": 500,
    }
    for _, code in rows:
        body = ErrorResponse(code=code, message="why").model_dump(mode="json")
        assert body == {"contract": "1.0", "status": "error", "code": code, "message": "why"}
    with pytest.raises(ValidationError):
        ErrorResponse(code="teapot", message="no")


def test_spectrum_states_and_nullable_target_fields():
    example = _example("points")
    for state in ("ok", "indicative", "saturated", "contaminated", "no_data"):
        assert SpectrumResponse.model_validate(dict(example, state=state)).state == state
    with pytest.raises(ValidationError):
        SpectrumResponse.model_validate(dict(example, state="fine"))
    bare_target = {"ra": 10.0, "dec": -5.0}
    nothing = SpectrumResponse.model_validate(
        dict(
            example, state="no_data", target=bare_target, neighbours=[], time_span=None, points=[], binned=[]
        )
    ).model_dump(mode="json")
    assert nothing["target"] == {
        "ra": 10.0,
        "dec": -5.0,
        "snapped_to": None,
        "pmra": None,
        "pmdec": None,
        "parallax": None,
        "epoch": None,
    }
    assert nothing["time_span"] is None and nothing["points"] == [] and nothing["binned"] == []
    for quality in ("good", "flagged", "saturated"):
        point = dict(example["points"][0], quality=quality)
        assert SpectrumResponse.model_validate(dict(example, points=[point])).points[0].quality == quality
    for kind in ("aperture", "joint_psf"):
        method = dict(example["method"], kind=kind)
        assert SpectrumResponse.model_validate(dict(example, method=method)).method.kind == kind


def test_resolve_not_found_and_solar_system_carry_only_what_is_set():
    assert ResolveResponse(status="not_found", query="zzz").model_dump(mode="json") == {
        "contract": "1.0",
        "status": "not_found",
        "query": "zzz",
    }
    comet = ResolveResponse(
        status="solar_system", query="3I/ATLAS", message="Solar-system objects move too fast."
    )
    assert comet.model_dump(mode="json") == {
        "contract": "1.0",
        "status": "solar_system",
        "query": "3I/ATLAS",
        "message": "Solar-system objects move too fast.",
    }
    with pytest.raises(ValidationError):
        ResolveResponse(status="ok", query="no position")


def test_resolve_coordinates_add_movers():
    mover = Mover(
        name="Barnard's Star",
        ra_ref=269.4462,
        dec_ref=4.7672,
        moved_arcsec=269.0,
        pm_arcsec_yr=10.39,
        year_at_position=2000.0,
    )
    typed = ResolveResponse(
        status="ok",
        query="17 57 48.5 +04 41 36",
        ra=269.452083,
        dec=4.693333,
        ra_ref=269.452083,
        dec_ref=4.693333,
        moved_arcsec=0.0,
        source="coordinates",
        movers=[mover],
    )
    dumped = typed.model_dump(mode="json")
    name_example = _example("query")
    assert list(dumped) == [*name_example, "movers"]  # every key of the name example, then movers
    assert dumped["name"] is None and dumped["pmra"] is None and dumped["otype"] is None
    assert dumped["movers"] == [mover.model_dump(mode="json")]
    assert list(dumped["movers"][0]) == [
        "name",
        "ra_ref",
        "dec_ref",
        "moved_arcsec",
        "pm_arcsec_yr",
        "year_at_position",
    ]
    assert "message" not in dumped
    assert "movers" not in ResolveResponse.model_validate(name_example).model_dump(mode="json")


def test_overlay_track_only_for_movers():
    slow = GaiaSource(
        source_id="1", ra=1.0, dec=2.0, epoch=2016.0, pmra=None, pmdec=None, parallax=None, g=None
    )
    dumped = slow.model_dump(mode="json")
    assert "track" not in dumped
    assert dumped["pmra"] is None and dumped["parallax"] is None and dumped["g"] is None
    fast = CatwiseSource(
        id="J085510.74-071442.5",
        ra=133.7948,
        dec=-7.2451,
        epoch=2015.4,
        pmra=-8100.0,
        pmdec=680.0,
        w1=17.8,
        w2=14.0,
        track=[TrackPoint(time_bin=0, ra=133.7599, dec=-7.2418)],
    )
    assert fast.model_dump(mode="json")["track"] == [{"time_bin": 0, "ra": 133.7599, "dec": -7.2418}]
    example = _example("gaia")
    assert "track" in example["gaia"][0] and "track" not in example["catwise"][0]
    for state in ("ok", "stale", "unavailable"):
        upstreams = {"gaia": state, "catwise": "ok"}
        assert OverlaysResponse.model_validate(dict(example, upstreams=upstreams)).upstreams.gaia == state
    with pytest.raises(ValidationError):
        OverlaysResponse.model_validate(dict(example, upstreams={"gaia": "down", "catwise": "ok"}))


def test_status_before_anything_is_known():
    example = _example("pipeline_version")
    cold = dict(
        example,
        newest_exposure=None,
        upstreams={"irsa_sia": {"ok": False, "latency_ms": None, "checked_at": None}},
    )
    dumped = StatusResponse.model_validate(cold).model_dump(mode="json")
    assert dumped["newest_exposure"] is None
    assert dumped["upstreams"] == {"irsa_sia": {"ok": False, "latency_ms": None, "checked_at": None}}


def test_nan_is_refused_everywhere():
    example = _example("points")
    bad_point = dict(example["points"][0], flux_ujy=float("nan"))
    with pytest.raises(ValidationError):
        SpectrumResponse.model_validate(dict(example, points=[bad_point]))
    with pytest.raises(ValidationError):
        FixtureStar(source_id="1", ra=float("inf"), dec=0.0, x=0.0, y=0.0)


def test_section_9_names_are_importable_from_models():
    for name in (
        "Exposure",
        "Cutout",
        "TimeBin",
        "WaveBin",
        "Plane",
        "Manifest",
        "SpectrumResponse",
        "ResolveResponse",
        "OverlaysResponse",
    ):
        assert hasattr(models, name)
    assert set(models.__all__) <= set(dir(models))


def test_schemas_list_omittable_fields_as_optional():
    for mode in ("serialization", "validation"):
        assert "scaled" not in Plane.model_json_schema(mode=mode)["required"]
        assert "track" not in GaiaSource.model_json_schema(mode=mode)["required"]
        assert "track" not in CatwiseSource.model_json_schema(mode=mode)["required"]
        assert "fixture_stars" not in Manifest.model_json_schema(mode=mode)["required"]
    assert set(Plane.model_json_schema(mode="serialization")["required"]) == set(Plane.model_fields) - {
        "scaled"
    }
    # A resolve answer that is not "ok" carries only contract, status and query (plus message).
    assert ResolveResponse.model_json_schema(mode="serialization")["required"] == [
        "contract",
        "status",
        "query",
    ]
    assert "properties" in OverlaysResponse.model_json_schema(mode="serialization")["$defs"]["GaiaSource"]


def test_export_schema_writes_the_manifest_schema(tmp_path):
    target = tmp_path / "manifest.schema.json"
    export_schema(target)
    text = target.read_text(encoding="utf-8")
    assert text.endswith("\n")
    schema = json.loads(text)
    assert schema == models.manifest_schema()
    assert schema["type"] == "object"
    properties = schema["properties"]
    assert list(_example("grid")) == [k for k in Manifest.model_fields if k != "fixture_stars"]
    assert set(properties) == set(Manifest.model_fields)
    assert set(schema["required"]) == set(properties) - {"fixture_stars"}
    plane = schema["$defs"]["Plane"]
    assert set(plane["required"]) == set(plane["properties"]) - {"scaled"}
    assert {"type": "null"} in plane["properties"]["band"]["anyOf"]
    for name in (
        "GridModel",
        "TimeBin",
        "WaveBin",
        "FramesInfo",
        "ExposuresInfo",
        "Provenance",
        "FixtureStar",
    ):
        assert name in schema["$defs"]
        assert schema["$defs"][name]["type"] == "object" and schema["$defs"][name]["properties"]
