"""What GET /api/fields/{key}/spectrum measures (Contract v1.0, section 7.1), before the photometry runs.

* Which source a click means: the click snaps to the nearest Gaia DR3 or CatWISE2020 source of the field's
  overlays (`tombaugh.catalogs`) within `SNAP_RADIUS_ARCSEC`, compared with every position the overlays give
  that source (its track point at each visit when it moves fast, else its catalogue position). The snapped
  source's astrometry follows it through the exposures. An object whose published astrometry the package
  holds (`make_fixture.TARGETS`: WISE 0855 from SIMBAD quoting Kirkpatrick et al. 2021) is preferred to its
  CatWISE entry, whose motion is measurably off (see `choose`). Without a source that close, the click itself
  is measured, at the position rounded to 4 decimals of a degree (0.36"), as field centres are.
* Which neighbours are fitted jointly: the CatWISE sources near the target (the photometry keeps those within
  15" and decides fitted or "contaminated"), except the target itself and CatWISE entries of the same object
  (within `SAME_OBJECT_ARCSEC` of the target at the CatWISE epoch). CatWISE, the infrared catalogue, lists what
  SPHEREx sees at 3-5 micron; Gaia goes far fainter in the optical, and its many faint sources would only
  make the joint fit unstable, so Gaia sources are not passed as neighbours (our choice).
* Motions: a source moves only as the overlays move it. A Gaia source keeps its catalogue proper motion; a
  CatWISE source keeps its motion only when the overlays gave it a track (its motion passed
  `catalogs.catwise_tracks`), because most fast CatWISE motions in our fields are not real (catalogs.py).
* Which exposures: the field's exposure list (stored with a built field, or found again for a recorded field)
  limited to the field's visits, so every point carries a time bin of the manifest.

Units: degrees (ICRS), arcsec, mas/yr, Julian years, MJD days.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass

import numpy as np

from tombaugh import __version__, catalogs, photometry
from tombaugh.grid import NATIVE_PIXSCALE_ARCSEC, Grid, sky_to_pixel, snap
from tombaugh.models import CatwiseSource, GaiaSource, Manifest, OverlaysResponse, SnappedTo, TimeBin
from tombaugh.types import Exposure

# Our choices, not measurements: a click within one native SPHEREx pixel of a catalogue position means that
# source; neighbours are looked for a little beyond the photometry's 15" so that a moving pair is not missed.
SNAP_RADIUS_ARCSEC = NATIVE_PIXSCALE_ARCSEC
NEIGHBOUR_SEARCH_ARCSEC = photometry.NEIGHBOUR_RADIUS_ARCSEC + 5.0
SAME_OBJECT_ARCSEC = catalogs.CATWISE_GAIA_MATCH_ARCSEC  # 3": as catalogs.py matches CatWISE to Gaia
VISIT_SLACK_DAYS = 1.0  # an exposure belongs to a visit when its listed mid-time is this close to the bin
GRID_EDGE_PX = 0.5  # a position is inside the field when it lies within [-0.5, n - 0.5] grid pixels


@dataclass(frozen=True)
class Choice:
    """What one click is measured as: the target, how it was snapped, its neighbours, its cache identity."""

    target: photometry.Source
    snapped_to: SnappedTo | None
    neighbours: tuple[photometry.Source, ...]
    identity: str


def field_grid(manifest: Manifest) -> Grid:
    """The grid of a manifest (`catalogs.field_grid`, so both routes use one definition)."""
    return catalogs.field_grid(manifest)


def inside_field(manifest: Manifest, ra: float, dec: float) -> bool:
    """True when the position lies on the field's grid (pixel centres -0.5 to n - 0.5)."""
    grid = field_grid(manifest)
    x, y = sky_to_pixel(grid, ra, dec)
    if not (math.isfinite(x) and math.isfinite(y)):
        return False
    low, high = -GRID_EDGE_PX, grid.n - 1 + GRID_EDGE_PX
    return low <= x <= high and low <= y <= high


def _separations(ra: float, dec: float, ras: np.ndarray, decs: np.ndarray) -> np.ndarray:
    """Angles from one position to many (degrees in), arcsec; the haversine form."""
    p1, p2 = math.radians(dec), np.radians(decs)
    dp, dl = p2 - p1, np.radians(ras - ra)
    a = np.sin(dp / 2.0) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dl / 2.0) ** 2
    return np.degrees(2.0 * np.arcsin(np.minimum(1.0, np.sqrt(a)))) * 3600.0


def _positions(source: GaiaSource | CatwiseSource) -> list[tuple[float, float]]:
    """Where the overlays put a source: its track points when it has a track, else its catalogue position."""
    if source.track:
        return [(point.ra, point.dec) for point in source.track]
    return [(source.ra, source.dec)]


