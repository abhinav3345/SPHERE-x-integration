"""Per-season stacks on a fixed north-up grid, centroids vs predicted motion, field-star null test, blink/diff/RGB PNGs.
usage: 04_stack.py <barnard|epsindB> <half> <pixscale_arcsec> <mask: lenient|strict> [zoom_halfwidth_px_native]
Outputs in out/: <tag>_stack.npz, <tag>_centroids.csv, <tag>_blink_<SEL>.png, per-season frames, GIF."""
import sys, json, os, csv, time, warnings, collections
import numpy as np
from scipy.optimize import least_squares
from scipy.ndimage import maximum_filter
import astropy
astropy.log.setLevel("ERROR")
warnings.simplefilter("ignore")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mb
from mb import spx

key, half, scale, mode = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
zoomhw = float(sys.argv[5]) if len(sys.argv) > 5 else 8.0
tag = f"{key}_h{half}_s{scale:g}_{mode}"
ra0, dec0 = mb.fixed_centre(key)
T = mb.TARGETS[key]
rows = json.load(open(os.path.join(mb.OUT, f"{key}_rows.json")))
cuts = spx.fetch_many(rows, ra0, dec0, half=half, workers=8, verbose=False)
nat = 2 * half + 1
npix = nat if abs(scale - 6.15) < 1e-6 else (int(round(nat * 6.15 / scale)) // 2) * 2 + 1
grid = spx.target_grid_wcs(ra0, dec0, npix=npix, pixscale_arcsec=scale)
cx = cy = (npix - 1) / 2.0
SRC = 1 << 21
HARD = (1 << 6) | (1 << 9) | (1 << 10) | (1 << 11)          # NONFUNC, MISSING_DATA, HOT, COLD
SATBITS = (1 << 1) | (1 << 26)                               # OVERFLOW, BLOOM
maskbits = mb.BADMASK if mode == "strict" else HARD
seasons = spx.epochs([{"mjd": c["mjd"], "i": i} for i, c in enumerate(cuts)], gap_days=60.0)
season_of = {d["i"]: d["epoch"] for d in seasons}
NS = max(season_of.values()) + 1
K = 3  # wavelength sub-bins per detector for matched stacking

# ------------------------------------------------------------------ reproject every exposure (cached)
cache = os.path.join(mb.OUT, tag + "_reproj.npz")
if os.path.exists(cache):
    z = np.load(cache)
    SCI, DISP, meta = z["sci"], z["disp"], json.loads(str(z["meta"]))
    print("loaded reprojection cache", SCI.shape)
else:
    SCI = np.full((len(cuts), npix, npix), np.nan, "f4")
    DISP = np.full((len(cuts), npix, npix), np.nan, "f4")
    meta = []
    t0 = time.time()
    for i, c in enumerate(cuts):
        img, fl, var, zo = c["image"], c["flags"], c["variance"], c["zodi"]
        sub = (img - zo).astype("f8")
        fin = np.isfinite(sub)
        bkgm = fin & ((fl & mb.BADMASK) == 0) & ((fl & SRC) == 0)
        if bkgm.sum() < 50:
            bkgm = fin & ((fl & mb.BADMASK) == 0)
        if bkgm.sum() < 20:
            bkgm = fin
        med = np.nanmedian(sub[bkgm]) if bkgm.any() else 0.0
        sub -= med
        vmed = float(np.nanmedian(var[bkgm])) if bkgm.any() else np.nan
        sci = sub.copy()
        sci[(fl & maskbits) != 0] = np.nan
        disp = sci.copy()
        satnan = ~np.isfinite(img) & ((fl & SATBITS) != 0)     # saturated core delivered as NaN
        if satnan.any() and np.isfinite(sub).any():
            # fill with the brightest finite value within 3 px of the hole (flat-topped star for display)
            from scipy.ndimage import maximum_filter as mf, binary_dilation
            tmp = np.where(np.isfinite(sub), sub, -np.inf)
            loc = mf(tmp, size=7)
            disp[satnan] = np.where(np.isfinite(loc[satnan]), loc[satnan], np.nanmax(sub))
        c2 = dict(c)
        c2["image"] = sci
        a, fp = spx.reproject_cut(c2, grid, npix, key="image")
        SCI[i] = a
        c2["image"] = disp
        a, fp = spx.reproject_cut(c2, grid, npix, key="image")
        DISP[i] = a
        xp, yp = [float(v) for v in c["wcs"].all_world2pix(*mb.pos_at(key, c["mjd"]), 0)]
        xi, yi = int(np.clip(round(xp), 0, nat - 1)), int(np.clip(round(yp), 0, nat - 1))
        meta.append(dict(det=int(c["det"]), mjd=float(c["mjd"]), lam=float(c["lam_map"][yi, xi]), vmed=vmed, season=season_of[i],
                         obs_id=c["obs_id"], nsat=int(satnan.sum())))
    dt = time.time() - t0
    print(f"reprojected {len(cuts)} cutouts x 2 planes onto {npix}x{npix} @ {scale}\" in {dt:.1f}s -> {dt / len(cuts) / 2 * 1000:.1f} ms per plane")
    np.savez(cache, sci=SCI, disp=DISP, meta=json.dumps(meta))

det = np.array([m["det"] for m in meta]); mjd = np.array([m["mjd"] for m in meta]); lam = np.array([m["lam"] for m in meta])
sea = np.array([m["season"] for m in meta]); wgt = 1.0 / np.array([m["vmed"] for m in meta])
wgt[~np.isfinite(wgt)] = 0
sub = np.zeros(len(meta), int)
for d, (lo, hi) in mb.DET_RANGE.items():
    s = det == d
    sub[s] = np.clip(((lam[s] - lo) / (hi - lo) * K).astype(int), 0, K - 1)
binid = (det - 1) * K + sub


def wmean(A, w):
    m = np.isfinite(A)
    num = np.nansum(A * w[:, None, None], axis=0)
    den = (m * w[:, None, None]).sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


def season_stacks(A, dets, use_seasons):
    """Bin-matched stacks: only (det, sub-band) bins populated in every season are used, bins get equal weight."""
    bins = [b for b in range(6 * K) if (b // K + 1) in dets and all(((binid == b) & (sea == s) & (wgt > 0)).any() for s in use_seasons)]
    out, info = {}, {}
    for s in use_seasons:
        layers, n, mj, ww, lams = [], 0, 0.0, 0.0, []
        for b in bins:
            sel = (binid == b) & (sea == s) & (wgt > 0)
            layers.append(wmean(A[sel], wgt[sel]))
            n += int(sel.sum()); mj += float((mjd[sel] * wgt[sel]).sum() / wgt[sel].sum()); lams += list(lam[sel])
        if not layers:
            continue
        L = np.array(layers)
        with np.errstate(invalid="ignore"):
            out[s] = np.nanmean(L, axis=0)
        info[s] = dict(n=n, mjd=mj / len(bins), lam_lo=min(lams), lam_hi=max(lams), nbins=len(bins))
    return out, info


def gfit(img, x0, y0, r):
    xi, yi = int(round(x0)), int(round(y0))
    if yi - r < 0 or xi - r < 0 or yi + r + 1 > img.shape[0] or xi + r + 1 > img.shape[1]:
        return None
    ys, xs = np.mgrid[yi - r:yi + r + 1, xi - r:xi + r + 1]
    zz = img[yi - r:yi + r + 1, xi - r:xi + r + 1].astype("f8")
    ok = np.isfinite(zz)
    if ok.sum() < 12:
        return None
    s0 = 0.6 * 6.15 / scale

    def res(p):
        a, x, y, sx, sy, b = p
        return (a * np.exp(-0.5 * (((xs - x) / sx) ** 2 + ((ys - y) / sy) ** 2)) + b - zz)[ok]
    try:
        s = least_squares(res, [np.nanmax(zz), x0, y0, s0, s0, np.nanmedian(zz[ok])],
                          bounds=([0, x0 - r, y0 - r, 0.2 * s0, 0.2 * s0, -np.inf], [np.inf, x0 + r, y0 + r, 8 * s0, 8 * s0, np.inf]))
    except Exception:
        return None
    a, x, y, sx, sy, b = s.x
    return dict(x=x, y=y, amp=a, fwhm=2.3548 * np.sqrt(sx * sy) * scale, dE=-(x - cx) * scale, dN=(y - cy) * scale, nan=int((~ok).sum()))


def pred_off(m):
    r, d = mb.pos_at(key, m)
    return mb.offset_arcsec(r, d, ra0, dec0)


R = max(3, int(round(3 * 6.15 / scale)))
use = list(range(NS))
sels = [("D%d" % d, [d]) for d in range(1, 7)] + [("ALL", [1, 2, 3, 4, 5, 6]), ("D1-3", [1, 2, 3]), ("D4-6", [4, 5, 6])]
stacks, infos, rowsout = {}, {}, []
print(f"\n== {T['name']}  tag={tag}  seasons={NS}  grid {npix}x{npix} @ {scale}\"  mask={mode}")
for name, dets in sels:
    for A, kind in ((SCI, "sci"), (DISP, "disp")):
        st, inf = season_stacks(A, dets, use)
        stacks[(name, kind)] = st
        infos[name] = inf
    st = stacks[(name, "sci")]
    for s in sorted(st):
        pe, pn = pred_off(infos[name][s]["mjd"])
        x0, y0 = cx - pe / scale, cy + pn / scale
        g = gfit(st[s], x0, y0, R)
        rec = dict(sel=name, season=s, n=infos[name][s]["n"], nbins=infos[name][s]["nbins"], date=mb.mjd2iso(infos[name][s]["mjd"]), mjd=infos[name][s]["mjd"],
                   lam_lo=infos[name][s]["lam_lo"], lam_hi=infos[name][s]["lam_hi"], pred_dE=pe, pred_dN=pn)
        if g:
            rec.update(meas_dE=g["dE"], meas_dN=g["dN"], res_dE=g["dE"] - pe, res_dN=g["dN"] - pn, fwhm=g["fwhm"], amp=g["amp"], nan_in_win=g["nan"])
        rowsout.append(rec)

print("sel   season date        N  bins  lam[um]        pred dE,dN [\"]     meas dE,dN [\"]     resid dE,dN [\"]   FWHM[\"]  amp[MJy/sr] NaN-in-window")
for r in rowsout:
    if "meas_dE" in r:
        print(f"{r['sel']:5s} {r['season']}      {r['date']} {r['n']:3d} {r['nbins']:3d}  {r['lam_lo']:.2f}-{r['lam_hi']:.2f}   {r['pred_dE']:+6.2f} {r['pred_dN']:+6.2f}    "
              f"{r['meas_dE']:+6.2f} {r['meas_dN']:+6.2f}    {r['res_dE']:+5.2f} {r['res_dN']:+5.2f}    {r['fwhm']:5.1f}   {r['amp']:9.3f}  {r['nan_in_win']}")
    else:
        print(f"{r['sel']:5s} {r['season']}      {r['date']} {r['n']:3d}  fit failed")
print("\n== season-to-season shift of the target: measured vs predicted (PM + parallax) [arcsec]")
for name, _ in sels:
    rr = {r["season"]: r for r in rowsout if r["sel"] == name and "meas_dE" in r}
    ss = sorted(rr)
    for a in range(len(ss)):
        for b in range(a + 1, len(ss)):
            A_, B_ = rr[ss[a]], rr[ss[b]]
            mE, mN = B_["meas_dE"] - A_["meas_dE"], B_["meas_dN"] - A_["meas_dN"]
            pE, pN = B_["pred_dE"] - A_["pred_dE"], B_["pred_dN"] - A_["pred_dN"]
            print(f"{name:5s} season {ss[a]}->{ss[b]} ({A_['date']} -> {B_['date']}): measured dE {mE:+6.2f} dN {mN:+6.2f} |{np.hypot(mE, mN):5.2f}|   "
                  f"predicted dE {pE:+6.2f} dN {pN:+6.2f} |{np.hypot(pE, pN):5.2f}|   diff {mE - pE:+5.2f} {mN - pN:+5.2f}")
with open(os.path.join(mb.OUT, tag + "_centroids.csv"), "w", newline="") as f:
    ks = ["sel", "season", "date", "mjd", "n", "nbins", "lam_lo", "lam_hi", "pred_dE", "pred_dN", "meas_dE", "meas_dN", "res_dE", "res_dN", "fwhm", "amp", "nan_in_win"]
    w = csv.DictWriter(f, fieldnames=ks); w.writeheader()
    for r in rowsout:
        w.writerow({k: r.get(k, "") for k in ks})

# ------------------------------------------------------------------ field stars (null test)
allst = stacks[("ALL", "sci")]
if len(allst) >= 2:
    mean_all = np.nanmean(np.array([allst[s] for s in sorted(allst)]), axis=0)
    filled = np.where(np.isfinite(mean_all), mean_all, -np.inf)
    fs = max(5, int(round(5 * 6.15 / scale)) | 1)
    loc = (filled == maximum_filter(filled, size=fs)) & np.isfinite(mean_all)
    yy, xx = np.nonzero(loc)
    noise = mb.mad_std(mean_all)
    cand = []
    excl = (12 if key == "barnard" else 4) * 6.15 / scale
    edge = 4 * 6.15 / scale
    for y, x in zip(yy, xx):
        if np.hypot(x - cx, y - cy) < excl or min(x, y, npix - 1 - x, npix - 1 - y) < edge:
            continue
        if mean_all[y, x] > 8 * noise:
            cand.append((mean_all[y, x], x, y))
    cand.sort(reverse=True)
    print(f"\n== field stars null test (brightest isolated peaks in the all-season ALL stack; noise(MAD)={noise:.4f} MJy/sr; {len(cand)} candidates)")
    allshift = collections.defaultdict(list)
    for name in ("ALL", "D1", "D2", "D3", "D4", "D5", "D6"):
        st = stacks[(name, "sci")]
        ss = sorted(st)
        if len(ss) < 2:
            continue
        for k, (pk, x, y) in enumerate(cand[:6]):
            fits_ = [gfit(st[s], x, y, R) for s in ss]
            if any(g is None for g in fits_) or any(g["nan"] > 0.3 * (2 * R + 1) ** 2 for g in fits_):
                continue
            # reject fits that ran away
            if any(np.hypot(g["x"] - x, g["y"] - y) > 1.5 * 6.15 / scale for g in fits_):
                continue
            E = np.array([g["dE"] for g in fits_]); N = np.array([g["dN"] for g in fits_])
            dE, dN = E - E.mean(), N - N.mean()
            allshift[name] += list(dE) + list(dN)
            if name == "ALL":
                print(f"  star{k} at dE={-(x - cx) * scale:+7.1f}\" dN={(y - cy) * scale:+7.1f}\" peak {pk:8.3f} MJy/sr: per-season offsets from mean "
                      + "  ".join(f"s{s}:({a:+.2f},{b:+.2f})" for s, a, b in zip(ss, dE, dN)) + f"   first->last shift |{np.hypot(E[-1] - E[0], N[-1] - N[0]):.2f}|\"")
    for name, v in allshift.items():
        v = np.array(v)
        print(f"  registration scatter {name}: rms per-axis offset from star mean = {np.sqrt(np.mean(v ** 2)):.3f}\"  (n={len(v)} season-axis values, {len(v) // (2 * NS)} stars)")

# ------------------------------------------------------------------ figures
def stretch(a, lo, hi, soft):
    a = np.clip((a - lo) / (hi - lo), 0, 1)
    return np.arcsinh(a / soft) / np.arcsinh(1 / soft)


def panels(name, kind="disp", zoom=None):
    st = stacks[(name, kind)]
    ss = sorted(st)
    if len(ss) < 2:
        return None
    first, last = st[ss[0]], st[ss[-1]]
    ref = np.array([st[s] for s in ss])
    if zoom:
        h = int(round(zoom * 6.15 / scale))
        sl = (slice(int(cy) - h, int(cy) + h + 1), slice(int(cx) - h, int(cx) + h + 1))
    else:
        sl = (slice(None), slice(None))
    sigma = mb.mad_std(ref)
    hi = np.nanpercentile(ref[:, sl[0], sl[1]], 99.9)
    lo = -2 * sigma
    soft = max(min(0.05, 10 * sigma / max(hi - lo, 1e-9)), 1e-4)
    ncol = len(ss) + 2
    fig, axs = plt.subplots(1, ncol, figsize=(4.6 * ncol, 5.2), dpi=110)
    ext_h = (first[sl].shape[0]) * scale / 2.0
    ext = [ext_h, -ext_h, -ext_h, ext_h]
    frames = []
    for ax, s in zip(axs, ss):
        im = stretch(st[s][sl], lo, hi, soft)
        frames.append(im)
        ax.imshow(np.where(np.isfinite(im), im, 0), origin="lower", cmap="gray", vmin=0, vmax=1, interpolation="nearest", extent=ext)
        inf = infos[name][s]
        pe, pn = pred_off(inf["mjd"])
        ax.plot([pe + 3 * scale + 6, pe + 3 * scale + 22], [pn, pn], color="yellow", lw=1)
        ax.plot([pe, pe], [pn + 3 * scale + 6, pn + 3 * scale + 22], color="yellow", lw=1)
        ax.set_title(f"{T['name']}  {name}  season {s}: {mb.mjd2iso(inf['mjd'])}\n{inf['lam_lo']:.2f}-{inf['lam_hi']:.2f} um, N={inf['n']} exp", fontsize=9)
    d = (last - first)[sl]
    v = np.nanpercentile(np.abs(d), 99.5)
    axs[-2].imshow(d, origin="lower", cmap="RdBu_r", vmin=-v, vmax=v, interpolation="nearest", extent=ext)
    axs[-2].set_title(f"difference: season {ss[-1]} - season {ss[0]}\n(red = brighter later; +-{v:.3g} MJy/sr)", fontsize=9)
    rgb = np.dstack([frames[0], frames[-1], frames[-1]])
    axs[-1].imshow(np.where(np.isfinite(rgb), rgb, 0), origin="lower", interpolation="nearest", extent=ext)
    axs[-1].set_title(f"composite: RED = season {ss[0]}, CYAN = season {ss[-1]}", fontsize=9)
    for ax in axs:
        ax.set_xlabel("dE [arcsec] (E left)"); ax.set_ylabel("dN [arcsec]")
    fig.suptitle(f"{tag}  {kind} stack, grid {scale}\"/px, fixed centre RA {ra0:.5f} Dec {dec0:+.5f}; yellow ticks = Gaia-predicted position"
                 + (f"  [zoom +-{zoom:g} native px]" if zoom else ""), fontsize=9)
    fig.tight_layout()
    p = os.path.join(mb.OUT, f"{tag}_blink_{name}" + ("_zoom" if zoom else "") + ".png")
    fig.savefig(p); plt.close(fig)
    return p, frames, ss


from PIL import Image
made = []
for name, _ in sels:
    for zoom in (None, zoomhw):
        r = panels(name, "disp", zoom)
        if r is None:
            continue
        p, frames, ss = r
        made.append(p)
        if name in ("ALL", "D3", "D5", "D2") and zoom:
            ims = []
            for fr, s in zip(frames, ss):
                a = (np.where(np.isfinite(fr), fr, 0)[::-1] * 255).astype("u1")
                im = Image.fromarray(a).resize((a.shape[1] * (12 if scale > 4 else 6), a.shape[0] * (12 if scale > 4 else 6)), Image.NEAREST)
                fp = os.path.join(mb.OUT, f"{tag}_frame_{name}_season{s}.png")
                im.save(fp); ims.append(im)
            gp = os.path.join(mb.OUT, f"{tag}_blink_{name}.gif")
            ims[0].save(gp, save_all=True, append_images=ims[1:], duration=600, loop=0)
            made.append(gp)
print("\nfigures:")
for p in made:
    print("  ", p)
np.savez(os.path.join(mb.OUT, tag + "_stack.npz"), **{f"{n}_{k}_s{s}": v for (n, k), st in stacks.items() for s, v in st.items()})
