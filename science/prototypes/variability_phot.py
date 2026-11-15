"""Steps c + e: forced aperture photometry (r = 2 px) on every exposure for the target and for 2MASS field stars.

Usage: python 04_phot.py "RW Aur"
Writes phot_<name>.json  (list of per-exposure, per-source measurements) and stars_<name>.json (catalog).
"""
import sys, json, os, io, csv, time
from common import *  # noqa
from astropy.coordinates import SkyCoord
import astropy.units as u
from photutils.aperture import CircularAperture

name = sys.argv[1]
tag = name.replace(" ", "_")
SIMBAD = {  # verified via SIMBAD TAP (Harvard mirror) 2026-11-14: ra, dec (ICRS, ep J2000), pmra, pmdec [mas/yr]
    "RW Aur": (76.95652603458333, 30.401438173888888, 7.23, -20.33),
    "R Dra": (248.16761083295, 66.75497941722, -20.643, 6.149),
}
FLAGN = {0: "TRANSIENT", 1: "OVERFLOW", 2: "SUR_ERROR", 6: "NONFUNC", 7: "DICHROIC", 9: "MISSING_DATA", 10: "HOT",
         11: "COLD", 12: "FULLSAMPLE", 14: "PHANMISS", 15: "NONLINEAR", 17: "PERSIST", 19: "OUTLIER", 20: "CROSSTALK",
         21: "SOURCE", 22: "GHOST", 23: "GHOST_FPA", 24: "GHOST_EXT", 25: "STREAK", 26: "BLOOM", 27: "SNOWBALL", 28: "HALO"}
R_AP, R_IN, R_OUT = 2.0, 5.0, 9.0
TAP = "https://irsa.ipac.caltech.edu/TAP/sync"


def tap(query, cache):
    path = os.path.join(HERE, cache)
    if not os.path.exists(path):
        r = spx.http_get(TAP, params={"QUERY": query, "FORMAT": "CSV"}, timeout=120)
        with open(path, "w") as f:
            f.write(r.text)
    with open(path) as f:
        return list(csv.DictReader(f))


def fl(v):
    try:
        return float(v)
    except Exception:
        return float("nan")


# ---------------------------------------------------------------- aperture correction from EPSF (r=2 px)
def ee_tables():
    """Per detector: zone centres, CWAVE and encircled energy inside r=2 native px (EPSF is 5x oversampled, 33x33)."""
    out = {}
    meta = json.load(open(os.path.join(HERE, "epsf_meta.json")))
    yy, xx = np.mgrid[0:33, 0:33]
    for det in range(1, 7):
        psf = np.load(os.path.join(HERE, f"epsf_det{det}.npy"))
        ee = []
        for p in psf:
            tot = p.sum()
            cy, cx = (yy * p).sum() / tot, (xx * p).sum() / tot
            # exact-ish: 4x4 subsampling of each oversampled pixel
            sub = np.linspace(-0.375, 0.375, 4)
            frac = np.zeros_like(p)
            for dy in sub:
                for dx in sub:
                    frac += (np.hypot(xx + dx - cx, yy + dy - cy) <= R_AP * 5.0)
            frac /= 16.0
            ee.append(float((p * frac).sum() / tot))
        m = meta[str(det)]
        out[det] = {"ee": np.array(ee), "cwave": np.array(m["cwave"]), "xc": np.array(m["xc"]), "yc": np.array(m["yc"])}
    return out


EE = ee_tables() if os.path.exists(os.path.join(HERE, "epsf_meta.json")) else None


def ee_at(det, xfull, yfull):
    if EE is None:
        return float("nan")
    t = EE[det]
    i = int(np.argmin((t["xc"] - xfull) ** 2 + (t["yc"] - yfull) ** 2))
    return float(t["ee"][i])


# ---------------------------------------------------------------- catalogs
ra0, dec0, pmra, pmdec = SIMBAD[name]
rad = 0.047  # deg = 169 arcsec: everything that can fall inside a rotated 49x49 px window
q2 = (f"SELECT ra,dec,j_m,h_m,k_m,j_msigcom,h_msigcom,k_msigcom,ph_qual,cc_flg FROM fp_psc "
      f"WHERE CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',{ra0},{dec0},{rad}))=1")
qw = (f"SELECT ra,dec,w1mpro,w1sigmpro,w2mpro,w2sigmpro,cc_flags,ph_qual,ext_flg FROM allwise_p3as_psd "
      f"WHERE CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',{ra0},{dec0},{rad}))=1")