def _gaia_target(source: GaiaSource) -> photometry.Source:
    return photometry.Source(
        ra=source.ra,
        dec=source.dec,
        epoch=source.epoch,
        pmra=source.pmra,
        pmdec=source.pmdec,
        parallax=source.parallax,
        catalog="gaia",
        id=source.source_id,
    )


def _catwise_source(source: CatwiseSource) -> photometry.Source:
    moves = bool(source.track)  # a CatWISE motion is used only when the overlays trusted it with a track
    return photometry.Source(
        ra=source.ra,
        dec=source.dec,
        epoch=source.epoch,
        pmra=source.pmra if moves else None,
        pmdec=source.pmdec if moves else None,
        catalog="catwise",
        id=source.id,
    )


def _nearest(
    ra: float, dec: float, sources: Sequence[GaiaSource | CatwiseSource]
) -> tuple[int, float] | None:
    """(index, separation in arcsec) of the source nearest the position at any of its positions, or None."""
    best: tuple[int, float] | None = None
    for index, source in enumerate(sources):
        places = np.array(_positions(source), dtype=np.float64)
        separation = float(_separations(ra, dec, places[:, 0], places[:, 1]).min())
        if best is None or separation < best[1]:
            best = (index, separation)
    return best


def _visit_years(time_bins: Sequence[TimeBin]) -> list[float]:
    """Julian years of the middles of the visits; `epoch_ref` when there is none."""
    if not time_bins:
        return [photometry.EPOCH_REF]
    return [photometry.mjd_to_jyear(time_bin.mjd_mid) for time_bin in time_bins]


def published_targets() -> list[photometry.Source]:
    """Objects whose published astrometry the package holds (`catalogs.published_targets`: `make_fixture.TARGETS`
    without the Gaia DR3 ones, whose own Gaia entry is among the overlays; the overlays place their CatWISE
    entry by the same astrometry). The catalogue name is the first word of the source ("simbad" for "SIMBAD,
    quoting Kirkpatrick et al. 2021").
    """
    out: list[photometry.Source] = []
    for target in catalogs.published_targets():
        out.append(
            photometry.Source(
                ra=target.ra,
                dec=target.dec,
                epoch=target.epoch,
                pmra=target.pmra,
                pmdec=target.pmdec,
                parallax=target.parallax,
                catalog=target.source.split(",")[0].split()[0].lower(),
                id=target.label,
            )
        )
    return out


def _nearest_published(
    ra: float, dec: float, years: Sequence[float]
) -> tuple[photometry.Source, float] | None:
    """The published target nearest the position at one of the visits, with that separation (arcsec)."""
    best: tuple[photometry.Source, float] | None = None
    for source in published_targets():
        places = np.array([source.position_at_year(year) for year in years], dtype=np.float64)
        separation = float(_separations(ra, dec, places[:, 0], places[:, 1]).min())
        if best is None or separation < best[1]:
            best = (source, separation)
    return best


def choose(overlays: OverlaysResponse, manifest: Manifest, ra: float, dec: float) -> Choice:
    """The target, snapping and neighbours for a click at (`ra`, `dec`) in a field with these overlays.

    A published target (`published_targets`) within the snap radius wins when it is nearer than the nearest
    catalogue source, and also over a CatWISE source that the overlays move along a track: measured on
    14 Nov 2026 (catalogs.py), CatWISE's motion of WISE 0855 (pmdec 1035.7 mas/yr against 673.2 published)
    puts it 0.9 to 1.1 grid pixels off the source in the 2025-26 frames, the published astrometry 0.2 to 0.24.
    Measured the same evening on all 258 exposures of the field, same code and neighbours: the joint fit gives
    562.0 +- 44.7 microjansky at 4.4-4.8 micron (18 good points) with the published motion, and 335.5 +- 34.3
    (19) with CatWISE's.
    """
    years = _visit_years(manifest.time_bins)
    candidates: list[tuple[str, GaiaSource | CatwiseSource]] = [("gaia", s) for s in overlays.gaia]
    candidates += [("catwise", s) for s in overlays.catwise]
    found = _nearest(ra, dec, [source for _, source in candidates])
    if found is not None and found[1] > SNAP_RADIUS_ARCSEC:
        found = None
    published = _nearest_published(ra, dec, years)
    if published is not None and published[1] > SNAP_RADIUS_ARCSEC:
        published = None
    snapped_to: SnappedTo | None = None
    if published is not None and (
        found is None
        or published[1] <= found[1]
        or (candidates[found[0]][0] == "catwise" and candidates[found[0]][1].track)
    ):
        target = published[0]
        snapped_to = SnappedTo(catalog=target.catalog, id=target.id, sep_arcsec=round(published[1], 2))
        identity = f"{target.catalog}:{target.id}"
    elif found is not None:
        catalog, source = candidates[found[0]]
        if catalog == "gaia":
            target = _gaia_target(source)
            name = source.source_id
        else:
            target = _catwise_source(source)
            name = source.id
        snapped_to = SnappedTo(catalog=catalog, id=name, sep_arcsec=round(found[1], 2))
        identity = f"{catalog}:{name}"
    else:
        ra0, dec0 = snap(ra, dec)
        target = photometry.Source(ra=ra0, dec=dec0)
        identity = f"position:{ra0:.4f},{dec0:.4f}"
    neighbours = tuple(_neighbours(overlays.catwise, target, years))
    return Choice(target=target, snapped_to=snapped_to, neighbours=neighbours, identity=identity)


