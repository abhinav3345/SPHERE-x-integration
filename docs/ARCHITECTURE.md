# Architecture

Backend only (the frontend owner adds a section). Code is in `src/backend`. `CLAUDE.md` calls this folder `/api`; the repo uses `src/backend`.

## Overview

```
Browser (frontend)
   │  HTTPS, JSON, PNGs
   ▼
FastAPI on Render (src/backend)
   ├── /resolve   → resolve.py  → CDS Sesame / SIMBAD
   ├── /stars     → gaia.py     → Gaia DR3 (ESA archive)
   ├── /frames    → presets.py  → demo_cache/  (instant)
   │              └ spherex.py  → IRSA TAP + cutouts (slow, live)
   ├── /overlay   → overlay.py  → frames + Gaia + proper motion
   ├── /presets   → presets.py
   └── static     /demo (demo_cache/), /static (live frames)
```

## Files

| File | Owner | Job |
|---|---|---|
| `main.py` | B2 | Routes, CORS, error handlers, static mounts, concurrency limit |
| `resolve.py` | B2 | Name, degrees or sexagesimal → RA/Dec |
| `gaia.py` | B2 | Gaia DR3 cone search with retries (max 200 stars) |
| `cache.py` | B2 | JSON disk cache (`cache/` runtime, `demo_cache/` committed) |
| `presets.py` | B2 | List presets, match a request to a precomputed preset |
| `overlay.py` | B2 | Proper-motion-corrected pixel positions per frame |
| `cleanup.py` | B2 | Keeps only the 20 newest live-frame folders |
| `precache.py` | B2 | Early script: Gaia stars for 5 demo stars (superseded) |
| `precache_frames.py` | B2 | Builds frames and stars for the 5 challenge targets into `demo_cache/` |
| `spherex.py` | B1 | IRSA search, cutouts, wavelength grouping, reprojection, PNGs |

B1 is unavailable at the moment; B2 maintains `spherex.py` until he returns.

## Request flow: `/frames`

1. Validate input (done in `spherex.py`).
2. If default options and the position matches a preset: return its saved `frames.json` from `demo_cache/frames/<slug>/`. No network.
3. Else if `static/frames/<folder>/frames.json` exists: return it.
4. Else try to take a live-build slot (`BoundedSemaphore(1)`). If none is free: 503 `{error}` immediately.
5. Run `build_frames()`:
   1. IRSA TAP query lists exposures covering the position.
   2. Download up to 80 cutouts in parallel, with retries.
   3. Group by wavelength, rank groups, select frames.
   4. Reproject onto one common sky grid, apply one shared stretch, write PNGs.
6. Save `frames.json` next to the PNGs, trim old live folders, return.

`/overlay` calls the same frame code, then Gaia (via `/stars` logic and cache), then `build_overlay()`.

## Caches

| Location | In git | Content |
|---|---|---|
| `demo_cache/` | yes | Preset frames, `frames/index.json`, Gaia stars. Survives redeploys |
| `cache/` | no | Runtime Gaia results |
| `static/frames/<folder>/` | no | Live builds (folder name = ra, dec, size, detector, mode, group). Trimmed to 20 |

Render's free disk resets on every deploy, so anything needed for the demo must be committed in `demo_cache/`. Cache keys round to 4 decimals, so near-identical searches share a file.

## Deployment (Render, free web service)

- Root directory `src/backend`
- Build: `uv sync`
- Start: `uv run uvicorn main:app --host 0.0.0.0 --port $PORT`
- Deploys from `main`. Python version must match `pyproject.toml` (>= 3.12).

## Decisions

- **Why not Vercel/Netlify for the backend:** serverless timeouts, no persistent disk, and astropy/reproject size limits.
- **Frames are PNGs, not live FITS in the browser:** small downloads, simple canvas player.
- **Precomputed presets:** live IRSA is slow (about a minute) and unreliable. The demo must not depend on it.
- **Plain `def` routes for slow work:** FastAPI runs them in worker threads, so health checks stay responsive.
- **One live build at a time:** protects Render's 512 MB RAM and IRSA from overload.
- **Fixed sky grid and one stretch per request:** a brightness change between frames is real, not an artefact of per-image scaling.

## Known constraints and risks

