"""Step d + f: per-epoch spectra, epoch ratios, light curves, halo (PSF-wing) photometry for saturated cores.

Usage: python 05_analysis.py "RW Aur"
Reads phot_<tag>.json (04_phot.py) and the cached cutouts. Writes PNGs + summary_<tag>.json.
"""
import sys, json, os
from common import *  # noqa
import photlib as P
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from astropy.time import Time

name = sys.argv[1]
tag = name.replace(" ", "_")
SIMBAD = {"RW Aur": (76.95652603458333, 30.401438173888888), "R Dra": (248.16761083295, 66.75497941722)}
CAT = {  # 2MASS PSC (IRSA fp_psc) magnitudes of the target itself, for reference only (non-simultaneous!)
    "RW Aur": {"J": 8.378, "H": 7.621, "K": 7.020},
    "R Dra": {"J": 3.863, "H": 3.125, "K": 2.438},
}
EPCOL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]  # categorical slots 1..5, fixed order by visit
INK, MUTED, SURF, GRID = "#0b0b0b", "#52514e", "#fcfcfb", "#e1e0d9"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": "#c3c2b7", "text.color": INK, "axes.labelcolor": MUTED,
                     "xtick.color": MUTED, "ytick.color": MUTED, "figure.facecolor": SURF, "axes.facecolor": SURF,
                     "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.spines.top": False,
                     "axes.spines.right": False, "legend.frameon": False})


def date(mjd):
    return Time(mjd, format="mjd").iso[:10]


ph = json.load(open(os.path.join(HERE, f"phot_{tag}.json")))
t = ph["target"]

# ------------------------------------------------------------------ halo (PSF wing) photometry from the cutouts
rows, cuts = load_cuts(name, verbose=False)
ra0, dec0 = SIMBAD[name]
n = 2 * HALF + 1
yy, xx = np.mgrid[0:n, 0:n]
halo = {}
for c in cuts:
    x, y = [float(v) for v in c["wcs"].all_world2pix(ra0, dec0, 0)]
    sub = c["image"].astype("f8") - c["zodi"]
    rr = np.hypot(xx - x, yy - y)
    good = np.isfinite(sub) & ((c["flags"] & P.BADBITS) == 0)
    a = sub[(rr >= 8) & (rr <= 12) & good]
    o = sub[(rr >= 21) & good]
    if len(a) < 60 or len(o) < 100:
        continue
    sky = np.median(o)
    sig = 1.4826 * np.median(np.abs(a - np.median(a)))
    halo[(c["obs_id"], c["det"])] = (float(np.median(a) - sky), float(1.2533 * sig / np.sqrt(len(a))), float(sky), len(a))
for p in t:
    h = halo.get((p["obs_id"], p["det"]))
    p["halo"], p["halo_err"], p["outer_sky"] = (h[0], h[1], h[2]) if h else (float("nan"),) * 3
    p["fcor"] = p["flux_mJy"] / p["ee2"]
    p["q"] = ("nan" if p["nan_ap"] > 0 else "overflow" if p["n_overflow"] > 0 else
              "sur_error" if p["n_sur_error"] > 0 else "otherbad" if p["n_bad_ap"] > 0 else "clean")

A = {k: np.array([p[k] for p in t]) for k in ("lam", "fcor", "flux_mJy", "err_mJy", "mjd", "epoch", "det", "halo", "halo_err", "peak")}
Q = np.array([p["q"] for p in t])
eps = sorted(set(int(e) for e in A["epoch"]))
summary = {"name": name, "n_exposures": len(t), "epochs": {}, "quality_by_det": {}}
print(f"== {name}: {len(t)} exposures")
for e in eps:
    m = A["epoch"] == e
    summary["epochs"][e] = {"n": int(m.sum()), "from": date(A["mjd"][m].min()), "to": date(A["mjd"][m].max()),
                            "lam_min": float(A["lam"][m].min()), "lam_max": float(A["lam"][m].max()),
                            "per_det": {int(d): int((m & (A["det"] == d)).sum()) for d in range(1, 7)}}
    print(f"  visit {e}: n={m.sum()} {date(A['mjd'][m].min())}..{date(A['mjd'][m].max())} lam {A['lam'][m].min():.2f}-{A['lam'][m].max():.2f} per-det {summary['epochs'][e]['per_det']}")
for d in range(1, 7):
    m = A["det"] == d
    qc = {q: int((m & (Q == q)).sum()) for q in ("clean", "overflow", "sur_error", "otherbad", "nan")}
    summary["quality_by_det"][d] = qc
    print(f"  D{d}: {qc}")
print("  overall:", {q: int((Q == q).sum()) for q in ("clean", "overflow", "sur_error", "otherbad", "nan")})