tm = tap(q2, f"cat_2mass_{tag}.csv")
ws = tap(qw, f"cat_allwise_{tag}.csv")
print(f"2MASS sources within {rad*3600:.0f} arcsec: {len(tm)}; AllWISE: {len(ws)}")
c0 = SkyCoord(ra0 * u.deg, dec0 * u.deg)
tmc = SkyCoord([fl(r["ra"]) for r in tm] * u.deg, [fl(r["dec"]) for r in tm] * u.deg)
wsc = SkyCoord([fl(r["ra"]) for r in ws] * u.deg, [fl(r["dec"]) for r in ws] * u.deg) if ws else None
sep0 = tmc.separation(c0).arcsec
stars = []
MINSEP = float(sys.argv[2]) if len(sys.argv) > 2 else 40.0
for i, r in enumerate(tm):
    k, j, h = fl(r["k_m"]), fl(r["j_m"]), fl(r["h_m"])
    if sep0[i] < 3.0:  # the target itself
        print("target in 2MASS:", r)
        continue
    if not (k < 12.6) or sep0[i] < MINSEP or sep0[i] > 125.0:
        continue
    # isolation: no 2MASS neighbour within 22 arcsec that is brighter than K+2.5
    d = tmc.separation(tmc[i]).arcsec
    nb = [(d[jx], fl(tm[jx]["k_m"])) for jx in range(len(tm)) if jx != i and d[jx] < 22.0]
    if any(kk < k + 2.5 for _, kk in nb):
        continue
    st = {"id": f"2M_{i}", "ra": fl(r["ra"]), "dec": fl(r["dec"]), "J": j, "H": h, "K": k, "sep_arcsec": float(sep0[i]),
          "ph_qual": r["ph_qual"], "W1": float("nan"), "W2": float("nan")}
    if wsc is not None:
        dw = wsc.separation(tmc[i]).arcsec
        jw = int(np.argmin(dw))
        if dw[jw] < 3.0:
            st["W1"], st["W2"] = fl(ws[jw]["w1mpro"]), fl(ws[jw]["w2mpro"])
            st["wise_cc"] = ws[jw]["cc_flags"]
    stars.append(st)
stars.sort(key=lambda s: s["K"])
print(f"{len(stars)} isolated field stars with K<12.6 at {MINSEP:.0f}-125 arcsec:")
for s in stars:
    print("  ", s)
json.dump(stars, open(os.path.join(HERE, f"stars_{tag}.json"), "w"), indent=1)

# ---------------------------------------------------------------- photometry
rows, cuts = load_cuts(name, verbose=True)
print("cutouts:", len(cuts))
yy, xx = np.mgrid[0:2 * HALF + 1, 0:2 * HALF + 1]
BADBITS = sum(1 << b for b in (1, 2, 6, 9, 10, 11, 15))  # OVERFLOW SUR_ERROR NONFUNC MISSING HOT COLD NONLINEAR


