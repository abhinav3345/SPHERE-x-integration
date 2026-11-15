# Engine notes

The history and known limits of the frames engine (`api/`) and of the parts built with it: the recorded
fields, the first web viewer, CI and the container. The engine's interface is `docs/CONTRACT_FIELDS.md`. The
team change log is `docs/ARCHITECTURE.md`: new entries go there. Update the list of known limits below when
a limit changes.

This file was `docs/architecture.md` until 14 November 2026; it was renamed because that name clashes with
`docs/ARCHITECTURE.md` on case-insensitive file systems. The foundation was built on a local branch named
`dev`, which no longer exists: it was merged with `main` into `frontend/main`. Each section below describes
the state at its own time. Entries have two lines: what changed and where; then any new constraint, or
"none".

## Foundation on `dev`, Saturday 14 November 2026

State at 14:05 GMT. Parts still missing at that time are named, so that no entry reads as more than it is.

**Contract v1.0**
- Changed: `docs/CONTRACT_FIELDS.md` defines the HTTP API, the manifest, `frames.bin`, the sky grid, time and wavelength bins, presets and fixtures; the machine-readable parts are `docs/contract/presets.json` and `docs/contract/vectors/grid.json`.
- Constraint: frozen. A change needs the data/backend owner, a version bump, and regenerated fixtures and vectors in the same pull request.

**API package**
- Changed: `api/` holds the Python 3.12 package `tombaugh` (uv, `pyproject.toml`, `uv.lock`): upstream HTTP, discovery, the range-request reader, preparation, registration, stacking, time bins, presets, the frame file and the response models, with tests in `api/tests/`. Not there yet: the HTTP service (`tombaugh.main`), the build pipeline, the cache and the recorded fixtures.
- Constraint: synchronous HTTP only; every upstream host is on the allow-list in `api/tombaugh/http.py`, with at most 2 requests to IRSA in flight; presets are read only from `api/tombaugh/data/presets.json`, a byte-identical copy of `docs/contract/presets.json`.

**Web seed**
- Changed: `web/` is one Vite, React and TypeScript app (npm, Biome, Vitest): contract types in `src/contract.ts`, the field loader in `src/api.ts`, the player maths in `src/player/` (float16 decoding, sky grid, playback, presets, rendering, screen mapping, band synthesis) with tests, and a first screen (`src/App.tsx`, `src/player/Player.tsx`). Not there yet: overlays, the spectrum panel, URL state.
- Constraint: `web/src/generated/` and `web/public/fixtures/` are written by `web/scripts/sync-contract.mjs` and are never edited or committed; `biome check .` covers every file under `web/`, including `functions/` and the JSON files.

**CI**
- Changed: `.github/workflows/ci.yml` runs on pull requests and on pushes to `main` and `dev`: job `api` (`uv sync --frozen`, `ruff check`, `pytest`) and job `web` (`npm ci`, lint, test, build). No deploy job. It has not run on GitHub yet.
- Constraint: CI has no access to the archives, so tests that need the network carry the `network` marker and are deselected; uv is pinned to 0.11.3 in the workflow and in the `Dockerfile`, and the two change together.

**Docker**
- Changed: `Dockerfile` and `.dockerignore` at the repository root describe the API image: `python:3.12-slim`, uv, the locked dependencies without development tools, then `api/tombaugh` and `cache/fixtures` at their repo-relative places under `/app`, and uvicorn on port 8080 with one worker. The image has not been built.
- Constraint: the server runs as uid 10001, never as root; the container starts as root only to hand `TOMBAUGH_CACHE_DIR` (`/data/cache`) to that user. The image cannot build while `cache/fixtures/` is missing from the build context.

**Fly config and proxy**
- Changed: `fly.toml` describes one machine (2 shared CPUs, 2 GB) in `iad` with a 3 GB volume at `/data`, HTTPS only, a `/healthz` check and a limit of 20 to 40 concurrent requests; `web/functions/api/[[path]].ts` forwards `/api/*` from the site to it, and `web/vercel.example.json` is the same rewrite for Vercel. Nothing is deployed.
- Constraint: the app name `tombaugh-api` is a placeholder; a second machine would have its own volume and its own build queue, so the design is one machine; the proxy sets `x-tombaugh-proxy-secret` and `x-forwarded-client-ip`, which the API does not read yet.