# which measurement do we trust? aperture if the core has no NaN; halo otherwise
USE_HALO = (Q == "nan").mean() > 0.5
val = A["halo"] if USE_HALO else A["fcor"]
verr = A["halo_err"] if USE_HALO else A["err_mJy"]
ylab = "PSF-wing surface brightness, r = 8-12 px  [MJy/sr]" if USE_HALO else "flux density, r = 2 px aperture / EE  [mJy]"
usable = np.isfinite(val) & (val > 0) & (np.ones(len(val), bool) if USE_HALO else (Q != "nan"))
summary["method"] = "halo" if USE_HALO else "aperture"
summary["usable_fraction"] = float(usable.mean())


def ref_interp(lam, det, mref):
    """Interpolate the reference-visit spectrum (same detector) at wavelengths lam."""
    out = np.full(len(lam), np.nan)
    for d in range(1, 7):
        r = mref & (A["det"] == d) & usable
        s = (A["det"] == d)
        if r.sum() < 3:
            continue
        o = np.argsort(A["lam"][r])
        lr, fr = A["lam"][r][o], val[r][o]
        inside = s & (lam >= lr[0]) & (lam <= lr[-1])
        out[inside] = np.interp(lam[inside], lr, fr)
    return out


# ------------------------------------------------------------------ figure 1: spectrum per visit
fig, ax = plt.subplots(figsize=(13, 6.2))
for i, e in enumerate(eps):
    m = (A["epoch"] == e) & usable
    cl = m & (Q == "clean")
    ax.errorbar(A["lam"][m & ~cl], val[m & ~cl], yerr=verr[m & ~cl], fmt="o", ms=4.5, mfc="none", mec=EPCOL[i], ecolor=EPCOL[i],
                elinewidth=0.8, lw=0, mew=1.0)
    ax.errorbar(A["lam"][cl], val[cl], yerr=verr[cl], fmt="o", ms=4.5, color=EPCOL[i], ecolor=EPCOL[i], elinewidth=0.8, lw=0,
                label=f"visit {e}: {summary['epochs'][e]['from']} .. {summary['epochs'][e]['to']}  (N={int(m.sum())})")
if not USE_HALO:
    for b, mag in CAT[name].items():
        lam_b, zp = P.ZP[b]
        ax.plot([lam_b], [zp * 10 ** (-0.4 * mag) * 1e3], marker="D", ms=8, color=INK, lw=0,
                label="2MASS J/H/Ks (1997-2000, not simultaneous)" if b == "J" else None)
for d, edge in enumerate((1.105, 1.635, 2.42, 3.815, 4.415)):
    ax.axvline(edge, color="#c3c2b7", lw=0.8, ls=":")
ax.set_yscale("log")
ax.set_xlabel("wavelength at the target pixel  [micron]   (dotted lines: detector boundaries D1|D2|D3|D4|D5|D6)")
ax.set_ylabel(ylab)
ax.set_title(f"{name}: one point per 113 s exposure, coloured by visit. Filled = core unflagged; open = OVERFLOW/SUR_ERROR in the core",
             fontsize=10.5, loc="left")
ax.legend(loc="best", fontsize=9)
fig.tight_layout()
f1 = os.path.join(HERE, f"spec_{tag}_per_visit.png")
fig.savefig(f1, dpi=120)
plt.close(fig)
print("wrote", f1)

# ------------------------------------------------------------------ figure 2: ratio to the reference visit
REF = eps[0]
mref = A["epoch"] == REF
refv = ref_interp(A["lam"], A["det"], mref)
ratio = val / refv
fig, ax = plt.subplots(figsize=(13, 5.6))
ax.axhline(1.0, color="#898781", lw=1.0)
summary["ratio_vs_visit0"] = {}
for i, e in enumerate(eps):
    if e == REF:
        continue
    m = (A["epoch"] == e) & usable & np.isfinite(ratio)
    ax.plot(A["lam"][m], ratio[m], "o", ms=4.5, color=EPCOL[i], lw=0,
            label=f"visit {e} ({summary['epochs'][e]['from']}..{summary['epochs'][e]['to']}) / visit {REF}")
    summary["ratio_vs_visit0"][e] = {}
    for d in range(1, 7):
        md = m & (A["det"] == d)
        if md.sum() < 3:
            continue
        r = ratio[md]
        med = float(np.median(r))
        sc = float(1.4826 * np.median(np.abs(r - med)))
        summary["ratio_vs_visit0"][e][d] = {"median": med, "robust_sigma": sc, "n": int(md.sum()),
                                           "lam": [float(A["lam"][md].min()), float(A["lam"][md].max())]}
        print(f"  ratio visit {e}/visit {REF}  D{d} ({A['lam'][md].min():.2f}-{A['lam'][md].max():.2f} um): median {med:.3f}  robust sigma {sc:.3f}  N={md.sum()}"
              f"  -> {-2.5*np.log10(med):+.3f} mag")
for edge in (1.105, 1.635, 2.42, 3.815, 4.415):
    ax.axvline(edge, color="#c3c2b7", lw=0.8, ls=":")
