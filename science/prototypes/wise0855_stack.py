"""Per-epoch stacks, S/N, centroids, blink / difference / red-cyan figures for WISE 0855."""
import csv, json
import numpy as np
from common import *
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from astropy.stats import mad_std, sigma_clip
from astropy.time import Time
from scipy.optimize import least_squares
from photutils.aperture import CircularAperture

tab = list(csv.DictReader(open(OUT + "exposures.csv")))
for t in tab:
    for k, v in t.items():
        if k not in ("obs_id", "date"):
            t[k] = float(v) if v not in ("", "nan") else np.nan
z = np.load(OUT + "prep.npz")
cube6, cube3, cubeM = z["cube6"], z["cube3"], z["cubeM"]
N6, N3, NM = 65, 131, 41
S3 = PIX / 2
G6 = spx.target_grid_wcs(RA0, DEC0, npix=N6, pixscale_arcsec=PIX)
G3 = spx.target_grid_wcs(RA0, DEC0, npix=N3, pixscale_arcsec=S3)
det = np.array([t["det"] for t in tab]).astype(int); ep = np.array([t["epoch"] for t in tab]).astype(int)
lam = np.array([t["lam_t"] for t in tab]); rms = np.array([t["rms"] for t in tab]); mjd = np.array([t["mjd"] for t in tab])
w = 1.0 / rms ** 2
UJ = 889.0  # MJy/sr -> microJy per native 6.15" pixel
stars = json.load(open(OUT + "stars.json"))["stars"]
cat = list(csv.DictReader(open(OUT + "catwise.csv")))
bgs = next(s for s in stars if s["source_name"].startswith("J085501.95"))   # background star next to the 2025-26 track
RS, DS = float(bgs["ra_pm"]), float(bgs["dec_pm"])
print("background star", bgs["source_name"], "W1", bgs["w1mpro_pm"], "W2", bgs["w2mpro_pm"])

SEL = {"A": ("4.4-5.0 um (D6)", (lam >= 4.4) & (lam <= 5.01)), "B": ("4.0-5.0 um", (lam >= 4.0) & (lam <= 5.01)),
       "C": ("D5 only 3.8-4.4 um", det == 5), "D": ("D4 only 2.4-3.8 um (null)", det == 4), "E": ("D1-D3 0.75-2.4 um (null)", det <= 3),
       "F": ("D1-D4 0.75-3.8 um (null)", det <= 4)}


def stack(cube, idx, clip=True, ret_w=False):
    d = cube[idx].astype("f8")
    fin = np.isfinite(d)
    ww = w[idx][:, None, None] * fin
    if clip and len(idx) >= 5:
        med = np.nanmedian(d, axis=0)
        dev = np.abs(d - med)
        rej = fin & (dev > 5 * rms[idx][:, None, None]) & (dev > 0.5 * np.abs(med))
        ww = np.where(rej, 0, ww)
    d0 = np.where(fin, d, 0)
    sw = ww.sum(0)
    out = np.where(sw > 0, (ww * d0).sum(0) / np.where(sw > 0, sw, 1), np.nan)
    if ret_w:
        return out, (ww > 0).sum(0), ww
    return out, (ww > 0).sum(0)


def rob_rms(a):
    v = sigma_clip(a[np.isfinite(a)], sigma=3, maxiters=8)
    return float(mad_std(v.compressed()))


def ap_flux(img, x, y, r_px=7.5 / S3, r1=20 / S3, r2=35 / S3):
    yy, xx = np.mgrid[0:img.shape[0], 0:img.shape[1]]
    rr = np.hypot(xx - x, yy - y)
    ann = (rr > r1) & (rr < r2) & np.isfinite(img)
    if ann.sum() < 30:
        return np.nan
    b = float(np.ma.median(sigma_clip(img[ann], sigma=3)))
    m = CircularAperture((x, y), r=r_px).to_mask("exact").to_image(img.shape)
    if m is None or not np.isfinite(img[m > 0]).all():
        return np.nan
    return float((m * np.nan_to_num(img - b)).sum()) * UJ * (S3 / PIX) ** 2   # microJy inside aperture


