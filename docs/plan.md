> **Note for readers (14 Nov, 13:45).** This is the build plan approved on Saturday morning, kept verbatim as the record of what was decided and why.
> Three things have changed since it was written:
> - **Folders.** The repo follows the team's layout: `apps/api` is `api/`, `apps/web` is `web/`, `spec/CONTRACT.md` is `docs/CONTRACT_FIELDS.md` (machine-readable parts in `docs/contract/`), fixtures are in `cache/fixtures/`, and the morning prototypes named below as `scratchpad/...` are in `science/prototypes/`.
> - **Schedule.** The early gates slipped by about ninety minutes; the current gates are in `CLAUDE.md` section 11.
> - **Time bins.** A visit is split only when it exceeds 60 days (not 14), so a normal visit keeps all its wavelengths in one frame; `docs/contract.md` section 3 is authoritative. npm is used instead of pnpm.

# Tombaugh — spot-the-difference for the SPHEREx sky

Plan for NASA Space Apps 2026, challenge "Planet X and SPHEREx", HackAthlone (TUS Athlone).
Status: research and live data tests done; three independent red-team reviews (science, delivery, judging) applied; nothing implemented; repo untouched. Sat 14 Nov 2026.

## 1. Context

**The ask.** A public web tool: enter RA/Dec, see SPHEREx images of that patch "like a little video", spot what moves or changes. Test on Barnard's Star, Epsilon Indi B, WISE 0855, RW Aurigae, R Draconis. Eight optional considerations: easy updating, creative use of 102 bands (per-detector stacks), spectra on the fly, add/subtract epochs, FOV choice, Gaia/WISE overlays, URL coordinates, flags, Astropy/Aladin. NASA names WiseView as the model.

**The clock (Irish time).** Work opened Sat 09:00 (first commit 10:04; keep history unsquashed). Sun 06:00 team confirmation in person at the Atrium X desk, or we are not scheduled. Sun 11:30–16:30 pitches: 3 min + 2 min questions, hard stop; whether a live demo is allowed is unpublished. Sun 23:59 NASA portal closes. Real build window: ~24 h to the pitch.

**Judging.** Five criteria, 1–5 each, same rubric locally and globally: Impact, Creativity, Validity, Relevance, Presentation. The 2025 local jury had no astronomer and rewarded "a clear user" and "a demo you could see". Global judges score mainly the project page, a demo (≤30 s video or ≤7 slides; longer = ineligible) and the live link, reopened until 26 Jan 2027. Best-fit awards: global "Best Use of Data", local "Best Use of Open Data".

**The field.** 117+ public "spherex" repos since 13 Nov; at least eight claim live coordinate search, blink, subtraction, Gaia overlay and spectra; some began weeks early. Two (muninn, pythonhack000) already place a 2010 AllWISE frame beside SPHEREx and tell the Pluto blink-comparator story. The repo we were pointed at (Ashhajj0) is a static bundle with cosmetic RA/Dec entry and five synthetic targets. Neither features nor the Pluto story will win. What can: five targets on real pixels with honest limits, numbers checked against Gaia, proof that strangers can use it, and craft.

## 2. Decision

Build **Tombaugh**: a blink comparator for a telescope that sees every star in a different colour on every exposure. Named for Clyde Tombaugh, who found Pluto while hunting for Planet X by flipping between two photographs. We never claim to be the only tool doing any one thing; we claim to do it correctly and show the evidence.

1. **Correct blinking.** Each SPHEREx exposure images a sky position at one wavelength; the next, 2.15 minutes later, is one spectral channel away; consecutive visits are rolled 180°. Tombaugh rebuilds registered, north-up, wavelength-matched stacks per time bin on one brightness scale, so what blinks is the sky, not the filter.
2. **Then & Now.** SPHEREx alone spans ~1.4 years at 6.15" pixels: Barnard's Star moves 1.7 pixels. Tombaugh blinks the AllWISE coadd (2010–11) against a SPHEREx stack at nearly the same wavelengths (2.4–3.8 µm beside W1; 4.0–5.0 µm beside W2) on one grid, with smoothed 2MASS (1997–2001) for objects bright enough. This extends WiseView's idea past the end of NEOWISE in 2024. Positions are comparable between surveys; brightness is not, and the labels say so.
3. **What it is, not only that it moved.** Click an object for quick-look spectrophotometry (0.75–5 µm) at the position predicted from catalogue motion, with catalogued neighbours fitted jointly and saturation refused honestly.
4. **The coordinate trap, solved.** The challenge's own WISE 0855 coordinates are its 2010 position, 126" from where it is now. Typed coordinates are checked for fast movers that used to be there, with a one-click "it is now 126" west" jump.
5. **Honest and durable.** Dates, exposure counts, wavelength range and provenance on every frame; zero synthetic imagery; discovery at query time, so new releases need no code change; ~$0–5/month.