ax.set_xlabel("wavelength  [micron]")
ax.set_ylabel(f"flux ratio to visit {REF} (interpolated in wavelength, same detector)")
lo, hi = np.nanpercentile(ratio[usable & np.isfinite(ratio) & ~mref], [1, 99]) if (usable & np.isfinite(ratio) & ~mref).any() else (0.5, 1.5)
ax.set_ylim(max(0, lo - 0.1 * (hi - lo)), hi + 0.1 * (hi - lo))
ax.set_title(f"{name}: change between visits, per exposure ({'PSF-wing' if USE_HALO else 'aperture'} photometry). 1.0 = no change", fontsize=10.5, loc="left")
ax.legend(loc="best", fontsize=9)
fig.tight_layout()
f2 = os.path.join(HERE, f"ratio_{tag}.png")
fig.savefig(f2, dpi=120)
plt.close(fig)
print("wrote", f2)

# ------------------------------------------------------------------ figure 3: light curves in wavelength bins (small multiples)
BINS = [("0.75-1.10 um (D1)", 0.75, 1.10), ("1.65-2.40 um (D3)", 1.65, 2.40), ("2.45-3.80 um (D4)", 2.45, 3.80), ("3.85-5.00 um (D5+D6)", 3.85, 5.00)]
# normalise by the all-visit median spectrum in each detector so that different wavelengths can share one panel
fig, axs = plt.subplots(len(BINS), 1, figsize=(13, 10.5), sharex=True)
summary["lightcurve"] = {}
for ax, (lab, l0, l1) in zip(axs, BINS):
    mb = usable & (A["lam"] >= l0) & (A["lam"] < l1) & np.isfinite(ratio)
    ax.axhline(1.0, color="#898781", lw=1.0)
    summary["lightcurve"][lab] = []
    for i, e in enumerate(eps):
        m = mb & (A["epoch"] == e)
        if not m.any():
            continue
        ax.plot(A["mjd"][m], ratio[m], "o", ms=4, color=EPCOL[i], lw=0, label=f"visit {e}")
    # 10-day bins
    if mb.any():
        t0 = np.floor(A["mjd"][mb].min() / 10) * 10
        for tb in np.arange(t0, A["mjd"][mb].max() + 10, 10):
            m = mb & (A["mjd"] >= tb) & (A["mjd"] < tb + 10)
            if m.sum() >= 3:
                med = float(np.median(ratio[m]))
                se = float(1.4826 * np.median(np.abs(ratio[m] - med)) / np.sqrt(m.sum()))
                ax.errorbar([A["mjd"][m].mean()], [med], yerr=[se], fmt="s", ms=7, mfc="none", mec=INK, ecolor=INK, lw=0, elinewidth=1.2)
                summary["lightcurve"][lab].append({"mjd": float(A["mjd"][m].mean()), "date": date(A["mjd"][m].mean()), "rel": med, "se": se, "n": int(m.sum())})
    ax.set_ylabel("flux / visit-0 spectrum")
    ax.set_title(lab + "   (dots: single exposures; open squares: 10-day medians)", fontsize=10, loc="left")
axs[0].legend(loc="best", fontsize=9, ncol=len(eps))
tk = axs[-1].get_xticks()
axs[-1].set_xticks(tk)
axs[-1].set_xticklabels([date(v)[:7] for v in tk])
axs[-1].set_xlim(A["mjd"].min() - 10, A["mjd"].max() + 10)
axs[-1].set_xlabel("date (UTC)")
fig.suptitle(f"{name}: light curve relative to the visit-{REF} spectrum at the same wavelength ({'PSF-wing' if USE_HALO else 'aperture'} photometry)", fontsize=11, x=0.01, ha="left")
fig.tight_layout(rect=(0, 0, 1, 0.97))
f3 = os.path.join(HERE, f"lightcurve_{tag}.png")
fig.savefig(f3, dpi=120)
plt.close(fig)
print("wrote", f3)
for lab, v in summary["lightcurve"].items():
    print("  LC", lab, [(x["date"], round(x["rel"], 3), round(x["se"], 3), x["n"]) for x in v])

# aperture vs halo consistency (PSF-wing fraction) for exposures where both exist
both = np.isfinite(A["halo"]) & (A["fcor"] > 0) & (Q != "nan")
if both.sum() > 10:
    hf = A["halo"][both] / A["fcor"][both]
    for d in range(1, 7):
        md = A["det"][both] == d
        if md.sum() > 2:
            print(f"  wing/aperture D{d}: median {np.median(hf[md]):.3e} MJy/sr per mJy, robust sigma {1.4826*np.median(np.abs(hf[md]-np.median(hf[md]))):.2e} (N={md.sum()})")
    summary["wing_per_mJy"] = {int(d): float(np.median(hf[A["det"][both] == d])) for d in range(1, 7) if (A["det"][both] == d).sum() > 2}
json.dump(summary, open(os.path.join(HERE, f"summary_{tag}.json"), "w"), indent=1)
np.savez(os.path.join(HERE, f"series_{tag}.npz"), q=Q, ratio=ratio, val=val, verr=verr, usable=usable, **A)