def ap_noise(img, step=4):
    v = []
    for y in range(14, img.shape[0] - 14, step):
        for x in range(14, img.shape[1] - 14, step):
            v.append(ap_flux(img, x, y))
    v = np.array(v); v = v[np.isfinite(v)]
    c = sigma_clip(v, sigma=3, maxiters=8)
    return float(mad_std(c.compressed())), len(v)


def gfit(img, x0, y0, sig, box=7, xs=None, ys=None, free_sig=False):
    """Gaussian fit (fixed sigma unless free_sig) + constant; optional second source fixed at (xs, ys) with free flux >= 0."""
    xi, yi = int(round(x0)), int(round(y0))
    sl = (slice(yi - box, yi + box + 1), slice(xi - box, xi + box + 1))
    yy, xx = np.mgrid[sl]
    d = img[sl]
    ok = np.isfinite(d)
    def model(p):
        s = p[5] if free_sig else sig
        m = p[0] * np.exp(-0.5 * ((xx - p[1]) ** 2 + (yy - p[2]) ** 2) / s ** 2) + p[3]
        if xs is not None:
            m = m + p[4] * np.exp(-0.5 * ((xx - xs) ** 2 + (yy - ys) ** 2) / s ** 2)
        return m
    p0 = [max(np.nanmax(d), 1e-4), x0, y0, 0.0, 0.0, sig]
    lo = [0, x0 - 4, y0 - 4, -np.inf, 0, 0.5 * sig]; hi = [np.inf, x0 + 4, y0 + 4, np.inf, np.inf if xs is not None else 1e-12, 2.5 * sig]
    r = least_squares(lambda p: (model(p) - d)[ok], p0, bounds=(lo, hi))
    return r.x


def w2pix(g, ra, dec):
    x, y = g.all_world2pix(ra, dec, 0)
    return float(x), float(y)


# ---------------- PSF width of the stacks from bright isolated stars (all-epoch D6 stack, 3" grid)
iA = np.where(SEL["A"][1])[0]
allA3, nA3 = stack(cube3, iA)
sigs = []
for s in stars[:6]:
    xs_, ys_ = w2pix(G3, float(s["ra_pm"]), float(s["dec_pm"]))
    if 12 < xs_ < N3 - 12 and 12 < ys_ < N3 - 12:
        p = gfit(allA3, xs_, ys_, 1.4, box=6, free_sig=True)
        fl = p[0] * 2 * np.pi * p[5] ** 2 * UJ * (S3 / PIX) ** 2
        w2f = 171.787e6 * 10 ** (-0.4 * float(s["w2mpro_pm"]))
        print(f"star {s['source_name']} W2={float(s['w2mpro_pm']):.2f}: fitted sigma={p[5] * S3:.2f}\" (FWHM {2.3548 * p[5] * S3:.2f}\") centroid offset=({(p[1] - xs_) * -S3:+.2f},{(p[2] - ys_) * S3:+.2f})\" Gauss flux={fl:.0f} uJy vs W2 flux {w2f:.0f} uJy ratio={fl / w2f:.2f}")
        if float(s["w2mpro_pm"]) < 13.5:
            sigs.append(p[5])
SIG3 = float(np.median(sigs))
print(f"adopted stack PSF sigma = {SIG3 * S3:.2f}\" (FWHM {2.3548 * SIG3 * S3:.2f}\") on the 3.075\" grid")

