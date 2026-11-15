"""Record the real IRSA answers that tests/test_legacy.py replays. Needs the network.

    cd api && uv run python tests/data/legacy/record_samples.py

Asks exactly what `tombaugh.legacy.build_legacy_planes` asks for a 3' grid (59 x 59 pixels) at the centre of the
recorded WISE 0855 field (RA 133.7598, Dec -7.2422) and the bands W2 and Ks, through `tombaugh.http`, and
writes each cut-out byte for byte (gzip, as served) with an index, `requests.json`. To stay small, an SIA answer
is kept as an excerpt: its header line and its rows of the bands in `KEEP_ROWS` (every subtype), whole lines, in
the order served; the index also gives the length and SHA-256 of the whole answer.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tombaugh import http, legacy
from tombaugh.discovery import SIA_URL
from tombaugh.grid import Grid

HERE = Path(__file__).resolve().parent
GRID = Grid(133.7598, -7.2422, 59)
BANDS = ("W2", "Ks")
KEEP_ROWS = {"wise_allwise": ("W2", "W3"), "twomass_allsky": ("K", "J")}  # SIA energy_bandpassname values


def excerpt(body: bytes, collection: str) -> bytes:
    """The header line and the rows of the kept bands, as served (lines end with a newline)."""
    lines = body.decode("utf-8").splitlines(keepends=True)
    column = lines[0].rstrip("\r\n").split("\t").index("energy_bandpassname")
    kept = [line for line in lines[1:] if line.split("\t")[column] in KEEP_ROWS[collection]]
    return "".join([lines[0], *kept]).encode("utf-8")


def save(name: str, url: str, params: dict[str, str], body: bytes, index: list[dict], whole: bytes) -> None:
    (HERE / name).write_bytes(body)
    entry = {
        "file": name,
        "url": url,
        "params": params,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    if whole != body:
        entry["whole_answer"] = {"bytes": len(whole), "sha256": hashlib.sha256(whole).hexdigest()}
    index.append(entry)
    print(f"{name}: {len(body)} bytes")


def main() -> None:
    index: list[dict] = []
    deadline = http.Deadline(300)
    found: dict[str, list[legacy.LegacyImage]] = {}
    for mission in ("AllWISE", "2MASS"):
        survey = legacy.SURVEYS[mission]
        parts = []
        for i, (ra, dec, radius) in enumerate(legacy.search_circles(GRID)):
            params = {
                "COLLECTION": survey.collection,
                "POS": f"circle {ra:.6f} {dec:.6f} {radius:.6f}",
                "RESPONSEFORMAT": "TSV",
            }
            whole = http.get(SIA_URL, params=params, timeout=legacy.SIA_TIMEOUT, deadline=deadline).content
            body = excerpt(whole, survey.collection)
            save(f"sia_{survey.collection}_{i}.tsv", SIA_URL, params, body, index, whole)
            parts.append(legacy.parse_sia_tsv(body.decode("utf-8"), mission)[0])
        found[mission] = legacy.merge_images(parts)
    for band in BANDS:
        mission = legacy.mission_of(band)
        chosen, _ = legacy.choose_images([image for image in found[mission] if image.band == band], GRID)
        for image in chosen:
            side = legacy.cutout_side_arcsec(GRID, image, legacy._PIXSCALE_HINT[mission])
            params = legacy.cutout_params(GRID, side)
            body = http.get(
                image.url, params=params, timeout=legacy.CUTOUT_TIMEOUT, deadline=deadline
            ).content
            save(f"cutout_{band}_{image.obs_id}.fits.gz", image.url, params, body, index, body)
    (HERE / "requests.json").write_text(
        json.dumps({"grid": [GRID.ra0, GRID.dec0, GRID.n], "bands": BANDS, "requests": index}, indent=1)
        + "\n"
    )


if __name__ == "__main__":
    main()
