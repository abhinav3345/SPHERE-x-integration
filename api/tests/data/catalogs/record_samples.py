"""Record the catalogue answers that tests/test_catalogs.py replays with no network.

    cd api && uv run python tests/data/catalogs/record_samples.py [out_dir]

For each recorded field in ``cache/fixtures`` (wise0855, barnard) this asks the live services exactly what
``tombaugh.catalogs.overlays_for_manifest`` asks, with the same search radius, and writes the answers byte for
byte, gzip-compressed:

* ``gaia_<name>.csv.gz``: the Gaia DR3 TAP answer of the first service in ``make_fixture.TAP_SERVICES`` that
  answers (ARI Heidelberg, else GAVO);
* ``catwise_<name>.tbl.gz``: IRSA Gator's IPAC-table answer for CatWISE2020;
* ``samples.json``: what was asked, from where, when, how many rows came back and how long each took.

It needs the network. Nothing is edited after download.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import sys
import time
from pathlib import Path

from tombaugh import catalogs, http
from tombaugh.models import Manifest
from tombaugh.tools.make_fixture import TAP_SERVICES, TAP_TIMEOUT

HERE = Path(__file__).resolve().parent
FIXTURES = Path(__file__).resolve().parents[4] / "cache" / "fixtures"
NAMES = ("wise0855", "barnard")


def _fetch(url: str, params: dict[str, str], timeout: tuple[float, float], tries: int) -> tuple[bytes, float]:
    started = time.monotonic()
    response = http.get(url, params=params, timeout=timeout, tries=tries, deadline=http.Deadline(150.0))
    return response.content, time.monotonic() - started


def record(name: str, out: Path) -> dict:
    manifest = Manifest.model_validate_json((FIXTURES / name / "manifest.json").read_text(encoding="utf-8"))
    grid = catalogs.field_grid(manifest)
    bins = manifest.time_bins
    entry: dict = {"field": name, "centre": [grid.ra0, grid.dec0], "grid_n": grid.n}

    radius = catalogs.search_radius_deg(grid, bins, catalogs.GAIA_EPOCH)
    for url, table in TAP_SERVICES:
        params = catalogs.gaia_query_params(table, grid.ra0, grid.dec0, radius)
        try:
            body, seconds = _fetch(url, params, TAP_TIMEOUT, 5)
            rows = catalogs.parse_gaia_csv(body.decode("utf-8"))
        except (http.UpstreamError, ValueError) as exc:
            print(f"{name}: gaia {url} failed: {exc}", file=sys.stderr)
            continue
        (out / f"gaia_{name}.csv.gz").write_bytes(gzip.compress(body, mtime=0))
        entry["gaia"] = {"url": url, "params": params, "seconds": round(seconds, 2), "rows": len(rows),
                         "bytes": len(body)}  # fmt: skip
        break

    radius = catalogs.search_radius_deg(grid, bins, catalogs.catwise_epoch_jyear())
    params = catalogs.catwise_query_params(grid.ra0, grid.dec0, radius)
    body, seconds = _fetch(catalogs.CATWISE_URL, params, catalogs.CATWISE_TIMEOUT, catalogs.CATWISE_TRIES)
    rows = catalogs.parse_catwise_ipac(body.decode("utf-8"))
    (out / f"catwise_{name}.tbl.gz").write_bytes(gzip.compress(body, mtime=0))
    entry["catwise"] = {"url": catalogs.CATWISE_URL, "params": params, "seconds": round(seconds, 2),
                        "rows": len(rows), "bytes": len(body)}  # fmt: skip
    return entry


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE
    out.mkdir(parents=True, exist_ok=True)
    recorded = {
        "recorded_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fields": [record(name, out) for name in NAMES],
    }
    (out / "samples.json").write_text(json.dumps(recorded, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(recorded, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