- IRSA (TAP and SIA2) fails intermittently (502, connection reset). Presets must be built when it is up, possibly from another machine.
- IRSA docs: SIA2 lags new data by about a day; TAP sees new data right after ingestion.
- QR2 data is no longer searchable. Use DR1 and QR3 (SIA2 collections `spherex_dr1`, `spherex_qr3`, plus `_deep`).
- Render free tier sleeps after inactivity and has limited RAM. Wake with `/health` before a demo. Whether `reproject` fits in memory on a live build is untested.
- Gaia lacks very bright and very faint objects (WISE 0855).
- Never fabricate data. Fixtures must be labelled. `BAD_FLAG_MASK` and several thresholds in `spherex.py` are marked `UNVERIFIED` in the code.

## Frontend (`web/`)

Added by the frontend lane after `main` was merged into `frontend/main` on 14 November 2026. A guide for teammates is in `web/README.md`.

```
Static site (web/, Vite build, no server code)
   ├── /        landing page   web/index.html      → web/src/landing/
   └── /look/   comparator     web/look/index.html → web/src/main.tsx
          ├── frames  → GET /api/fields on the frames engine (api/, docs/CONTRACT_FIELDS.md)
          │             or the two recorded fields bundled in the site (/fixtures/<name>/)
          └── search  → GET /resolve, GET /stars on this backend (docs/CONTRACT.md)
```

