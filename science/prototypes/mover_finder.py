"""Find SPHEREx Level-2 detector-images that contain a solar-system object at exposure time.

Method: Horizons daily geocentric ephemeris -> windows where solar elongation is in SPHEREx's range ->
ONE SIA query per ~8-day chunk (big circle covering the whole track segment + TIME window) -> local filter with the
s_region polygon at the interpolated position -> exact SPHEREx-centred Horizons positions at the exposure times.
"""
import sys, os, json, hashlib, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spx
import cadence_analyze as ca

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "")
DL = HERE + "dl/"
HOR = "https://ssd.jpl.nasa.gov/api/horizons.api"


def horizons(command, center="'500@399'", start=None, stop=None, step="1 d", tlist=None, quantities="1,3,9,19,20,23,24"):
    p = {"format": "text", "COMMAND": command, "OBJ_DATA": "'NO'", "MAKE_EPHEM": "'YES'", "EPHEM_TYPE": "'OBSERVER'",
         "CENTER": center, "QUANTITIES": f"'{quantities}'", "ANG_FORMAT": "'DEG'", "CSV_FORMAT": "'YES'", "CAL_FORMAT": "'JD'"}
    if tlist is not None:
        p["TLIST"] = "'" + " ".join(f"{t:.6f}" for t in tlist) + "'"
    else:
        p.update({"START_TIME": f"'{start}'", "STOP_TIME": f"'{stop}'", "STEP_SIZE": f"'{step}'"})
    key = hashlib.sha1(json.dumps(p, sort_keys=True).encode()).hexdigest()[:16]
    path = DL + f"hor_{key}.txt"
    if not os.path.exists(path):
        r = spx.http_get(HOR, params=p, timeout=120, tries=8)
        with open(path, "w") as f:
            f.write(r.text)
    txt = open(path).read()
    if "$$SOE" not in txt:
        raise RuntimeError("Horizons error: " + txt[-600:])
    body = txt.split("$$SOE")[1].split("$$EOE")[0].strip().splitlines()
    out = []
    for line in body:
        c = [x.strip() for x in line.split(",")]
        # JD, sun, moon, RA, DEC, dRA*cosD, dDEC, mag, (surf or nucleus mag), r, rdot, delta, deldot, S-O-T, /r, S-T-O
        def fl(x):
            try:
                return float(x)
            except Exception:
                return np.nan
        out.append([fl(c[0]), fl(c[3]), fl(c[4]), fl(c[5]), fl(c[6]), fl(c[7]), fl(c[8]), fl(c[9]), fl(c[11]), fl(c[13]), fl(c[15])])
    a = np.array(out)
    return {"jd": a[:, 0], "mjd": a[:, 0] - 2400000.5, "ra": a[:, 1], "dec": a[:, 2], "dra": a[:, 3], "ddec": a[:, 4],
            "mag": a[:, 5], "mag2": a[:, 6], "r": a[:, 7], "delta": a[:, 8], "elong": a[:, 9], "phase": a[:, 10]}


def sia_window(ra, dec, radius, mjd0, mjd1, coll):
    path = DL + f"siaw_{coll}_{ra:.4f}_{dec:+.4f}_{radius:.3f}_{mjd0:.2f}_{mjd1:.2f}.csv"
    if not os.path.exists(path):
        r = spx.http_get(spx.SIA_URL, params={"COLLECTION": coll, "POS": f"circle {ra} {dec} {radius}",
                                               "TIME": f"{mjd0} {mjd1}", "RESPONSEFORMAT": "csv"}, timeout=300, tries=8)
        with open(path, "w") as f:
            f.write(r.text)
    return spx._parse_sia_csv(open(path).read())


def sep(ra1, d1, ra2, d2):
    a1, a2, b1, b2 = map(np.radians, (ra1, ra2, d1, d2))
    return np.degrees(np.arccos(np.clip(np.sin(b1) * np.sin(b2) + np.cos(b1) * np.cos(b2) * np.cos(a1 - a2), -1, 1)))