def _same_object(
    target: photometry.Source,
    source: CatwiseSource,
    places: Sequence[tuple[float, float]],
    at_epoch: tuple[float, float],
) -> bool:
    """True when a CatWISE entry is the target itself (or the target listed again).

    `places` are the target's positions at the visits and `at_epoch` at the CatWISE epoch. Either the entry
    lies within SAME_OBJECT_ARCSEC of the target at the CatWISE epoch, or it is a source the overlays move
    along a track that stays within SNAP_RADIUS_ARCSEC of the target at every visit (a fast mover whose
    CatWISE motion is a little off, as WISE 0855's).
    """
    if target.catalog == "catwise" and source.id == target.id:
        return True
    if float(_separations(*at_epoch, np.array([source.ra]), np.array([source.dec]))[0]) < SAME_OBJECT_ARCSEC:
        return True
    if not source.track or not target.moves:
        return False
    track = {point.time_bin: (point.ra, point.dec) for point in source.track}
    along = [track[i] for i in sorted(track)]
    if len(along) != len(places):
        return False
    return all(
        float(_separations(tra, tdec, np.array([pra]), np.array([pdec]))[0]) <= SNAP_RADIUS_ARCSEC
        for (tra, tdec), (pra, pdec) in zip(places, along, strict=True)
    )


def _neighbours(
    catwise: Sequence[CatwiseSource], target: photometry.Source, years: Sequence[float]
) -> list[photometry.Source]:
    """CatWISE sources within NEIGHBOUR_SEARCH_ARCSEC of the target at a visit, not the target itself."""
    if not catwise:
        return []
    places = [target.position_at_year(year) for year in years]
    at_epoch = target.position_at_year(catalogs.catwise_epoch_jyear())
    out: list[photometry.Source] = []
    for source in catwise:
        if _same_object(target, source, places, at_epoch):
            continue
        neighbour = _catwise_source(source)
        for year, (tra, tdec) in zip(years, places, strict=True):
            nra, ndec = neighbour.position_at_year(year)
            if (
                float(_separations(tra, tdec, np.array([nra]), np.array([ndec]))[0])
                <= NEIGHBOUR_SEARCH_ARCSEC
            ):
                out.append(neighbour)
                break
    return out


def cache_name(identity: str) -> str:
    """File name of a measured spectrum in the derived cache: the identity and the pipeline version, hashed."""
    digest = hashlib.sha256(f"{__version__}|{identity}".encode()).hexdigest()[:16]
    return f"spectrum-{digest}.json.gz"


# ----------------------------------------------------------------------------------------- exposures
def exposures_to_json(exposures: Sequence[Exposure]) -> bytes:
    """The exposure list of a field as JSON (UTF-8), in the order given."""
    return json.dumps([asdict(exposure) for exposure in exposures], separators=(",", ":")).encode("utf-8")


def _exposure_list(listed: object) -> list[Exposure]:
    if not isinstance(listed, list):
        raise TypeError("not a JSON array")
    return [Exposure(**entry) for entry in listed]  # TypeError for anything but objects of Exposure's fields


def exposures_from_json(data: bytes) -> list[Exposure]:
    """The exposure list written by `exposures_to_json`. Raises ValueError when it is not one."""
    try:
        return _exposure_list(json.loads(data))
    except TypeError as exc:
        raise ValueError(f"not an exposure list: {exc}") from exc


def within_visits(exposures: Sequence[Exposure], time_bins: Sequence[TimeBin]) -> list[Exposure]:
    """The exposures whose listed mid-time falls in one of the field's visits (VISIT_SLACK_DAYS of slack).

    A list found again for a recorded field can hold newer exposures than the recording: they belong to no
    visit of its manifest and would be labelled with the wrong one, so they are left out.
    """
    spans = [(b.mjd_start - VISIT_SLACK_DAYS, b.mjd_end + VISIT_SLACK_DAYS) for b in time_bins]
    return [e for e in exposures if any(start <= e.mjd <= end for start, end in spans)]