def phot(c, ra, dec):
    x, y = [float(v) for v in c["wcs"].all_world2pix(ra, dec, 0)]
    n = 2 * HALF + 1
    if not (R_AP + 1 <= x <= n - 2 - R_AP and R_AP + 1 <= y <= n - 2 - R_AP):
        return None
    img, zodi, var, flg = c["image"].astype("f8"), c["zodi"].astype("f8"), c["variance"].astype("f8"), c["flags"]
    sub = img - zodi
    rr = np.hypot(xx - x, yy - y)
    w = CircularAperture((x, y), r=R_AP).to_mask(method="exact").to_image(sub.shape)
    inap = w > 0
    nan_ap = int(np.sum(~np.isfinite(sub[inap])))
    ann = (rr >= R_IN) & (rr <= R_OUT) & np.isfinite(sub) & ((flg & BADBITS) == 0)
    if ann.sum() < 20:
        return None
    a = sub[ann]
    med = np.median(a)
    mad = 1.4826 * np.median(np.abs(a - med))
    a = a[np.abs(a - med) < 3 * mad] if mad > 0 else a
    bkg, bkg_sig = float(np.median(a)), float(1.4826 * np.median(np.abs(a - np.median(a))))
    s = np.where(np.isfinite(sub), sub, 0.0)
    v = np.where(np.isfinite(var), var, 0.0)
    area = float(w.sum())
    apsum = float((w * s).sum() - bkg * area)
    aperr = float(np.sqrt((w * v).sum() + area * area * bkg_sig ** 2 / max(len(a), 1)))
    conv = spx.sr_per_pixel() * 1e9  # MJy/sr per px -> mJy
    core = rr <= 2.5
    f_or = int(np.bitwise_or.reduce(flg[inap]))
    iy, ix = int(round(y)), int(round(x))
    # centroid of the 5x5 box (diagnostic for WCS accuracy)
    box = (np.abs(xx - ix) <= 2) & (np.abs(yy - iy) <= 2)
    sb = np.where(box & np.isfinite(sub), sub - bkg, 0.0)
    tot = sb.sum()
    cxo, cyo = ((xx * sb).sum() / tot - x, (yy * sb).sum() / tot - y) if tot > 0 else (float("nan"), float("nan"))
    xf, yf = x + c["x0"], y + c["y0"]
    ee = ee_at(c["det"], xf, yf)
    return {"obs_id": c["obs_id"], "det": c["det"], "mjd": c["mjd"], "epoch": c["epoch"], "coll": c["collection"],
            "lam": float(c["lam_map"][iy, ix]), "x": x, "y": y, "xfull": xf, "yfull": yf,
            "flux_mJy": apsum * conv, "err_mJy": aperr * conv, "ee2": ee,
            "bkg": bkg, "bkg_sig": bkg_sig, "zodi": float(zodi[iy, ix]),
            "peak": float(np.nanmax(sub[rr <= 1.5])) if np.isfinite(sub[rr <= 1.5]).any() else float("nan"),
            "flag_or": f_or, "flag_cen": int(flg[iy, ix]), "nan_ap": nan_ap,
            "n_overflow": int(((flg[core] >> 1) & 1).sum()), "n_nonlinear": int(((flg[core] >> 15) & 1).sum()),
            "n_sur_error": int(((flg[core] >> 2) & 1).sum()), "n_persist": int(((flg[core] >> 17) & 1).sum()),
            "n_bad_ap": int(((flg[inap] & BADBITS) != 0).sum()), "cen_dx": float(cxo), "cen_dy": float(cyo),
            "psf_fwhm": c["psf_fwhm"], "dlam": float(c["dlam"])}


out = {"target": [], "stars": {s["id"]: [] for s in stars}}
for c in cuts:
    yr = 2000.0 + (c["mjd"] - 51544.5) / 365.25
    cosd = np.cos(np.radians(dec0))
    ra_t = ra0 + pmra * (yr - 2000.0) / 3.6e6 / cosd
    dec_t = dec0 + pmdec * (yr - 2000.0) / 3.6e6
    p = phot(c, ra_t, dec_t)
    if p:
        out["target"].append(p)
    for s in stars:
        p = phot(c, s["ra"], s["dec"])
        if p:
            out["stars"][s["id"]].append(p)
json.dump(out, open(os.path.join(HERE, f"phot_{tag}.json"), "w"))
t = out["target"]
print(f"target measurements: {len(t)}")
for s in stars:
    print(f"  star {s['id']} K={s['K']:.2f}: {len(out['stars'][s['id']])} measurements")


def flagnames(v):
    return [FLAGN.get(b, f"bit{b}") for b in range(32) if (v >> b) & 1]


# flag statistics at the target
from collections import Counter
cc, co = Counter(), Counter()
for p in t:
    for n_ in flagnames(p["flag_cen"]):
        cc[n_] += 1
    for n_ in flagnames(p["flag_or"]):
        co[n_] += 1
print("flag counts at CENTRAL pixel (of", len(t), "):", dict(cc))
print("flag counts OR over r<=2 aperture:", dict(co))
for det in range(1, 7):
    td = [p for p in t if p["det"] == det]
    if not td:
        continue
    pk = np.array([p["peak"] for p in td])
    fx = np.array([p["flux_mJy"] for p in td])
    print(f"  D{det}: n={len(td)} lam {min(p['lam'] for p in td):.3f}-{max(p['lam'] for p in td):.3f} um  "
          f"peak px median {np.nanmedian(pk):.1f} MJy/sr (max {np.nanmax(pk):.1f})  ap flux median {np.nanmedian(fx):.1f} mJy  "
          f"overflow-in-core {sum(p['n_overflow'] > 0 for p in td)}  nonlinear {sum(p['n_nonlinear'] > 0 for p in td)}  "
          f"sur_err {sum(p['n_sur_error'] > 0 for p in td)}  nan-in-ap {sum(p['nan_ap'] > 0 for p in td)}  "
          f"EE2 median {np.nanmedian([p['ee2'] for p in td]):.3f}  |centroid off| median "
          f"{np.nanmedian([np.hypot(p['cen_dx'], p['cen_dy']) for p in td]):.2f} px")