# ---------------- per-epoch, per-selection measurements
res = []
stacks = {}
for key, (label, m) in SEL.items():
    for e in [0, 1, 2, 3, "all"]:
        idx = np.where(m & ((ep == e) if e != "all" else True))[0]
        if len(idx) == 0:
            continue
        s6, n6 = stack(cube6, idx); s3, n3 = stack(cube3, idx)
        stacks[(key, e)] = (s6, s3, idx)
        mm = float(np.mean(mjd[idx])); rp, dp = predict(mm)
        x6, y6 = w2pix(G6, rp, dp); x3, y3 = w2pix(G3, rp, dp)
        r6 = rob_rms(s6); r3 = rob_rms(s3)
        xi, yi = int(round(x6)), int(round(y6))
        pk = float(np.nanmax(s6[yi - 1:yi + 2, xi - 1:xi + 2]))
        apf = ap_flux(s3, x3, y3); apn, nap = ap_noise(s3)
        d = dict(sel=key, label=label, epoch=e, n=len(idx), mjd=mm, date=Time(mm, format="mjd").iso[:10], ra_pred=rp, dec_pred=dp,
                 rms6_uJy=r6 * UJ, peak6_uJy=pk * UJ, snr_peak=pk / r6, ap_uJy=apf, ap_noise_uJy=apn, snr_ap=apf / apn,
                 lam_min=float(lam[idx].min()), lam_max=float(lam[idx].max()))
        res.append(d)
        print(f"[{key}] {label:26s} epoch {str(e):3s} N={len(idx):3d} {d['date']} rms={r6 * UJ:6.1f} uJy/pix  peak@pred={pk * UJ:7.1f} uJy/pix  S/N_peak={pk / r6:5.1f} | ap(r=7.5\")={apf:7.1f} +- {apn:5.1f} uJy  S/N_ap={apf / apn:5.1f}")
json.dump(res, open(OUT + "stack_snr.json", "w"), indent=1)

# ---------------- centroids per epoch (selection A and B) with bootstrap
print("\nCentroids (3.075\" grid). Offsets are EAST/NORTH in arcsec relative to the fixed centre RA0,DEC0.")
xs3, ys3 = w2pix(G3, RS, DS)
rng = np.random.default_rng(1)
cent = {}
for key in ("A", "B"):
    for e in [0, 1, 2, 3, "all"]:
        if (key, e) not in stacks:
            continue
        s6, s3, idx = stacks[(key, e)]
        mm = float(np.mean(mjd[idx])); rp, dp = predict(mm); x3, y3 = w2pix(G3, rp, dp)
        _, _, ww = stack(cube3, idx, ret_w=True)
        d0 = np.nan_to_num(cube3[idx].astype("f8"))
        def fits2(img):
            p1 = gfit(img, x3, y3, SIG3)
            p2 = gfit(img, x3, y3, SIG3, xs=xs3, ys=ys3)
            return p1, p2
        p1, p2 = fits2(s3)
        bs1, bs2 = [], []
        for b in range(150):
            j = rng.integers(0, len(idx), len(idx))
            sw = ww[j].sum(0)
            img = np.where(sw > 0, (ww[j] * d0[j]).sum(0) / np.where(sw > 0, sw, 1), np.nan)
            try:
                q1, q2 = fits2(img); bs1.append(q1[:3]); bs2.append(list(q2[:3]) + [q2[4]])
            except Exception:
                pass
        bs1, bs2 = np.array(bs1), np.array(bs2)
        toE = lambda x: -(x - (N3 - 1) / 2) * S3
        toN = lambda y: (y - (N3 - 1) / 2) * S3
        k = 2 * np.pi * SIG3 ** 2 * UJ * (S3 / PIX) ** 2
        c = dict(pred=(toE(x3), toN(y3)), one=(toE(p1[1]), toN(p1[2])), one_err=(bs1[:, 1].std() * S3, bs1[:, 2].std() * S3),
                 two=(toE(p2[1]), toN(p2[2])), two_err=(bs2[:, 1].std() * S3, bs2[:, 2].std() * S3),
                 flux_one=p1[0] * k, flux_one_err=bs1[:, 0].std() * k, flux_two=p2[0] * k, flux_two_err=bs2[:, 0].std() * k,
                 star_flux=p2[4] * k, star_flux_err=bs2[:, 3].std() * k, n=len(idx), mjd=mm)
        cent[(key, e)] = c
        print(f"[{key}] epoch {str(e):3s} N={len(idx):3d}: predicted (E,N)=({c['pred'][0]:+6.2f},{c['pred'][1]:+6.2f})  1-src fit=({c['one'][0]:+6.2f}+-{c['one_err'][0]:.2f},{c['one'][1]:+6.2f}+-{c['one_err'][1]:.2f}) flux={c['flux_one']:.0f}+-{c['flux_one_err']:.0f} uJy | 2-src fit=({c['two'][0]:+6.2f}+-{c['two_err'][0]:.2f},{c['two'][1]:+6.2f}+-{c['two_err'][1]:.2f}) flux={c['flux_two']:.0f}+-{c['flux_two_err']:.0f} star={c['star_flux']:.0f}+-{c['star_flux_err']:.0f} uJy")