def find(command, name, coll, mjd_lo, mjd_hi, elong_rng=(76, 122), chunk=8):
    eph = horizons(command, start="2025-04-20", stop="2026-11-12")
    m = (eph["mjd"] >= mjd_lo) & (eph["mjd"] <= mjd_hi) & (eph["elong"] >= elong_rng[0]) & (eph["elong"] <= elong_rng[1])
    idx = np.where(m)[0]
    if not len(idx):
        return [], eph
    # contiguous runs -> chunks
    runs = np.split(idx, np.where(np.diff(idx) > 1)[0] + 1)
    cand = []
    nq = 0
    for run in runs:
        for k in range(0, len(run), chunk):
            seg = run[k:k + chunk + 1]
            if len(seg) < 2:
                seg = np.array([seg[0], min(seg[0] + 1, len(eph["mjd"]) - 1)])
            ras, decs = eph["ra"][seg], eph["dec"][seg]
            # centre = mid of track; radius = max distance to track points + margin
            x = np.cos(np.radians(decs)) * np.cos(np.radians(ras)); y = np.cos(np.radians(decs)) * np.sin(np.radians(ras)); z = np.sin(np.radians(decs))
            cx, cy, cz = x.mean(), y.mean(), z.mean()
            ra0 = float(np.degrees(np.arctan2(cy, cx)) % 360); dec0 = float(np.degrees(np.arctan2(cz, np.hypot(cx, cy))))
            rad = float(sep(ra0, dec0, ras, decs).max() + 0.05)
            t0 = time.time()
            rows = sia_window(ra0, dec0, rad, float(eph["mjd"][seg[0]]), float(eph["mjd"][seg[-1]]), coll)
            nq += 1
            print(f"  {name} {coll} chunk mjd {eph['mjd'][seg[0]]:.1f}-{eph['mjd'][seg[-1]]:.1f} elong {eph['elong'][seg[0]]:.0f}->{eph['elong'][seg[-1]]:.0f} r={rad:.2f} deg: {len(rows)} rows ({time.time() - t0:.1f}s)", flush=True)
            for r in rows:
                ra_i = float(np.interp(r["mjd"], eph["mjd"], np.unwrap(np.radians(eph["ra"])))); ra_i = np.degrees(ra_i) % 360
                dec_i = float(np.interp(r["mjd"], eph["mjd"], eph["dec"]))
                ws, order = ca.wave_wcs(r["det"], rows)
                xx, yy, uv = ca.frac_xy(r, ra_i, dec_i, order)
                if -0.01 <= uv[0] <= 1.01 and -0.01 <= uv[1] <= 1.01:
                    r["ra_i"], r["dec_i"], r["x"], r["y"] = ra_i, dec_i, float(xx), float(yy)
                    r["coll"] = coll
                    cand.append(r)
    # de-dup
    seen, out = set(), []
    for r in sorted(cand, key=lambda r: (r["mjd"], r["det"])):
        k = (r["obs_id"], r["det"])
        if k not in seen:
            seen.add(k); out.append(r)
    print(f"  {name} {coll}: {nq} SIA queries, {len(out)} detector-images contain the interpolated geocentric position", flush=True)
    return out, eph


def refine(command, rows):
    """Exact astrometric positions at exposure mid-times, as seen from the SPHEREx spacecraft (-163182) and geocentre."""
    if not rows:
        return rows
    jds = sorted(set(round(r["mjd"] + 2400000.5, 6) for r in rows))
    pos = {}
    for k in range(0, len(jds), 40):
        part = jds[k:k + 40]
        e = horizons(command, center="'500@-163182'", tlist=part)
        g = horizons(command, center="'500@399'", tlist=part)
        for i, jd in enumerate(part):
            pos[jd] = (e["ra"][i], e["dec"][i], e["dra"][i], e["ddec"][i], e["mag"][i], e["r"][i], e["delta"][i], e["elong"][i], e["phase"][i], g["ra"][i], g["dec"][i])
    for r in rows:
        p = pos[round(r["mjd"] + 2400000.5, 6)]
        r["ra_o"], r["dec_o"], r["dra"], r["ddec"], r["vmag"], r["rh"], r["delta"], r["elong"], r["phase"], r["ra_geo"], r["dec_geo"] = [float(v) for v in p]
        ws, order = ca.wave_wcs(r["det"], rows)
        xx, yy, uv = ca.frac_xy(r, r["ra_o"], r["dec_o"], order)
        r["x"], r["y"] = float(xx), float(yy)
        r["on"] = bool(0.0 <= uv[0] <= 1.0 and 0.0 <= uv[1] <= 1.0)
        lam, dlam = ws.wcs_pix2world(np.clip(xx, 0, 2039), np.clip(yy, 0, 2039), 0)
        r["lam"], r["dlam"] = float(lam), float(dlam)
    return rows


if __name__ == "__main__":
    name, command = sys.argv[1], sys.argv[2]
    allrows = []
    for coll, lo, hi in (("spherex_dr1", 60780, 61180), ("spherex_qr3", 61170, 61330)):
        if len(sys.argv) > 3 and sys.argv[3] != coll:
            continue
        rows, eph = find(command, name, coll, lo, hi)
        allrows += rows
    allrows = refine(command, allrows)
    keep = [r for r in allrows if r.get("on")]
    slim = [{k: r[k] for k in ("obs_id", "det", "mjd", "coll", "s3_url", "access_url", "ra_o", "dec_o", "dra", "ddec", "vmag", "rh", "delta", "elong", "phase", "ra_geo", "dec_geo", "x", "y", "lam", "dlam", "s_region", "energy_bandpassname", "t_min", "t_max")} for r in keep]
    json.dump(slim, open(HERE + f"found_{name}.json", "w"))
    from astropy.time import Time
    print(f"{name}: {len(keep)} detector-images contain the object (SPHEREx-centred Horizons position)")
    for r in keep:
        print(f"  {Time(r['mjd'], format='mjd').iso[:19]} {r['obs_id']} D{r['det']} lam {r['lam']:.3f} xy ({r['x']:.0f},{r['y']:.0f}) RA {r['ra_o']:.5f} Dec {r['dec_o']:+.5f} rate {r['dra']:.1f},{r['ddec']:.1f} \"/h V {r['vmag']:.1f} r {r['rh']:.2f} delta {r['delta']:.2f} elong {r['elong']:.1f} geo-off {3600 * sep(r['ra_o'], r['dec_o'], r['ra_geo'], r['dec_geo']):.1f}\" {r['coll']}")