- **Pages.** One static site with two pages: the landing page at `/` and the comparator at `/look/`. Both are built from the design sources (`web/src/landing/`, `web/src/comparator/`).
- **Frames.** The comparator loads a field (a manifest and one float16 frame file, Contract v1.0) from the frames engine. When the engine does not answer, the two recorded fields (WISE 0855, Barnard's Star) load from the copies of `cache/fixtures/` that the build puts into the site.
- **Endpoints of the engine it calls.** `/api/fields` for a field, `/api/fields/{key}/overlays` for the catalogue markers (Gaia DR3 and CatWISE at each visit's date) and `/api/fields/{key}/spectrum` for the spectrum of the ringed position. With no engine, the two recorded fields still show their markers, and the spectrum at their centre, from recorded answers of the engine (`cache/fixtures/<name>/overlays.json` and `spectrum.json`), labelled with the date they were recorded; anywhere else these two parts say they are not available. The recorded fields also carry their older-survey images for Then and now.
- **Endpoints of this backend it calls.** `/resolve` for names and coordinates, `/stars` for Gaia DR3 stars and proper motions (the hint for objects that have moved away from their catalogue position). Not used by the comparator today: `/frames`, `/overlay`, `/presets`.
- **Configuration.** `VITE_TEAM_API_URL` is this backend's address; the browser calls it directly (CORS is open). `VITE_ENGINE_URL` is the engine's address; empty means the same origin, with `/api` proxied. Both are compiled into the page, so nothing secret goes there (`web/.env.example`). In development the Vite server proxies `/api` to `http://localhost:8080`, or to `TOMBAUGH_API_URL`.
- **Design sources.** `docs/design/system/` (rules, tokens, components, hand-off guides), `docs/design/landing/` and `docs/design/comparator/` (layouts, states, behaviour, copy, and the removable parts).
- **Why frames come from the engine** (the current wiring, still to be confirmed by the team: `CLAUDE.md` section 14). The designs and the viewer need every wavelength band of a visit on one brightness scale, with bad pixels masked and no-data pixels marked, and the engine is the only part that has produced all the test targets so far. This backend has what the engine lacks: name lookup, Gaia stars and a deployment.
- **Deployment.** None. The static host is not chosen yet.

## Frames engine (`api/`)

A second FastAPI service (Python package `tombaugh`), separate from this backend. It finds SPHEREx exposures at IRSA, reads only the needed rows from the public bucket, masks bad pixels, registers north-up and stacks per visit and wavelength bin, and serves one float16 file per field from a disk cache. Not deployed; where it runs is still open (`CLAUDE.md` section 14).

- Contract: `docs/CONTRACT_FIELDS.md` (Contract v1.0, machine-readable parts in `docs/contract/`).
- History and known limits: `docs/ENGINE_NOTES.md`.
- Routes: `GET /api/fields` (202 while building), `/api/fields/{key}/frames.bin`, `/api/fields/{key}/overlays`, `/api/fields/{key}/spectrum`, `/api/status`, `/healthz`.
- Run locally: `cd api && uv run uvicorn tombaugh.main:app --port 8080`.

## Change log

Append two lines per task: what changed, where, any new constraint.

- 2026-11-14: Backend skeleton (`main.py`, `resolve.py`), Gaia `/stars`, disk cache, uv setup. Constraint: `size` unit differs between `/stars` (arcmin) and `/frames` (degrees).
- 2026-11-14: Standard `{error}` handlers; B1's `spherex.py` merged. Constraint: live `/frames` takes about a minute.
- 2026-11-14: Deployed on Render. Constraint: free tier sleeps, disk is not persistent.
- 2026-11-14: `/frames` route, `/demo` and `/static` mounts, `/presets`, cache-first `/frames`. Constraint: presets need `demo_cache/` committed.
- 2026-11-14: `/overlay`, live frames cache, sexagesimal input, live-build limit (503), live-folder cleanup. Constraint: overlay uses Gaia only.
- 2026-11-14: Presets still not precomputed because IRSA TAP and SIA2 returned 502 or connection resets.
- 2026-11-14: `main` merged into `frontend/main` with a foundation built on a separate local branch: frames engine `api/`, recorded fields `cache/fixtures/`, web app `web/`, prototypes `science/prototypes/`, `Dockerfile`, `fly.toml`, CI. The engine's contract and notes are `docs/CONTRACT_FIELDS.md` and `docs/ENGINE_NOTES.md` (renamed from `docs/contract.md` and `docs/architecture.md`, which clash with this folder's files on case-insensitive file systems). Constraint: two contracts; the merge changed no file of this backend.
- 2026-11-14: Frontend: design sources in `docs/design/`; tokens, fonts and `bc-` component styles in `web/src/design/`; pages `/` and `/look/`; sections "Frontend (`web/`)" and "Frames engine (`api/`)" above. Constraint: the comparator calls `/resolve` and `/stars` here and takes frames from the engine; `/frames`, `/overlay` and `/presets` are not used by it today.
- 2026-11-14: `CLAUDE.md`, `README.md`, `docs/RUNBOOK.md`, `docs/ENGINE_NOTES.md` and the new `web/README.md` describe the combined repository; CI runs on pull requests and on pushes to `main` only. Constraint: new change-log entries go here, not in `docs/ENGINE_NOTES.md`.
- 2026-11-14: Frontend: landing page built from `docs/design/landing/` (`web/src/landing/`; four real frames and their provenance in `web/public/landing/`). Constraint: the frames are drawn at whole multiples of 119 px with smoothing off; `frames.json` stays in Biome's format; the pictures must be exported again if the SPHEREx planes of the recorded fields ever change (the exporter drove the first viewer, which is removed).
- 2026-11-14: Frontend: search and the moved-object banner (`web/src/overlays/`): positions are parsed in the page, names go to `/resolve`, fast movers come from `/stars` and from a short built-in list of known movers. Constraint: name search is on only when `VITE_TEAM_API_URL` is set; the banner for WISE 0855 and the five target rows work without this backend.
- 2026-11-14: Frontend: comparator built from `docs/design/comparator/` (`web/src/comparator/`: a view model, 25 blocks, layouts for 1280×720, 1440×900, the 720 rail and phones) with all twelve removable parts switched on in `features.ts`; the first viewer (`App.tsx`, `Player.tsx`, `Viewport.tsx`) is removed. Constraint: at 1280×720 and 1440×900 the page never scrolls; in the time rail only the timeline and then the caveat notice may shrink; the legend's items never depend on the frame or on the ring; a moving catalogue source is drawn only along the engine's track; notes under the view switch stay one line each. The rules for blocks are in `web/src/comparator/CONTRACT.md`.
- 2026-11-14: Frames engine, pipeline 0.3.0 (`api/`): `/api/fields/{key}/spectrum`, `/api/fields/{key}/overlays`, and AllWISE and 2MASS planes in every build; both recorded fields recorded again (their SPHEREx planes are byte-identical to the 0.2.0 recordings). Measurements and known limits are in `docs/ENGINE_NOTES.md`. Constraint: the spectrum and the catalogue markers need the engine; a field without older-survey planes greys Then and now; contract clarifications for sections 5, 7.1 and 7.3 await sign-off (`CLAUDE.md` section 14).
- 2026-11-14: Frontend: the address of a frame file is judged by its parsed origin (`web/src/api.ts`, `isEngineOrigin`). Constraint: the page loads a frame file only from its own origin or from the configured engine.
- 2026-11-15: Recorded answers. `api/tombaugh/tools/record_answers.py` records the `/overlays` and `/spectrum` answers of a recorded field through the routes' own code into `cache/fixtures/<name>/overlays.json` and `spectrum.json` (envelope and rules: `docs/CONTRACT_FIELDS.md`, section 8); the comparator uses them only when no live answer can be had, the spectrum only at the field's centre, always labelled with the date (`web/src/api.ts`, `web/src/comparator/extras/`). Constraint: a live answer always wins; record the answers again (`uv run python -m tombaugh.tools.record_answers <name>`) whenever a recorded field is recorded again.