print(f"background star position (E,N) = ({-(xs3 - (N3 - 1) / 2) * S3:+.2f},{(ys3 - (N3 - 1) / 2) * S3:+.2f})")
for key in ("A", "B"):
    for a, b in [(0, 1), (1, 3), (0, 3), (1, 2)]:
        if (key, a) in cent and (key, b) in cent:
            ca, cb = cent[(key, a)], cent[(key, b)]
            for nm in ("one", "two"):
                dE = cb[nm][0] - ca[nm][0]; dN = cb[nm][1] - ca[nm][1]
                eE = np.hypot(cb[nm + "_err"][0], ca[nm + "_err"][0]); eN = np.hypot(cb[nm + "_err"][1], ca[nm + "_err"][1])
                pE = cb["pred"][0] - ca["pred"][0]; pN = cb["pred"][1] - ca["pred"][1]
                print(f"[{key}] shift epoch {a}->{b} ({nm}-source fit): measured dE={dE:+.2f}+-{eE:.2f} dN={dN:+.2f}+-{eN:.2f} arcsec ; predicted dE={pE:+.2f} dN={pN:+.2f}")
json.dump({f"{k[0]}_{k[1]}": v for k, v in cent.items()}, open(OUT + "centroids.json", "w"), indent=1)

# ---------------- co-moving stack (every exposure re-centred on the predicted position)
iB = np.where(SEL["B"][1])[0]
for key, idx in (("A", iA), ("B", iB)):
    cm, ncm = stack(cubeM, idx)
    r = rob_rms(cm); c0 = (NM - 1) // 2
    pk = float(np.nanmax(cm[c0 - 2:c0 + 3, c0 - 2:c0 + 3]))
    yy, xx = np.mgrid[0:NM, 0:NM]
    print(f"co-moving stack sel {key}: N={len(idx)} rms={r * UJ:.1f} uJy/pix(native-equivalent) peak near centre={pk * UJ:.1f} S/N_peak={pk / r:.1f}")
    stacks[("CM" + key, "all")] = (None, cm, idx)

# =============================================================== FIGURES
def ext(n, s):
    h = n * s / 2.0
    return [h, -h, -h, h]   # east left


def mark(ax, e_list, cross_ep=None, lw=1.6, star=True, zoom=60):
    for e in e_list:
        m = mjd[ep == e].mean(); rp, dp = predict(m); E, Nn = offset_arcsec(rp, dp, RA0, DEC0)
        col = "cyan" if e == cross_ep else "magenta"
        g, L = (7, 16) if e == cross_ep else (0, 0)
        if e == cross_ep:
            ax.plot([E + g, E + L], [Nn, Nn], color=col, lw=lw); ax.plot([E - g, E - L], [Nn, Nn], color=col, lw=lw)
            ax.plot([E, E], [Nn + g, Nn + L], color=col, lw=lw); ax.plot([E, E], [Nn - g, Nn - L], color=col, lw=lw)
    if star:
        Es, Ns = offset_arcsec(RS, DS, RA0, DEC0)
        ax.add_patch(plt.Circle((Es, Ns), 4.0, fill=False, color="yellow", lw=1.0, ls=":"))
    ax.set_xlim(zoom, -zoom); ax.set_ylim(-zoom, zoom)