## Foundation on `dev`, state at 16:35 GMT on Saturday 14 November 2026

The entries above describe 14:05. Since then the service was joined up, checked independently and fixed.
Where an entry above says a part is missing or "not read yet", this section is the current one.

**Service, pipeline and cache**
- Changed: `api/tombaugh/build.py` joins discovery, the reader, preparation, registration and stacking into one field and writes the manifest; `cache.py` is a size-capped disk cache keyed by content, with an index of requests; `main.py` serves `/api/fields`, `frames.bin`, `/api/status` and `/healthz`. `/spectrum`, `/overlays` and `/resolve` answer 404 "not built yet". `docs/contract/manifest.schema.json` is exported from the response models.
- Constraint: one build at a time, 8 waiting, HTTP 429 beyond; a build nobody polls for 20 s is cancelled; a build that reaches 120 s returns what it has as "partial"; at most 600 exposures per field, sampled the same way every time.

**Recorded fields**
- Changed: `cache/fixtures/wise0855` (254 of 258 exposures, 68 planes) and `cache/fixtures/barnard` (348 of 364 exposures, 82 planes) are real fields recorded by `python -m tombaugh.tools.make_fixture <name>`.
- Constraint: a change to `prepare`, `register`, `stack`, `frames` or `build` needs a higher pipeline version and both fields recorded again in the same change; `api/tests/test_fixtures_golden.py` holds their values.

**Pipeline 0.2.0**
- Changed: three rules per exposure in `prepare.py` (`hole_mask`, `spill_mask`, `spike_mask`) remove single-pixel artefacts that the archive's flags miss; exposures whose band covers 1.083 um are left out of any plane that has other exposures (`build.leave_out_helium`), because they carry a bright foreground that one constant cannot remove; the manifest's `frames.url` ends in `?v=<hash>` and the server serves only the copy with that hash; a field whose list of exposures is unchanged after the 24-hour check is not downloaded again.
- Constraint: the pipeline version lives in `api/tombaugh/__init__.py`, `api/pyproject.toml` and `api/uv.lock`, and `api/tests/test_version.py` keeps the three equal; it is part of every cache key.

**Viewer seed**
- Changed: after a load the keyboard focus moves to the field, so Space plays and the arrows step; the note under the image keeps a fixed height, so the controls do not move while frames change; a loaded field scrolls to the top of the window.
- Constraint: nothing around the image may move when the frame changes. The React and CSS fixes have no unit test (the web tests run without a DOM); they were checked in a headless browser.

### Known limits at 16:35

1. Nothing is deployed. Build time next to the data and the proxy path are unmeasured.
2. A new field takes 30 to 80 s from the venue: about 1.3 MB is downloaded per exposure at 6 arcmin.
3. Visits with few exposures (under 10 per detector) get no rejection between exposures. Artefacts wider than one pixel can remain in them. Such frames are marked "partial" or "thin" and greyed: do not show them as evidence of anything.
4. WISE 0855, all bands, April to May 2026: a dark streak from a single exposure at 1.09 um remains. Use the 4.0 to 5.0 um preset for that target.
5. Saturated stars: the core is blank only in some planes. In the all-bands, D1, D5, D6 and cold views of Barnard's Star no hatch shows, and the core brightness there means nothing. The warning "saturated core" fires on the archive's OVERFLOW flag alone, also where no pixel is blank (RW Aur).
6. Rejection compares all exposures of one detector in a visit, across its four wavelength bins. A spectral feature seen in a tenth or fewer of them can be removed. The manifest notes say so; the rule is the science owner's to confirm or change.
7. The frame noise from the contract's formula is 0.2 to 0.8 of the scatter measured in crowded fields, so any signal-to-noise ratio printed from it is too high.
8. Visits at opposite spacecraft orientations differ by 0.12 to 0.17 arcsec east-west. This matters for the difference view, which is not built.
9. Viewer: at 1280 x 720 the frame label, the buttons and the strip of visits are below the fold; warnings name visits by a number that starts at 0; the no-data hatch is faint on dark sky.
10. Without `TOMBAUGH_PROXY_SECRET` the limit on new builds treats all visitors behind the proxy as one client.
11. Not examined: a point-like signal in one exposure of the WISE 0855 field (May 2025, 1.04 um, pixel 98, 15, absent in the other visits), and three bright spots in the sparse planes of the Barnard field. Artefact or real, unknown.

