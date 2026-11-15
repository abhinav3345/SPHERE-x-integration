"""Shared bits for the variability agent scripts (research only)."""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spx  # noqa
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
HALF = 24
# cutout-centre coordinates (deg). FIXED so the on-disk cutout cache keys stay valid. Precise source
# positions are computed later through each cutout's WCS, so these only need to be within a pixel or two.
TARGETS = {
    "RW Aur": (76.95625, 30.40139),
    "R Dra": (248.1675, 66.755),
}
SIA_RADIUS = 0.01


def rows_for(name, collections=("spherex_dr1", "spherex_qr3")):
    ra, dec = TARGETS[name]
    allrows = []
    for coll in collections:
        rows = spx.sia(ra, dec, radius_deg=SIA_RADIUS, collection=coll)
        for r in rows:
            r["collection"] = coll
        allrows += rows
    # de-duplicate on obs_id + detector (DR1 wins over QR3 if both exist)
    seen, out = set(), []
    for r in sorted(allrows, key=lambda d: (d["collection"], d["mjd"])):
        k = (r["obs_id"], r["det"])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return spx.epochs(out, gap_days=20.0)


def load_cuts(name, workers=8, verbose=True, collections=("spherex_dr1", "spherex_qr3")):
    ra, dec = TARGETS[name]
    rows = rows_for(name, collections)
    coll = {(r["obs_id"], r["det"]): r["collection"] for r in rows}
    cuts = spx.fetch_many(rows, ra, dec, half=HALF, workers=workers, verbose=verbose)
    for c in cuts:
        c["collection"] = coll.get((c["obs_id"], c["det"]), "?")
    return rows, cuts