**Rejected.** (a) A static showcase: fails the core objective. (b) An automatic "discovery engine": the one we inspected reports motions 100× Barnard's Star; three visits cannot support it in a day. (c) A browser-only app: IRSA discovery has no CORS, FLAGS need server-side decoding, and a server caches and protects upstreams.

## 3. Evidence (measured today on real pixels unless marked)

| # | Finding | Status |
|---|---|---|
| E1 | Public images: `spherex_dr1`, `spherex_dr1_deep` (2025-04-24 → 2026-05-14) and `spherex_qr3`, `spherex_qr3_deep` (→ 2026-10-05; nominally weekly, nothing new since 29 Oct). The five targets have 3–4 visits ~6 months apart, R Dra near-continuous. | Verified |
| E2 | Pixels are in the public bucket `nasa-irsa-spherex` (us-east-1, anonymous, range requests). 66 MB files; FLAGS Rice-compressed per row; layout uniform across 48 files; wavelength table and EPSF identical per detector. | Verified |
| E3 | IRSA's cutout service returns ≥4 MB per cutout, 4–15 s each. Our range reader fetched all 258 detector-images of a 5' field in 7–9 s (image only, 116 MB) or 19–25 s (four planes, 416 MB) from the venue; 0 failures in 884 fetches. | Verified here; in-region speed is H1 |
| E4 | Registration costs 1–3 ms per frame and equals full WCS+SIP reprojection. A per-exposure cube is ~6 MB on the display grid and unbounded for deep fields, so we ship bounded stacks (§6). | Verified |
| E5 | **Barnard's Star** (3 visits): steps north by 8.2–10.4" depending on detector (10.25" predicted). Core saturated in every exposure, so position comes from the wings (residuals up to 1.4"). Field-star residuals in the difference image are 6–12% of peak. | Verified, plots inspected |
| E6 | **WISE 0855**: invisible in single frames; 4.4–5.0 µm stacks reach S/N 8–20 per visit. It is blended with a background star 4–11" away; fitted jointly, it moved 4.36 ± 0.34" west Nov 2025 → May 2026 (4.54" predicted) and 7.60 ± 0.63" in a year (7.94"). A single-source centroid is pulled ~1.5". | Verified, plots inspected |
| E7 | Below 3.8 µm only that background star is visible at the position; with it removed the target's flux is zero below 3.8 µm and ~600 µJy at 4.4–4.8 µm. | Verified (analytic star correction) |
| E8 | Catalogue positions miss today's sky: WISE 0855 is 122–130" from the challenge coordinates, Barnard 269" from J2000 (outside a 6' field), Eps Indi B 121". | Verified |
| E9 | **RW Aur**: 1.2 µm flux +35% then +51% over three visits while 4.6 µm fell 23% then 46%; six comparison stars constant to 1.5%. Core OVERFLOW-flagged: indicative only. | Verified, plot inspected |
| E10 | **R Dra**: 2,514 detector-images; core blank in 537 of 539 sampled. Only the 4–5 µm halo behaves (fades to 0.42×, partly recovers); other bands unreliable. | Verified, weak |
| E11 | Photometry of unsaturated stars vs 2MASS/AllWISE: median ratio 0.987, scatter 2.9% (6 stars, 2 fields, monochromatic interpolation). | Verified, small sample |
| E12 | A strict flag mask erases saturated stars (Barnard: OVERFLOW on the peak pixel in 88% of exposures). Onset near J,H ≈ 10, K ≈ 9.5. | Verified |
| E13 | AllWISE W2 cutout (coadd of the May and Nov 2010 passes; 383 kB, ~2 s) shows a source at WISE 0855's 2010 position and little at today's. 2MASS images are in `twomass_allsky`. | Fetch only; registration, scaling and blink untested (H2) |
| E14 | Centroid precision for an isolated source with the real ePSF is 5.9"/(S/N) per axis; real targets are worse (blends, saturation). SPHEREx alone reaches only ≳1–3"/yr. | Simulated |
| E15 | The all-sky cube, HiPS and Mosaic Tool are time-averaged; IRSA's spectrophotometry is at fixed coordinates. | Verified (docs) |
| E16 | CDS Strasbourg is down; CfA/IDIA mirrors work. IRSA SIA: ~1.6 s, no CORS; the ecliptic pole returns 29,470 rows in 31 s. | Verified |
| E17 | Venue network reset ~50% of new TLS connections to AWS/IRSA/JPL at 10:30–10:50; gone by 11:00. | Verified, intermittent |
| E18 | 350 detector-images cover interstellar comet 3I/ATLAS's track; IRSA MOST agrees. | Metadata only |

**Open hypotheses, each tied to a gate:** H1 a cold 258-exposure build on the real Fly machine, twice running, takes ≤15 s within memory. H2 Then & Now frames register and scale well enough to blink (spike by 15:00). H3 Eps Indi B (predicted unsaturated, untested) shows its ~1 px motion beside a bright primary. H4 the Cloudflare proxy passes a byte-exact binary and 100/100 requests from the venue. H5 a solar-system mover (Pluto or 3I/ATLAS) is plainly visible in single exposures (45-minute spike).

## 4. Product

One screen, keyboard-first, built around the viewport. `/` opens on a real hero sequence with one caption sentence.

### Core A — the demo path (G2, 21:00)
- **K1 Search with a fast-mover hint.** RA/Dec (decimal or sexagesimal) or a name; names centre on the position at a fixed epoch (2026.0). Typed coordinates are checked against Gaia DR3/CatWISE/SIMBAD movers (>0.3"/yr) within 6'; if one used to be there, a banner offers "now 126" west — jump". Acceptance: all five challenge strings reach their target. Solar-system names get an explanatory sentence, not a dead end.
- **K2 Live frames anywhere.** Discovery over four collections at request time. Frames are time bins: split at gaps >20 days and wherever a visit exceeds ~14 days. ≤600 exposures used, sampled deterministically, labelled "N of M". Field 6', max 10'. Honest "no coverage yet".
- **K3 Blink.** Band presets: D1–D6 (NASA's per-detector stacks), All, 4.0–5.0 µm "cold objects", and a three-colour view (red = 3.8–5.0 µm) so cold objects stand out. Space plays/pauses, ←/→ step, hold-to-flip, side-by-side, dated timeline strip, contrast and invert, cursor RA/Dec/value readout, click to recentre. One stretch per sequence. Never autoplays; ≤6 frame changes/s; 150 ms cross-fade option. Thin or partial frames (N<8 or a different detector set) are greyed.
- **K4 Then & Now** for three featured targets, shipped as dated static files from the same pipeline. Go/no-go from real frames at 15:00; fallback is linked side-by-side panels.
- **K5 Trust.** Frame label (date range, N, wavelength range, effective wavelength, "resampled, ~10" resolution"), "newest SPHEREx image" chip, provenance line.

### Core B — feature freeze at G3 (01:00)
- **K6 Difference.** B scaled to A on field stars, common wavelength bins only, shown against an error model with a fractional term so static stars stay quiet; saturated cores hatched.
- **K7 Quick-look spectrum.** Click snaps to a catalogue source. Per-exposure points plus binned points with errors, one colour per visit, time span printed. Neighbours within 15" fitted jointly. Blank core → "saturated: no reliable photometry"; OVERFLOW → hollow points, "indicative only".
- **K8 Overlays.** Gaia DR3 at each frame's date including parallax (server-computed); CatWISE neighbours at catalogue epoch.
- **K9 URL state** `?ra=&dec=&fov=&band=&mode=&frame=`; **About** on one screen: methods, limits, validation table, a "moved / varied / probably not real" guide, acknowledgements, AI use, "independent, not a NASA tool".

### Complete — in this order, after Core is green
Then & Now for any position · motion readout (per-visit centroid vs Gaia, saturated sources labelled "wings only, ±1.5"") · single-exposure-event overlay and "hours" mode · draggable wavelength window · flag overlay and exposure table · GIF export and candidate card · `embed=1` and WiseView-style hash · phone polish · 20'–30' fields.

### Showcases (only if their spike passes)
A solar-system mover followed through single exposures, built through the same pipeline with ephemeris centres: Pluto first (it makes the name pay off), else 3I/ATLAS. R Dra in 10-day bins.

### Will not build
Automatic discovery claims, accounts, any simulated sky, a general FITS viewer.

## 5. Science pipeline (defaults from the Explanatory Supplement or measured)

1. **Discover**: SIA2 on four collections (≤2 concurrent), stale-while-revalidate, de-duplicate on (obs_id, detector); validate bucket, region and key.
2. **Read**: range-read the window's rows of IMAGE and FLAGS (6 requests per exposure, 2 with cached metadata); ZODI/VARIANCE sampled sparsely; wavelength tables bundled.
3. **Prepare**: subtract the clipped median of an outer ring that excludes bright-star wings (fallback: ZODI plus one constant); mask hard defects and transients (0x3FD2CEC5) except within ~3 px of a saturated core; never mask SOURCE.
4. **Register**: pixel map from the full WCS+SIP, bilinear, north-up, 3.075"/px.
5. **Stack on the server, once**: per time bin × wavelength bin (4 per detector = 24). Samples deviating >5σ (with a 15% tolerance) from the same-detector median are excluded and counted in a "single-exposure events" plane, never silently dropped. Uniform weights for band presets, inverse-variance only for "maximum S/N". No rejection across time bins (it erases movers). Each plane records N, effective wavelength, noise, dates.
6. **Difference**: scale on field stars; `σ_D² = σ_sky² + (f·brighter)²` with f measured per pair (~0.1).
7. **Then & Now**: AllWISE W1/W2 Atlas cutouts unblurred; 2MASS smoothed to ~10" and off by default; each scaled on common unsaturated stars; centred on the track midpoint; labelled with mission, band, date range and "own stretch".
8. **Spectrum**: native pixels, epoch-propagated position, joint fit of target and catalogued neighbours (aperture r = 2 px / 0.96 as fallback), 5–9 px annulus, error `sqrt(stat² + (0.03·F)²)`.
9. **Display**: asinh with pooled limits, grey default, orange/blue for two-epoch composites, hatching for missing or saturated data.

## 6. Architecture

```
Browser — React SPA on Cloudflare Pages
  viewport (Canvas 2D) · band = weighted sum of planes · spectrum (uPlot) · overlays · URL state
        │ same-origin /api/* via a Pages Function (build-time switch to direct CORS if H4 fails)
API — FastAPI container on Fly.io, Ashburn (same metro as the data)
  GET /api/fields?ra&dec&fov  → 202 + progress while building, 200 + manifest when ready (idempotent)
  GET /api/fields/{key}/frames.bin (immutable float16 planes, gzip) · /spectrum?ra&dec
  GET /api/resolve · /api/catalogs · /api/status · /healthz (answers during builds)
        │ threaded keep-alive HTTP/1.1 pool, deadlines, jittered retries, per-host caps
Upstreams: IRSA SIA (discovery) · S3 nasa-irsa-spherex (pixels) · IRSA IBE (AllWISE, 2MASS)
           Sesame/SIMBAD mirrors (CfA → IDIA) · Gaia DR3 (ARI TAP → GAVO) · CatWISE (IRSA SCS)
Cache: size-capped content-addressed files on a Fly volume; featured targets also ship as static files
```

- **Bounded payload.** Planes = time bins × 24 wavelength bins (Then & Now planes use the same slots): ~2 MB at 6' for three visits whatever the exposure count; bins coarsen for deep fields. Band changes, blinking and differences need no round trip. No web worker (0.35 ms per 512² frame).
- **One idempotent GET, no job table.** One build at a time, queue of 8, 429 beyond; unpolled builds cancel after 20 s; labelled partial results at 120 s.
- **The demo and the judged link cannot go cold.** Hero and featured targets are static files in the Pages deployment, produced by the production pipeline and dated; discovery is stale-on-error; cached and static responses are exempt from rate limits (the whole venue shares one address).
- **Hosting.** Fly.io `iad`, one 2 GB machine and a 3 GB volume, size fixed before submission. Needs one payment card: go/no-go at 13:00. No-card route: Azure for Students in East US (start verification now). Google Cloud's Space Apps credit only for a VM with a disk.
- **Updatability.** Collections from a run-time config list; cache keys = snapped position, fixed epoch, exposure set, pipeline version.
- **Abuse and safety.** Shared secret between proxy and origin; forwarded client IP for a token bucket on cold builds plus a global daily budget; FOV and exposure caps; fixed upstream allow-list; contact User-Agent; no secrets in the client; no accounts; `robots.txt` excludes `/api/`.

**Contract v1 (frozen at G0a; changes only through the lead).** Manifest: snapped request; grid (centre, 3.075", shape, pixel-centre convention, row order); time bins; presets; planes (bin, wavelength range, effective wavelength, N, noise, dates, mission); exposures used and sampled counts; versions; status and error codes. `frames.bin`: little-endian float16, NaN = no data, sha256 in the manifest, int16 fallback decoder. Three Gaia stars with expected pixels per fixture. Python `Cutout`/`Plane` types; viewport `skyToScreen`/`screenToSky`/`onSkyClick`; one preset table for both languages; a fixture mode on the API. **Design contract, same hour:** ~40 tokens, eight components, and a `/design` gallery of loading, empty, error and partial states; no colour or font outside tokens; single column as the base layout.

**Stack (versions verified today, pinned by lockfiles).** Python 3.12, FastAPI, requests/httpx (sync, threaded), numpy, astropy (IERS auto-download off), scipy; `reproject` as a test reference only; uv; Docker. Node 24 LTS, pnpm 12, React 19.3, Vite 8, TypeScript 7 (lint with Biome), Tailwind 4, Zustand 5, uPlot 1.6, Vitest 5, Playwright 1.65. GitHub Actions; one external uptime monitor. Licence Apache-2.0. Aladin Lite is off the critical path (CDS outage; GPL-3 in stable 3.8.2).

**Repo layout to create** (repo holds only README and .gitignore): `apps/api/tombaugh/` (`discovery.py`, `remote_fits.py`, `prepare.py`, `register.py`, `stack.py`, `photometry.py`, `legacy.py`, `catalogs.py`, `frames.py`, `build.py`, `cache.py`, `main.py`) with `tests/`; `apps/web/src/` (`viewport/`, `synth/`, `panels/`, `state/`, `design/`), `apps/web/functions/api/[[path]].ts`, `apps/web/public/featured/`; `spec/` (contract, preset table, fixtures); `science/` (scripts, `results/*.json`); `docs/` (ARCHITECTURE, SCIENCE, LIMITATIONS, VALIDATION, DATA_SOURCES, AI_USE, RUNBOOK); `CLAUDE.md`; `Dockerfile`, `fly.toml`, `.github/workflows/`.
**Reuse (port = move plus tests, not rewrite):** `scratchpad/agents/access/fast.py` (6-request reader, bit-identical to astropy) → `remote_fits.py`; SIA parsing and clustering from `scratchpad/tools/spx.py` → `discovery.py`; `scratchpad/agents/variability/04_phot.py` and `05_analysis.py` (photometry, 10-day bins, wing proxy) → `photometry.py`; `scratchpad/agents/motion-faint/04_stack.py` (stacks, two-source fit) and `motion-bright/04_stack.py` → `stack.py` and `science/`; `scratchpad/agents/movers/mv.py` (ephemeris-to-exposure finder) → the mover spike.

**Design direction.** A precision instrument, not a dashboard: near-black neutral ground, warm white type, one amber accent with blue for overlays; Inter for text, IBM Plex Mono with tabular numerals for coordinates; hairlines instead of cards and shadows; no decorative motion. Viewport dominant; right rail holds the timeline strip, wavelength ruler and spectrum; a status line carries provenance. Built with the frontend-design skill.

## 7. Team, gates, working agreements

One owner per lane, each with their own Claude Code session on a branch; small PRs to `main` behind CI. This session leads lane A and writes Contract v1 first.

| Lane | Owns |
|---|---|
| A Data and infra | reader port, fetch, build, cache, CI/CD, deploy, monitoring; then the spectrum endpoint |
| B Science | Then & Now and mover spikes from the first minute; prepare/register/stack; validation numbers |
| C Viewport | decoder, renderer, blink, side-by-side, difference, overlay layer |
| D Panels | resolve and catalogs endpoints plus their UI, fast-mover hint, URL state, spectrum panel; backs up E from 20:00 |
| E Design and story | tokens, shell and state gallery; landing; About; deck, recording, NASA page; outreach and stranger tests |

| Gate | When | Must be true |
|---|---|---|
| Ask the desk | now | Slides required? Sent in advance? Live demo allowed? Own laptop? |
| Hosting go/no-go; **G0a** | 13:00 | Card on Fly.io or no-card route chosen. Contract v1, two real fixtures, stub scaffold, design tokens and shell, `CLAUDE.md` merged |
| Mentor check | 14:00 | Evidence plots and §5 shown to the astronomy mentor (leaves 18:00): "what is wrong with this?" |
| **G0b** | 14:30 | Fixtures render on the public URL through the production path; H1 and H4 measured |
| Hero decision | 15:00 | Then & Now and mover spikes rendered from real data (H2, H5); pitch opener chosen |
| **G1** | 17:00 | Live frames for any coordinate on the public URL |
| Reviews | 20:00 | Deck v0, page v0, first stranger test; UI review (a design mentor), pitch review (a pitch mentor) |
| **G2** | 21:00 | Core A complete; first screen recording saved |
| **G3** | 01:00 | Core B complete; five targets pinned. **Feature freeze** |
| **G4** | 04:00 | Demo script passes three times in a row on production; tagged |
| Desk; lock | 06:00; 07:00 | Named primary and backup confirm the team. **Production lock**: tag, image digest and Pages URL recorded; deploys manual; lead-approved demo-path fixes until 10:30, each followed by two full script runs |
| Record; test; save | 08:00; 08:30; 10:00 | Raw captures recorded; second stranger test; first complete NASA page saved. Final save by 22:00 |

If behind, cut in this order — G0b: proxy (direct CORS), extra CI; G1: ZODI/VARIANCE (median background), deep collections, FOV choice; G2: three-colour view, speed/zoom controls, resolver mirror chain; G3: joint neighbour fit (warn instead), motion arrows (static markers), About (link the README); G4: phone polish. **Never cut:** the fast-mover hint, difference image, URL state, pinned featured files, backup recording, NASA page saved by 10:00. What does not work is cut or hidden, never faked.

**Working agreements.** Agents edit only their lane's paths; `spec/` changes go through the lead with regenerated fixtures. No new dependency, endpoint, field or upstream call without a line in the PR and a recorded real response. No synthetic sky; published numbers render from `science/results/*.json`. One implementation each of propagation, presets and stacking. No skipped or loosened tests. PRs merge within 90 minutes; revert first when `main` breaks. Five-line handoff before sleeping (two shifts, 01:00–07:00; pitch speakers sleep). Never paste tokens into agent sessions.

## 8. Definition of done

- Public HTTPS URL; any coordinate returns real pixels or an honest "no data"; nothing depends on a laptop.
- A stranger on a phone, given only the URL, sees something move within 10 seconds and can say what moved within 60; tested on at least five people; result published.
- One-command local run; reproducible image and lockfiles; CI without network in under 3 minutes; deploys only from `main`, manual after v1.0.
- Designed failure: deadlines, retries, stale discovery when IRSA is down, partial results labelled, upstream status visible, featured targets independent of every upstream.
- Health check that answers during builds; external uptime monitor alerting two named owners; free disk in `/api/status`; manual checks on 2 Dec, 16 Dec, 25 Jan.
- Keyboard-complete, AA contrast, safe blink rates with a non-flashing equivalent, a data table behind the spectrum, usable on a phone.
- Units, dates, uncertainty and provenance on every image and number; limits one click away; "candidate", never "discovery".
- Docs: README, architecture, science, validation results, limitations, data sources with DOIs, AI use, runbook, licence.
- ≤ $5/month and alive through 26 Jan 2027.

## 9. Validation

**Protecting the demo (required).** Production smoke script running the demo path after every deploy, including the five pasted challenge strings; golden fixture tests (a Gaia star at its expected pixel, WISE 0855 S/N in range, Barnard shifting north); one frames round trip run by both pytest and Vitest on the same decoded file.

**Per-target pass criteria (owner B; shown in About from `science/results/*.json`).**
| Target | Pass |
|---|---|
| Barnard's Star | Shift within 2σ of Gaia; labelled "saturated, wings only, ±1.5"" |
| Eps Indi B | Steps 1.9", 2.8", 1.9" recovered to 0.3", or reported as not measured |
| WISE 0855 | S/N >10 per full visit at 4–5 µm; joint-fit motion within 2σ of prediction; field-star null |
| RW Aur, R Dra | "Variable" only above 5× the scatter of five comparison stars; saturated curves labelled "experimental" |

**Method checks, most credibility per hour first:** Gaia field-star null per frame on the displayed stacks, rms and common-mode vector (30 min); known-mover table (45 min); two or three unsaturated stars against the IRSA Spectrophotometry Tool by hand (30 min); Then & Now null: Gaia stars moving <10 mas/yr agree to 0.5" rms. Photometry target: median within 5%, scatter under 10%, J and Ks.

## 10. Risks and fallbacks

| Risk | Fallback |
|---|---|
| SPHEREx-only motion is illegible to a lay jury | Hero is Then & Now or a solar-system mover, chosen from real frames at 15:00 |
| Then & Now not validated by 15:00, or artefacts | Linked side-by-side AllWISE panel; not the pitch lead |
| Uniqueness challenged | We say "we have not found another entry that validates this against Gaia", never "only" |
| Blended target (WISE 0855) | Joint fit; else a warning and Eps Indi B for the spectrum beat |
| Saturated test stars look broken | Hatched cores, lenient mask near them, "saturated" state, honest card captions |
| No live demo allowed, or venue network fails | Self-contained deck with recorded captures of the real product; hotspot; static hero |
| Pitch truncated at 3:00 | Script to 2:40, user and URL in the first 40 seconds |
| Cache un-warmed by deploy, expiry or new data | Static featured files; production lock at 07:00 |
| No payment card / sole card holder | Decide at 13:00; Azure for Students; two owners on alerts |
| Integration slips | Contract v1 and fixtures first; fixtures on the public URL before live data; freeze at 01:00 |
| Deep fields (29,470 frames at the ecliptic pole) | ≤600 exposures, deterministic sampling, "N of M" |
| Overclaiming | Fixed vocabulary: candidate, measured, uncertain. This finds nearby stars and brown dwarfs, not Planet X: SPHEREx is too shallow and Planet X would jump ~14' between visits |
| Product rots before January | Size-capped cache with a pinned set; external monitor; dated manual checks |

## 11. Pitch, demo, submission

**Sentence to remember:** "Spot-the-difference for the whole sky: the trick that found Pluto, on NASA's newest telescope, for anyone."

**Pitch, scripted to 2:40, one speaker and one driver, deck works with no network.**
| Time | Say | Show |
|---|---|---|
| 0:00–0:20 | Tombaugh found Pluto by flipping between two photos. SPHEREx photographs the whole sky every six months, and there is no public way to flip through it | Hero sequence already looping |
| 0:20–0:40 | We built one. Type any spot in the sky, get the flip-book. It is for NASA's Backyard Worlds volunteers, and it is live: scan this | Name, tagline, QR on every slide |
| 0:40–1:35 | Three beats: the chosen mover; then and now with years; "SPHEREx sees 102 infrared colours: click the dot and its spectrum tells you what it is" | Real captures |
| 1:35–2:00 | Gaia predicts 4.5"; we measure 4.4 ± 0.3". Every pixel is real, and where a star is too bright we say so on the image | One number |
| 2:00–2:40 | Paste NASA's own test coordinates and most tools show empty sky, because the star left in 2010; ours tells you where it went. Open source, new NASA images as they are released. [Stranger-test result.] Go and find something | URL, QR |

Prepared answers: found Planet X? (no, and why) · doesn't NASA have this? (their SPHEREx tools show a time-averaged sky) · how is it different? (five targets on real pixels, any coordinate live, checked against Gaia, never "only") · is it right? (the Gaia number) · who uses it Monday? (the named community and Saturday's post) · what fails? (bright stars lose their centres; slow movers need the old surveys) · how much did AI do? (truthfully; see below).

**NASA page (main global deliverable), in order:** ~1,000-character summary; hero GIF under 10 MB with a still fallback; "tested on" table (target, measured, catalogue, caveat, deep link); who it is for, with evidence; limits; every dataset, library, font, image and tutorial cited; team. NASA data: SPHEREx DR1/QR3, AllWISE, 2MASS at IRSA. Partner data: ESA Gaia; CSA link if built. "Link to Final Project" = the live hero deep link. No custom domain; file the FortiGuard classification for the `pages.dev` host.

**Video, 29 s, human voice, burned-in English subtitles, no generated imagery:** 0–2 s team and "Athlone, Ireland"; 2–5 s two real frames flipping; 5–9 s name and tagline over the live UI; 9–20 s one continuous capture (type a name, then and now, click, spectrum); 20–26 s phone view and "new NASA data as released"; 26–29 s URL, "open source · not an official NASA tool". Captures recorded Sunday 08:00, after the lock. Duration checked on the hosted copy, hosted twice.

**Impact evidence (team, by hand, starting today).** Stranger tests with a stopwatch; live link posted to the Space Apps Connect thread and sent to the Backyard Worlds team and WiseView's authors; one before/after line (IRSA: 4 MB and 4–15 s per frame, no blink; ours: seconds for hundreds).

**Name.** Keep "Tombaugh" (unused among 176 competing repo names) with a plain tagline, one rehearsed pronunciation ("TOM-baw") and a tribute line. Test: tell three mentors, ask them to write it down ten minutes later; if most fail, use "Clyde". Any photograph of Tombaugh needs a checked licence.

**Compliance, owner decisions.** Met or planned: no work before Sat 09:00; English; public links without login; Apache-2.0; team confirmation; demo limits; no NASA logos; no generated images, video or audio. **Two points the team must decide, not the AI:** (1) Space Apps permits AI tools but says they should not be used to come up with the idea of how to solve the challenge. The challenge prescribes the solution's shape, and this document is a proposal: adopt, change or reject its concept choices as your own, and describe AI's role truthfully in the SI field and in answers. (2) AI-generated code must be acknowledged "in descriptive text and metadata". Proposal: README, About, `docs/AI_USE.md`, package description fields and an HTML meta tag, with commit messages left free of AI attribution per the standing repo rule. Confirm or change this reading.

## 12. First actions on approval

1. Team, now: ask the desk about presentation format; Fly.io sign-up with a card (or start Azure for Students); Cloudflare account; confirm all five are on the NASA team page; check everyone's Claude Code limits; name the 06:00 pair.
2. Lane A (this session): Contract v1 and `CLAUDE.md`; port the reader with tests; two real fixtures from the cached cutouts; scaffold API and web with a fixture mode, minimal CI, Dockerfile, `fly.toml`, Pages Function; deploy; measure H1 and H4.
3. Lane B: Then & Now spike (WISE 0855: AllWISE W2 vs SPHEREx 4–5 µm; Barnard: 2MASS/AllWISE/SPHEREx) and the Pluto/3I spike, both from the cached prototypes, for the 15:00 hero decision; Eps Indi B stack (H3).
4. Lane E: design tokens, shell and state gallery by 13:00; take the evidence plots to the astronomy mentor at 14:00.
5. Finish syncing this plan into the shared doc.

## Sources

Challenge page · Judging & Awards Guide and Project Submission Guide (spaceappschallenge.org/resources) · hackathlone.com (schedule, judges, mentors) · SPHEREx Explanatory Supplement v2.1 (irsa.ipac.caltech.edu/data/SPHEREx/docs/SPHEREx_Expsupp.pdf) · IRSA SPHEREx archive guide and tutorials (caltech-ipac.github.io) · IRSA SIA/IBE and the `nasa-irsa-spherex` bucket (measured) · WiseView (byw.tools/wiseview) · Gaia DR3 · Fly.io and Cloudflare docs · competing READMEs (read, not run), including github.com/Ashhajj0/SPHEREX-And-PLANETX and github.com/root3315/muninn.