## Spectrum, catalogue overlays and Then & Now in the engine, evening of Saturday 14 November 2026

Pipeline 0.3.0. Three modules written the same evening (`photometry.py`, `catalogs.py`, `legacy.py`; their
reports hold the validation) were joined to the service, and the two recorded fields were recorded again into
a scratch folder, not into `cache/fixtures` (the lead swaps them).

**Quick-look spectrophotometry** (Contract 7.1)
- Changed: `api/tombaugh/photometry.py` measures one flux per exposure on native pixels (aperture r = 2 px, or a joint PSF fit with CatWISE neighbours within 15"), with the file's own EPSF tables; validated against 2MASS/AllWISE (median ratio 1.027, 5 stars), on WISE 0855 (549 +- 41 microjansky at 4.4-4.8 micron), Barnard's Star ("saturated") and empty sky.
- Constraint: no fallback when the EPSF tables cannot be read (503); a partial read cannot be marked in the JSON (see the route below); "indicative" was never checked on a real OVERFLOW-only star before tonight's RW Aur run (below).

**Catalogue overlays** (Contract 7.3)
- Changed: `api/tombaugh/catalogs.py` builds the body of GET /api/fields/{key}/overlays: Gaia DR3 (ARI then GAVO TAP; proper motion, parallax and RV by ERFA pmpx; Earth from astropy's builtin ephemeris, nothing downloaded) and CatWISE2020 (IRSA Gator), tested offline on recorded answers in `api/tests/data/catalogs`.
- Constraint: a CatWISE motion moves a marker only after `catalogs.catwise_tracks` (30 sigma, no Gaia counterpart, no G<10 star in the field, duplicates merged, Gaia answer at hand); IRSA TAP data queries failed on 14 Nov, so CatWISE goes through Gator.

**Then & Now planes** (Contract 5 and 6)
- Changed: `api/tombaugh/legacy.py` makes AllWISE W1/W2 and 2MASS J/H/Ks planes on a field's grid from IRSA SIA v2 and IBE cut-outs (2MASS smoothed to 10", mosaics filled image by image and never averaged), scaled on field stars to the paired SPHEREx frame; `build.py` runs it on a side thread while the SPHEREx windows are read and appends the planes after the SPHEREx planes (`build_field_for_service`, `make_fixture`; `build_field` adds none unless `legacy_bands` is given).
- Constraint: a plane not scaled on field stars is left out with a warning (the contract says every legacy plane is "scaled": "field_stars"); an upstream failure of the older surveys never fails the field but makes it rebuild after 10 minutes, like a failed SPHEREx download; legacy planes never enter the content key. IRSA's 2MASS SIA does not answer circles of 0.085 deg or more, so 8' and 10' fields are searched in four quarter circles.

**Routes, cache and warnings**
- Changed: `main.py` serves /overlays and /spectrum for built and recorded fields (content key, or a recorded field's name); `cache.py` keeps derived files per key (`derived/<key>/`: exposure list written at build time, overlays answer final once both catalogues answered, every complete spectrum per key and snapped target), capped at a tenth of the cache and removed with their field; `spectrum.py` snaps a click to the nearest Gaia/CatWISE source within 6.15", prefers the package's published astrometry (WISE 0855) to a CatWISE track, and passes CatWISE neighbours. Manifest warnings name visits by their dates, and a blank (saturated) core is told apart from an OVERFLOW-flagged but measured one ("indicative only").
- Constraint: at most 2 spectra are measured at once (429 beyond), each read bounded by 60 s; a spectrum that misses exposures is served with `X-Tombaugh-Incomplete` and never cached; a spectrum needs both catalogues (503 when one is unavailable and not cached). The interpreter switch interval is 1 ms (`main.SWITCH_INTERVAL_S`) so that /healthz is not starved by the reader threads.

### Known limits added tonight

12. WISE 0855's CatWISE motion is wrong by 362 mas/yr in Dec; measured on all 258 exposures, a spectrum along the CatWISE track reads 335.5 +- 34.3 microjansky at 4.4-4.8 micron against 562.0 +- 44.7 with the published motion. The route and, since the fixes below, the overlays use the published motion only for objects in `make_fixture.TARGETS`; any other fast mover known only to CatWISE is measured and drawn along its CatWISE track, unverified.
13. A spectrum of a recorded field searches the archive again for its exposures (SIA, 3-10 s; IRSA answered HTTP 502 eight times once tonight: an honest 503, and the retry worked). Exposures newer than the recording's visits are left out.
14. Contention: cold spectra start 16 reader threads and up to 6 PSF-table threads that parse FITS in Python. Local server, probes every 0.1 s during a build and three cold spectra: with the default 5 ms switch interval 4 of 1903 /healthz probes took over 100 ms (max 230 ms); with 1 ms, 1 of 1048 (151 ms, as a cold spectrum started), median 2.2 ms, p99 43.5 ms, none failed. Under 100 ms always is not reached; fewer spectrum read workers would trade spectrum time for it (not measured).
15. Partial spectra: the contract's JSON cannot say that exposures are missing; the header is the only marker, and the page must read it.
16. Legacy planes hold single pixels exactly 0.0 where a pixel equals the plane's background median (legacy.py subtracts it): real values, not "no data", but `test_fixtures_golden.test_barnard_core_is_saturated_and_says_so` must check SPHEREx planes only once the new recordings replace the committed ones.

## Fixes after the independent verification, night of Saturday 14 November 2026

Pipeline output unchanged (no change to discovery, reader, preparation, registration, stacking, legacy planes or
build): both fields recorded again with this code into a scratch folder are byte-identical to the 0.3.0 recordings
the lead is to swap in (WISE 0855 key `5c321dc84550bfba`, 73 planes; Barnard key `aeae7a60489afee0`, 87 planes).
The answers of /overlays and /spectrum changed, under the same pipeline version 0.3.0, which no deployment holds yet.

**Overlays: WISE 0855 placed by its published astrometry**
- Changed: `catalogs.published_matches` and `catalogs.catwise_sources` give the most significant CatWISE entry of an object in `make_fixture.TARGETS` (not a Gaia one: WISE 0855) the track of its published astrometry with parallax (`catalogs.published_positions`, through `astrometric_positions`) and leave its other entries out (J085508.34-071439.2 and J085506.91-071437.5, whose MJD 57170 positions lie about 83" from the object in the 2025-26 frames); `spectrum.published_targets` reads the same list. Measured in the 4-5 micron frame of each visit, both recordings of the field: 0.18-0.24 px from the fitted source (CatWISE's motion: 0.89-1.14 px, 2.7-3.5"); the golden test now holds 0.5 px. Live from the venue: 94 Gaia and 426 CatWISE sources in 8.0 s.
- Constraint: a published target's track needs no Gaia answer (it is not a CatWISE motion); the CatWISE entry keeps CatWISE's own `ra`, `dec`, `pmra`, `pmdec` (contract 7.3, clarified).

**Spectrum: background terms in the error of binned values**
- Changed: `photometry.binned_error` adds, in quadrature, `BACKGROUND_FLOOR_UJY` (25 microjansky on detectors 1-4, 35 on 5-6) and the bin's weighted annulus skew (`_Point.background_skew`: clipped mean minus median of the annulus, as flux) to every binned `err_ujy`; binned `lam_min`/`lam_max` widen to the members' own wavelengths. Real windows of both fields (one-off measurement scripts, not kept in the repository): binned z at the four void positions of the WISE 0855 field rms 1.12 -> 0.93, |z| > 3 in 1.1 % -> 0 % of bins; at the four emptiest Barnard positions mean z -1.21 -> -0.93, |z| > 3 in 2.2 % -> 0 %. Live: WISE 0855's binned values below 3.8 micron have no |z| > 2.5 (were down to -3.3); its 4.4-4.8 micron points are unchanged (562.0 +- 44.7 microjansky).
- Constraint: the terms are errors, not corrections (blank sky still reads below zero at voids, limit 17); per-point `err_ujy` are unchanged.

**Spectrum route: each click's own separation**
- Changed: `main._for_this_click` answers a kept or joined spectrum with this click's `snapped_to` (a second click 2" away now reads 0.91", not the first click's 0.31").
- Constraint: none.

**Contract clarifications** (`docs/CONTRACT_FIELDS.md`, each marked "clarified on 14 Nov 2026", for the data/backend owner to sign off): section 5, what a legacy plane's values are and that an unscaled plane is not served; section 7.1, the background terms of binned errors, the widened bin edges, and `sep_arcsec` per click; section 7.3, CatWISE motions move a marker only after the server's checks, and an object with published astrometry keeps one CatWISE entry with that track.
- Constraint: the binned error now means more than the contract's "3 % floor in quadrature"; if the owner wants it as a separate field, that is a 1.x minor bump.

### Known limits added after the verification

17. Background and confusion. Blank sky reads -16 to -35 microjansky per detector (inverse-variance means of all good points) at the four positions of the WISE 0855 field farthest from any catalogued source, and positions at least 18" from catalogued sources scatter by 16-36 microjansky per detector beyond their errors; at 39 positions of a regular grid at least 10" from catalogued sources the per-detector medians are -7 to +1 microjansky. In the crowded Barnard field the four emptiest positions read -49 to -241. The annulus skew explains the crowded field, not the sparse one; no correction is applied, only the error terms above.
18. Calibration. Five unsaturated, isolated stars (Ks 10.5-12.3) measured through the route on real windows read a median 1.029 times their 2MASS/AllWISE values interpolated in wavelength (mean 1.026, scatter 0.017); H and Ks run 3-7 % high in four of them, W2 0.92-1.01. The morning prototype found 0.987 +- 0.029 on six other stars. The 4 % difference is unexplained; the WISE W1/W2 zero points behind the comparison were not re-read tonight (unverified). Present the figure as measured (+2.9 %, within the 3 % floor), not as exact.
19. Unfitted light. Only CatWISE sources within 15" of the target are fitted; Gaia-only sources (Barnard's Star itself, which CatWISE does not list), sources 15-30" away whose wings reach the 2-pixel aperture, and sources beyond the grid's edge (the overlays list only on-grid sources) are not. At unsnapped positions 6-10" from catalogued sources in the Barnard field, 16 % of binned values still lie more than 3 errors from zero after the background terms; the state says "ok" there.
20. WISE 0855's fourth CatWISE entry, J085507.45-071437.8 (11" from the published position at MJD 57170, motion -4252, -3610 mas/yr at 25 sigma), is not recognised as the object and is drawn at its catalogue position on the WISE-era trail, where the SPHEREx frames show nothing.
21. The CatWISE entry of a Gaia fast mover stays at its catalogue position: in the WISE 0855 field the entry of Gaia DR3 5756957056704690816 (191 mas/yr) is 1.9-2.1" (0.6-0.7 px) from that star's Gaia track at the visits. The Gaia marker is right.

## Recorded fields of pipeline 0.3.0 swapped in, night of Saturday 14 November 2026

**Recorded fields**
- Changed: `cache/fixtures/wise0855` (key `5c321dc84550bfba`, 73 planes: 68 SPHEREx and 5 legacy, `frames.bin` 2,067,506 bytes, sha256 `b1d9ea973d906bf1…`) and `cache/fixtures/barnard` (key `aeae7a60489afee0`, 87 planes: 82 and 5, 2,464,014 bytes, sha256 `f645de8940d456c3…`) are the 0.3.0 recordings. Their SPHEREx planes are byte for byte those of the 0.2.0 recordings (the first 1,925,896 and 2,322,404 bytes); time bins, exposures and fixture stars are unchanged. `api/tests/test_fixtures_golden.py` expects pipeline 0.3.0, applies the ordering rule to kind "sci" planes and checks the legacy planes against contract section 5 (after every SPHEREx plane, in the order W1, W2, J, H, Ks, no time or wave bin, their own dates, "scaled" "field_stars"); the saturated-core check reads SPHEREx planes only (limit 16); `test_recorded_legacy_planes` holds the recorded missions, bands and dates, and `test_wise0855_w2_plane_shows_a_source_at_the_2010_position_and_none_at_the_centre` holds the Then & Now of WISE 0855 (W2 2010: 30.3 sigma at the challenge's coordinates, no peak within 1.5 px of the centre). `api/tests/test_legacy.py` builds its paired frames from the SPHEREx planes only.
- Constraint: none.

## Recorded answers of the two recorded fields, night of Saturday 14 to Sunday 15 November 2026

**Recorded answers of /overlays and /spectrum** (contract section 8, clarified on 15 Nov 2026)
- Changed: `api/tombaugh/tools/record_answers.py` (`python -m tombaugh.tools.record_answers <name>`) runs the service of `tombaugh.main` in its own process (`create_app` with the real catalogue queries, archive search and photometry, asked through FastAPI's TestClient, so routes, checks and serialisation are the server's), asks `GET /api/fields/{key}/overlays` and `GET /api/fields/{key}/spectrum` at the manifest's request position, and writes each final answer in an envelope to `cache/fixtures/<name>/overlays.json` and `spectrum.json`; the field itself is only read. Recorded live between 00:01 and 00:03 UTC on 15 Nov 2026, each field with an empty cache: WISE 0855, 94 Gaia and 426 CatWISE sources (2.8 s) and a spectrum "ok", joint PSF, 257 points and 65 binned values from 258 windows read (25.9 s; one exposure's joint fit failed and is left out, as the route does); Barnard, 829 Gaia and 600 CatWISE sources (3.3 s) and a spectrum "saturated" without points (30.8 s; 360 of 364 windows read, 4 off the detector, 237 with a blank core). The four responses are byte for byte those of a first recording at 23:47:33 UTC on 14 Nov: the engine answered the same twice. Both overlays are byte for byte what `catalogs.overlays_for_manifest` makes offline from the catalogue answers kept in `api/tests/data/catalogs` (recorded at 19:55 UTC). `api/tests/test_recorded_answers.py` (no network) holds the files to their fields: the envelope byte for byte, each response's SHA-256, `recorded_at` by its form and range (after the field's build, not in the future), that offline recomputation, the fixture stars within 0.001 px of their recorded pixels, WISE 0855's track through the centre (0.024 px at its closest), the spectrum snapped again offline at the request position, WISE 0855 at 3.5 to 6.4 times the error in each binned value at 4.4-4.8 micron (573.0 +- 47.6 microjansky together) and within 2.48 times it below 3.8 micron, Barnard "saturated"; and the tool's refusals.
- Constraint: an answer is written only when final (HTTP 200, the contract model's own JSON, both catalogues "ok", no `X-Tombaugh-Incomplete`), and nothing is recorded when the package is not the pipeline version of the field. Recording again with the same answers changes only `recorded_at`, which the golden test holds by form and range, so it needs no change to the test; a response that changes changes its digest in `RECORDED` (`api/tests/test_recorded_answers.py`), to be updated and explained in the same change. A change to the catalogues, the spectrum, the photometry or the routes that changes these answers needs them recorded again.

### Known limit added with the recorded answers

22. A recorded answer is a record of one moment: the overlays, and the one spectrum at the request position, as pipeline 0.3.0 answered on 15 Nov 2026. It does not follow a new data release or a code change until it is recorded again, and it never answers a click elsewhere (contract rule R3). The tool, like the API tests, asks through starlette's TestClient, which (starlette 1.10.0) warns that its httpx transport is deprecated in favour of httpx2: a starlette upgrade may need the development dependencies changed by their owner.