def catmarks(ax, zoom, w2lim=16.5):
    for s in cat:
        try:
            w2 = float(s["w2mpro_pm"])
        except Exception:
            continue
        E, Nn = offset_arcsec(float(s["ra_pm"]), float(s["dec_pm"]), RA0, DEC0)
        if abs(E) < zoom and abs(Nn) < zoom and w2 < w2lim and not s["source_name"].startswith("J085506.91"):
            ax.plot(E, Nn, marker="o", ms=9, mfc="none", mec="orange", mew=0.7, alpha=0.8)


def daterange(idx):
    return f"{Time(mjd[idx].min(), format='mjd').iso[:10]}..{Time(mjd[idx].max(), format='mjd').iso[5:10]}"


# Figure 1: grid of per-epoch stacks, identical stretch within a row
rowsel = ["A", "B", "C", "D", "E"]
fig, axs = plt.subplots(len(rowsel), 5, figsize=(25, 5 * len(rowsel)))
for i, key in enumerate(rowsel):
    ref = stacks[(key, 1)][1]
    r = rob_rms(ref) * UJ
    vmin, vmax = -3 * r, 12 * r
    for j, e in enumerate([0, 1, 2, 3, "all"]):
        ax = axs[i, j]
        if (key, e) not in stacks:
            ax.set_axis_off(); ax.set_title(f"{SEL[key][0]} | epoch {e}: no exposures"); continue
        s6, s3, idx = stacks[(key, e)]
        ax.imshow(s3 * UJ, origin="lower", extent=ext(N3, S3), cmap="gray", vmin=vmin, vmax=vmax, interpolation="nearest")
        mark(ax, [0, 1, 2, 3] if e == "all" else [e], cross_ep=(1 if e == "all" else e))
        catmarks(ax, 60)
        ax.set_title(f"{SEL[key][0]} | epoch {e} {daterange(idx)}\nN={len(idx)} exp, stretch {vmin:.0f}..{vmax:.0f} uJy/pix", fontsize=11)
        if j == 0:
            ax.set_ylabel("arcsec north")
        if i == len(rowsel) - 1:
            ax.set_xlabel("arcsec east of fixed centre")
fig.suptitle("WISE 0855 field, SPHEREx DR1 per-epoch stacks (N up, E left; 3.075\" grid). Cyan cross-hair = predicted position (K21 PM+parallax). "
             "Yellow dotted = background star CatWISE J085501.95-071428.2. Orange rings = CatWISE W2<16.5", fontsize=13)
fig.tight_layout(rect=[0, 0, 1, 0.97]); fig.savefig(OUT + "fig1_epoch_grid.png", dpi=70); plt.close(fig)

