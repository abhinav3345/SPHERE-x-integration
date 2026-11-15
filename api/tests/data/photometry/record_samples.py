"""Record the real samples that the offline photometry tests replay.

Needs the network (IRSA SIA, the public SPHEREx bucket). Run once by hand from the `api` folder:

    uv run python tests/data/photometry/record_samples.py

For each sample set it discovers the field's exposures, picks a few by a fixed rule, and reads their windows with
the production reader exactly as `tombaugh.photometry.measure` does (`remote_fits.read_windows`, half-width
`WINDOW_HALF_PX`, centred on the target at the mean time of the field's exposures). It then reads each detector's
EPSF table with `photometry.fetch_psf_table` and keeps the zone geometry of the whole table and the stamps of the
zones the samples use. Nothing is edited. It writes, next to this script:

    windows.npz   image (float32) and flags (int32) of every window, and its IMAGE header (zlib, uint8)
    windows.json  per window: sample set, exposure, x0, y0, lam, dlam, mjd, psf_fwhm, zodi_level, sky_var, version
    psf.npz       per detector: xcenter, ycenter, cwave of every zone; the zone ids and stamps that were kept
    sets.json     per sample set: the target and neighbour astrometry used, with its source
"""

from __future__ import annotations

import json
import zlib
from dataclasses import asdict
from pathlib import Path

import numpy as np

from tombaugh import photometry as ph
from tombaugh import remote_fits
from tombaugh.build import sample_exposures
from tombaugh.discovery import discover
from tombaugh.register import celestial_wcs
from tombaugh.tools.make_fixture import TARGETS

HERE = Path(__file__).resolve().parent

# CatWISE2020 (VizieR II/365 at the CfA mirror, read 14 Nov 2026): ra_pm, dec_pm at epoch 2015.405 (MJD 57170),
# motions converted from arcsec/yr to mas/yr.
STAR = {
    "catalog": "catwise",
    "id": "J085501.95-071428.2",
    "ra": 133.7581654,
    "dec": -7.2411795,
    "epoch": 2015.405,
    "pmra": 8.69,
    "pmdec": -4.39,
}


def _source(entry: dict) -> ph.Source:
    keys = ("ra", "dec", "epoch", "pmra", "pmdec", "parallax", "catalog", "id")
    return ph.Source(**{k: entry[k] for k in keys if k in entry})


def _target(name: str) -> dict:
    t = TARGETS[name]
    return {
        "catalog": "",
        "id": t.label,
        "ra": t.ra,
        "dec": t.dec,
        "epoch": t.epoch,
        "pmra": t.pmra,
        "pmdec": t.pmdec,
        "parallax": t.parallax,
        "source": t.source,
    }


SETS = {
    # WISE 0855: four 4.4-5.0 micron exposures (detector 6) and three below 2.4 micron (detectors 1 to 3).
    "wise0855": {
        "field": (133.7598, -7.2422),
        "target": _target("wise0855"),
        "neighbours": [STAR],
        "pick": {6: 4, 1: 1, 2: 1, 3: 1},
    },
    # Barnard's Star: saturated core.
    "barnard": {
        "field": (269.4463, 4.7682),
        "target": _target("barnard"),
        "neighbours": [],
        "pick": {1: 2, 2: 2, 6: 1},
    },
    # An empty patch of the WISE 0855 field: 21.6" from the nearest CatWISE2020 source, 25" or more from 2MASS and
    # AllWISE sources (measured on 14 Nov 2026 with the catalogues of the VizieR mirror at CfA).
    "empty": {
        "field": (133.7598, -7.2422),
        "target": {"catalog": "", "id": "empty", "ra": 133.7514, "dec": -7.2616},
        "neighbours": [],
        "pick": {1: 1, 3: 1, 5: 1, 6: 1},
    },
}


def _pick(exposures, counts: dict[int, int]):
    """`counts[det]` exposures of each detector, spread evenly through time."""
    chosen = []
    for det, n in counts.items():
        mine = [e for e in exposures if e.det == det]
        chosen += [mine[(2 * i + 1) * len(mine) // (2 * n)] for i in range(n)]
    return chosen


def main() -> None:
    images, flags, headers, meta, tables, keep = [], [], [], [], {}, {}
    for name, spec in SETS.items():
        exposures = sample_exposures(discover(*spec["field"]))
        target = _source(spec["target"])
        mid = ph.mjd_to_jyear(float(np.mean([e.mjd for e in exposures])))
        ra, dec = target.position_at_year(mid)
        chosen = _pick(exposures, spec["pick"])
        cutouts, failures = remote_fits.read_windows(chosen, ra, dec, ph.WINDOW_HALF_PX, workers=8)
        print(name, len(cutouts), "windows", failures)
        sources = [target] + [_source(n) for n in spec["neighbours"]]
        for cut in cutouts:
            det = cut.exposure.det
            if det not in tables:
                tables[det] = ph.fetch_psf_table(cut.exposure)
            wcs = celestial_wcs(cut.wcs_header)
            for source in sources:
                sra, sdec = source.position_at_year(ph.mjd_to_jyear(cut.mjd))
                x, y = (float(v) for v in wcs.all_world2pix(sra, sdec, 0))
                keep.setdefault(det, set()).add(tables[det].zone(x, y))
            images.append(np.asarray(cut.image, dtype=np.float32))
            flags.append(np.asarray(cut.flags, dtype=np.int32))
            headers.append(np.frombuffer(zlib.compress(cut.wcs_header.encode("ascii"), 9), dtype=np.uint8))
            meta.append(
                {
                    "set": name,
                    "exposure": asdict(cut.exposure),
                    "x0": cut.x0,
                    "y0": cut.y0,
                    "lam": cut.lam,
                    "dlam": cut.dlam,
                    "mjd": cut.mjd,
                    "psf_fwhm": cut.psf_fwhm,
                    "zodi_level": cut.zodi_level,
                    "sky_var": cut.sky_var,
                    "version": cut.version,
                }
            )
    arrays = {f"image_{i}": a for i, a in enumerate(images)}
    arrays.update({f"flags_{i}": a for i, a in enumerate(flags)})
    arrays.update({f"header_{i}": a for i, a in enumerate(headers)})
    np.savez_compressed(HERE / "windows.npz", **arrays)
    (HERE / "windows.json").write_text(json.dumps(meta, indent=1) + "\n")
    psf = {}
    for det, table in tables.items():
        zones = np.array(sorted(keep[det]), dtype=np.int64)
        psf[f"xcenter_{det}"] = table.xcenter
        psf[f"ycenter_{det}"] = table.ycenter
        psf[f"cwave_{det}"] = table.cwave
        psf[f"zones_{det}"] = zones
        psf[f"stamps_{det}"] = table.stamps[zones]
    np.savez_compressed(HERE / "psf.npz", **psf)
    sets = {name: {"target": spec["target"], "neighbours": spec["neighbours"]} for name, spec in SETS.items()}
    (HERE / "sets.json").write_text(json.dumps(sets, indent=1) + "\n")
    print({det: sorted(z) for det, z in keep.items()})


if __name__ == "__main__":
    main()