# Figure 2: blink pair epoch 1 vs 3 (sel A) + difference + red/cyan
for key in ("A", "B"):
    a = stacks[(key, 1)][1] * UJ; b = stacks[(key, 3)][1] * UJ
    r = max(rob_rms(a), rob_rms(b))
    vmin, vmax = -3 * r, 14 * r
    fig, axs = plt.subplots(1, 4, figsize=(28, 7.6))
    Z = 40
    for ax, im, e in ((axs[0], a, 1), (axs[1], b, 3)):
        ax.imshow(im, origin="lower", extent=ext(N3, S3), cmap="gray", vmin=vmin, vmax=vmax, interpolation="nearest")
        mark(ax, [e], cross_ep=e, zoom=Z); catmarks(ax, Z)
        idx = stacks[(key, e)][2]
        ax.set_title(f"epoch {e}: {daterange(idx)}  {SEL[key][0]}  N={len(idx)}\nstretch {vmin:.0f}..{vmax:.0f} uJy/pix", fontsize=12)
    d = b - a
    axs[2].imshow(d, origin="lower", extent=ext(N3, S3), cmap="RdBu_r", vmin=-8 * r, vmax=8 * r, interpolation="nearest")
    mark(axs[2], [1], cross_ep=1, zoom=Z); mark(axs[2], [3], cross_ep=3, zoom=Z)
    axs[2].set_title("difference: epoch 3 minus epoch 1 (red = brighter in 2026)\nboth predicted positions cross-haired", fontsize=12)
    norm = lambda x: np.clip((np.nan_to_num(x) - vmin) / (vmax - vmin), 0, 1)
    rgb = np.dstack([norm(a), norm(b), norm(b)])
    axs[3].imshow(rgb, origin="lower", extent=ext(N3, S3), interpolation="nearest")
    mark(axs[3], [1], cross_ep=1, zoom=Z, star=True)
    axs[3].set_title("two-epoch composite: RED = epoch 1 (Nov 2025), CYAN = epoch 3 (Apr-May 2026)\nstationary = white; mover = red (east) / cyan (west) fringe", fontsize=12)
    for ax in axs:
        ax.set_xlabel("arcsec east")
    axs[0].set_ylabel("arcsec north")
    fig.tight_layout(); fig.savefig(OUT + f"fig2_blink_diff_composite_{key}.png", dpi=70); plt.close(fig)

# Figure 3: context - challenge coordinates vs where the object is now (native 6.15" grid, full 400" field)
fig, axs = plt.subplots(1, 3, figsize=(27, 9.4))
for ax, key, ttl in ((axs[0], "A", "ALL epochs, 4.4-5.0 um (D6)"), (axs[1], "B", "ALL epochs, 4.0-5.0 um"), (axs[2], "D", "ALL epochs, D4 2.4-3.8 um")):
    s6, s3, idx = stacks[(key, "all")]
    r = rob_rms(s6) * UJ
    ax.imshow(s6 * UJ, origin="lower", extent=ext(N6, PIX), cmap="gray", vmin=-3 * r, vmax=15 * r, interpolation="nearest")
    Ec, Nc = offset_arcsec(RA_CH, DEC_CH, RA0, DEC0)
    ax.add_patch(plt.Circle((Ec, Nc), 12, fill=False, color="red", lw=2)); ax.text(Ec, Nc + 16, "challenge coords\n(WISE 2010.3)", color="red", ha="center", fontsize=11)
    tr = [offset_arcsec(*predict(Time(y, format="jyear").mjd), RA0, DEC0) for y in np.arange(2010.3, 2026.5, 0.05)]
    ax.plot([p[0] for p in tr], [p[1] - 0 for p in tr], color="cyan", lw=0.8, alpha=0.7)
    E1, N1 = offset_arcsec(*predict(mjd[ep == 1].mean()), RA0, DEC0)
    ax.add_patch(plt.Circle((E1, N1), 12, fill=False, color="cyan", lw=2)); ax.text(E1, N1 - 26, "predicted 2025.85", color="cyan", ha="center", fontsize=11)
    ax.set_xlim(200, -200); ax.set_ylim(-200, 200)
    ax.set_title(f"{ttl}: N={len(idx)} exposures, stretch {-3 * r:.0f}..{15 * r:.0f} uJy/pix\ncyan line = predicted track 2010.3 -> 2026.5", fontsize=12)
    ax.set_xlabel("arcsec east of fixed centre")
axs[0].set_ylabel("arcsec north")
fig.tight_layout(); fig.savefig(OUT + "fig3_context_challenge_vs_now.png", dpi=70); plt.close(fig)

# Figure 4: fixed-sky all-epoch stack vs co-moving stack, plus D4 control, zoomed
fig, axs = plt.subplots(1, 4, figsize=(28, 7.6))
a = stacks[("A", "all")][1] * UJ; r = rob_rms(a)
vmin, vmax = -3 * r, 20 * r
axs[0].imshow(a, origin="lower", extent=ext(N3, S3), cmap="gray", vmin=vmin, vmax=vmax, interpolation="nearest")
mark(axs[0], [0, 1, 2, 3], cross_ep=1, zoom=40); catmarks(axs[0], 40)
axs[0].set_title(f"FIXED-sky stack, all 4 epochs, 4.4-5.0 um, N={len(iA)}\n(W2-like; cross-hair = 2025.85 prediction)", fontsize=12)
cm = stacks[("CMA", "all")][1] * UJ
E1, N1 = offset_arcsec(*predict(mjd[ep == 1].mean()), RA0, DEC0)
hm = NM * S3 / 2
axs[1].imshow(cm, origin="lower", extent=[E1 + hm, E1 - hm, N1 - hm, N1 + hm], cmap="gray", vmin=vmin, vmax=vmax, interpolation="nearest")
mark(axs[1], [1], cross_ep=1, zoom=40, star=False)
axs[1].set_title(f"CO-MOVING stack (each exposure centred on predicted position)\n4.4-5.0 um, N={len(iA)}", fontsize=12)
cmB = stacks[("CMB", "all")][1] * UJ
axs[2].imshow(cmB, origin="lower", extent=[E1 + hm, E1 - hm, N1 - hm, N1 + hm], cmap="gray", vmin=vmin, vmax=vmax, interpolation="nearest")
mark(axs[2], [1], cross_ep=1, zoom=40, star=False)
axs[2].set_title(f"CO-MOVING stack 4.0-5.0 um, N={len(iB)}", fontsize=12)
d4 = stacks[("D", "all")][1] * UJ; r4 = rob_rms(d4)
axs[3].imshow(d4, origin="lower", extent=ext(N3, S3), cmap="gray", vmin=-3 * r4, vmax=20 * r4, interpolation="nearest")
mark(axs[3], [0, 1, 2, 3], cross_ep=1, zoom=40); catmarks(axs[3], 40)
axs[3].set_title(f"CONTROL: D4 2.4-3.8 um all epochs, N={len(stacks[('D', 'all')][2])}\nstretch {-3 * r4:.0f}..{20 * r4:.0f} uJy/pix: only the background star", fontsize=12)
for ax in axs:
    ax.set_xlabel("arcsec east")
fig.tight_layout(); fig.savefig(OUT + "fig4_fixed_vs_comoving.png", dpi=70); plt.close(fig)

# GIF blink (epochs 0..3, selection A), upscaled nearest-neighbour
try:
    from PIL import Image, ImageDraw
    frames = []
    a1 = stacks[("A", 1)][1] * UJ; r = rob_rms(a1); vmin, vmax = -3 * r, 14 * r
    c0 = (N3 - 1) // 2; hz = 14
    for e in (0, 1, 2, 3):
        s3 = stacks[("A", e)][1] * UJ
        sub = s3[c0 - hz:c0 + hz + 1, c0 - hz:c0 + hz + 1][::-1]
        g = (np.clip((np.nan_to_num(sub) - vmin) / (vmax - vmin), 0, 1) * 255).astype("u1")
        im = Image.fromarray(g).resize((580, 580), Image.NEAREST).convert("RGB")
        dr = ImageDraw.Draw(im)
        idx = stacks[("A", e)][2]
        dr.text((8, 8), f"epoch {e}  {daterange(idx)}  4.4-5.0um  N={len(idx)}", fill=(0, 255, 255))
        frames.append(im)
    frames[0].save(OUT + "blink_A_epochs0123.gif", save_all=True, append_images=frames[1:], duration=700, loop=0)
    frames[1].save(OUT + "blink_A_epochs13.gif", save_all=True, append_images=[frames[3]], duration=600, loop=0)
except Exception as ex:
    print("gif failed", ex)
print("figures written to", OUT)
