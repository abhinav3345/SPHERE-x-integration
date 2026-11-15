# CLAUDE.md — Tombaugh, a blink comparator for SPHEREx (HackAthlone: Planet X and SPHEREx)

Shared context for every Claude instance on this repo. Read this file first. Do NOT re-scan the whole repo each prompt.
Confidence tags: **[CHALLENGE]** = from the official brief. **[TEAM]** = decided by the team. **[MEASURED]** = measured by us on real SPHEREx data, or read in a primary source, on 14 Nov 2026. **[VERIFY]** = not yet checked. Never present [VERIFY] items as fact in UI, docs, or pitch.

State described: Saturday 14 November 2026, about 23:30 Irish time. The repository holds two lines of work built apart and merged on branch `frontend/main`: the team backend with its documents (`main`), and a foundation built on a separate local branch (frames engine, web app, recorded fields, prototypes). The merge left the team's files unchanged. Open decisions are listed once, in §14.

---

## 0. Start here

**Layout** (who owns what: §10):
```
src/backend/          team backend (FastAPI): /health /resolve /stars /frames /overlay /presets. Deployed on Render
api/                  frames engine (FastAPI package `tombaugh`): SPHEREx stacks per visit and wavelength bin. Not deployed
web/                  the static site (Vite, React, TypeScript): / landing page, /look/ comparator. Guide: web/README.md
cache/fixtures/       two recorded REAL fields (wise0855, barnard) made by the engine; copied into the site at build time
science/prototypes/   first-morning scripts behind the measured numbers in §5
docs/CONTRACT.md          contract of the team backend
docs/CONTRACT_FIELDS.md   contract v1.0 of the frames engine; machine-readable parts in docs/contract/
docs/ARCHITECTURE.md      team backend notes, the Frontend section, and the team change log
docs/ENGINE_NOTES.md      the engine's history and known limits
docs/TARGETS.md, docs/VALIDATION.md   test targets and validation checklist (team backend; every check still unticked)
docs/design/              design sources: system/, landing/, comparator/
docs/plan.md              the build plan approved on Saturday morning, kept as the record
docs/RUNBOOK.md, docs/DATA_SOURCES.md, docs/AI_USE.md   deploy and operate; data credits; use of AI (draft)
```

**Which contract governs what.**
- `docs/CONTRACT.md`: the team backend. Its owner (B2) updates it before an endpoint changes.
- `docs/CONTRACT_FIELDS.md` (Contract v1.0, with `docs/contract/`): the frames engine, its frame file and the recorded fields; `web/src/contract.ts` mirrors it. Frozen: a change needs its owner, a version bump, and regenerated fixtures and vectors in the same pull request.
- The comparator calls `/resolve` and `/stars` from the first and `/api/fields`, `/api/fields/{key}/overlays` and `/api/fields/{key}/spectrum` from the second. It does not use the team backend's `/frames`, `/overlay` or `/presets` today.

**Commands** (Python 3.12 with uv; Node 24 with npm):
```bash
cd src/backend && uv sync && uv run uvicorn main:app --port 8000       # team backend
cd api && uv sync && uv run pytest -q                                   # engine tests, no network; what CI runs
cd api && uv run uvicorn tombaugh.main:app --reload --port 8080         # frames engine
cd web && npm install && npm run dev        # http://localhost:5173/ and /look/; /api is proxied to the engine
cd web && npm test && npm run lint && npm run build
```
Port 8080 taken? Run the engine on another port (`--port 8081`) and the web app with `TOMBAUGH_API_URL=http://localhost:8081 npm run dev`.
The site's addresses come from `web/.env.local` (copy `web/.env.example`): `VITE_TEAM_API_URL` for the team backend, `VITE_ENGINE_URL` for the engine (empty: same origin, `/api` proxied). With no engine running, the two recorded fields still load from the copies bundled with the site, with recorded answers of the engine for the catalogue markers and the spectrum at the field's centre, labelled with their date (`docs/CONTRACT_FIELDS.md`, section 8).

**Rules for all code:**
- Real data only. Synthetic arrays only inside tests, named as such (`synthetic_*` in the engine), never shipped.
- Within each part, one implementation each of sky projection, proper-motion propagation, presets and stacking; import it. The two back ends each have their own today (§14, decision 1).
- Never fetch a URL a user supplied. Every upstream call has a timeout and retries. The engine keeps its hosts on an allow-list in `api/tombaugh/http.py`, with at most 2 requests to IRSA in flight and a deadline on each call.
- Front end: the rules of `docs/design/system/README.md` outrank taste. Image pixels are whole device pixels with smoothing off; one brightness scale per sequence; no-data pixels hatched; nothing plays until the reader starts it, at most 6 frame changes a second; nothing around the image moves when the frame changes; in the comparator, colours, fonts and sizes only from tokens and `bc-` classes; no request to any origin except the configured APIs (fonts are self-hosted).
- "Candidate", never "discovery". Never say we are the "only" tool doing something.

## 1. Situation [MEASURED]
- HackAthlone (NASA Space Apps local event), TUS Athlone, 13–15 Nov 2026. Project work opened Sat 09:00.
- Pitch: Sun 15 Nov from 11:30, **3 minutes plus 2 of questions, hard stop**. Whether a live demo is allowed is unpublished: ask the desk.
- One member must confirm the team **in person at the Atrium X desk by Sun 06:00**, or we are not scheduled.
- NASA portal closes **Sun 23:59**. The NASA demo is at most a **30-second video or 7 slides**; longer makes the project ineligible for global judging.
- Global judges reopen the live link until winners on 26 Jan 2027, so the deployment must stay up for ten weeks.
- Team: 6 people. Humans review every PR. Code written with AI is acknowledged (§14, decision 6).
- Goal: win. Aim for 1st place plus the special prizes (see §7).
- Time is very short. Ship a working, deployed core first. Polish second.

## 2. The challenge [CHALLENGE]
Build a **public-facing web tool** that displays images of the sky from NASA's SPHEREx mission so anyone can quickly see how they change over time.

Core ask: the user enters **RA/Dec** of a sky patch. The tool shows a **series of images of that patch like a little video**, making moving objects easy to spot.

Background points from the brief:
- Moving objects are found by comparing images taken at different times (Pluto was discovered this way). Volunteers (e.g. backyardworlds.org) found most known comets and brown dwarfs this way.
- SPHEREx has mapped the whole sky once every six months since May 2025, in **102 bands** of near-infrared light, with images of over a billion objects (brown dwarfs, quasars, comets, asteroids, stars, supernovae, galaxies). Too much data for any one person or computer code.

**Test targets** (the tool must work on all of these):
| Target | Notes |
|---|---|
| Barnard's Star | high proper-motion star |
| Epsilon Indi B | pair of brown dwarfs orbiting a star |
| WISE 0855 | fast-moving brown dwarf. RA 08h55m10.831s, Dec -07d14m42.53s |
| RW Aurigae | variable star |
| R Draconis | variable star |

**Optional considerations from the brief** (not required, but score creativity/influence):
1. Easy to update with new data releases (data arrives fast).
2. Creative use of the 102 bands. E.g. sum data from each of the **six detector arrays** separately to raise signal-to-noise. Extra kudos for **spectra generated on the fly**.
3. Option to add or subtract images taken at different times.
4. User-selectable **field of view** (bigger FOV tracks faster movers but means more data transfer).
5. Overlay other telescopes' data (Gaia, WISE).
6. Coordinates in the **URL** so it can be embedded in other sites.
7. Display metadata such as contamination flags.
8. Use public tools: Astropy; Aladin (CDS Strasbourg).

## 3. Judging criteria [CHALLENGE — drives every decision]
Influence/Impact (quality and quantity of possible impact) · Creativity · **Validity (scientifically valid?)** · Relevance (responsive to this challenge) · Presentation (how well we communicate). Each is scored 1 to 5, with the same rubric locally and globally [MEASURED].
Features alone do not win. Story, validity, and clear communication do. The 2025 local jury had no astronomer and rewarded "a clear user" and "a demo you could see" [MEASURED]. Global judges score mainly the NASA project page, then the demo and the live link.

## 4. Product [TEAM]
Name: **Tombaugh**, a working name (§14). Clyde Tombaugh found Pluto, while hunting for Planet X, by flipping between two photographs. The earlier working name "Blink" appears in 14 competing repository names this weekend. In the site the name is one string, `SITE_NAME` in `web/src/site.ts`.
Personas: citizen scientist (Backyard Worlds style volunteer), teacher/student, professional astronomer.

What it does, in five points, with the state of each:
1. **Correct blinking.** Frames are registered, north-up, wavelength-matched stacks per visit on one brightness scale, so what blinks is the sky and not the filter. Built: the engine (any position with coverage, at most 600 exposures, field 6′ default and 10′ max, honest "no coverage yet", thin and partial frames marked) and the two recorded fields.
2. **Then & Now.** The 2010 AllWISE image (and 2MASS, 1997–2001) on the same grid as a SPHEREx stack at nearly the same wavelengths. Positions are comparable between surveys; brightness is not. Built: the engine adds AllWISE W1/W2 and 2MASS J/H/Ks planes to every field (pipeline 0.3.0; registration 0.2–0.3" rms on field stars), both recorded fields carry them, and the comparator's Then and now view shows them.
3. **What it is, not only that it moved.** Click an object for quick-look spectrophotometry (0.75–5 µm) at the position predicted from catalogue motion. Built: the engine's `/spectrum` (aperture or joint fit with catalogued neighbours; states ok, indicative, saturated, contaminated, no data) and the spectrum panel with chart, table and CSV. Without the engine, the two recorded fields show the engine's recorded spectrum at their centre, labelled as recorded; anywhere else the panel says the spectrum is not available.
4. **The coordinate trap, solved.** Typed coordinates are checked for fast movers that used to be there ("WISE 0855-0714 was here in 2010. It is now 127″ to the west.", with a jump). Built: a short list of known movers that needs no network, plus Gaia through the team backend's `/stars`; names resolve through `/resolve`.
5. **Honest and durable.** Dates, exposure counts, wavelength range and provenance on every frame. No synthetic imagery. New releases need no code change. Built in the engine's manifest; shown by the frame label and the provenance line.

### Built in `web/` on Saturday, from `docs/design/`
- Landing page (`/`): the 1930 Pluto story, two real pairs to flip (Barnard's Star, WISE 0855), what it shows and its limits, a link to the comparator.
- Comparator (`/look/`), the layout that stays when every removable part is left out: search by decimal degrees, band (eight options), field of view, playback (Space and the arrows; never autoplays), the dated frames timeline, the image with scale bar, readout and compass, recentre, frame label, legend with the no-data hatch, caveat list, the "Recorded field" or "Live data" chip, provenance with the two DOIs, and the note "Same brightness scale for every frame".
- The twelve removable parts (`docs/design/comparator/Handoff-removable.dc.html`), each of which can be left out without a gap: search by name or by hours and degrees · moved-object banner · hold to flip · side by side · difference image · then and now · contrast and invert · spotlight zoom · three-colour · spectrum panel · catalogue markers · copy link. All twelve are built and switched on in `web/src/comparator/features.ts`; a part that stops working is switched off there, never left half done. Name search is on only when `VITE_TEAM_API_URL` is set.

### Later, only after the above works
Motion readout against the Gaia prediction · single-exposure events and an "hours" mode · draggable wavelength window · flag overlay and exposure table · GIF export and candidate card · embed and WiseView-style links · wider fields · a one-screen About (methods, limits, validation table, data notes, AI use) · Irish-language toggle (bonus for the local prize).

### Will not build
Automatic "discovery" claims, accounts, any simulated sky, a general FITS viewer.

## 5. Science constraints [MEASURED unless tagged]
- Searchable image collections: `spherex_dr1`, `spherex_dr1_deep`, `spherex_qr3`, `spherex_qr3_deep`. `spherex_qr2` returns nothing. Pixels are in the public bucket `nasa-irsa-spherex` (us-east-1, anonymous, HTTP range requests).
- IRSA's cutout service returns at least 4 MB per cutout whatever the size and takes 4–15 s. The engine reads only the needed rows from the bucket: 258 exposures in 7–9 s from the venue.
- Native pixel 6.15"; stacked resolution about 10". Each exposure images a sky position at ONE wavelength; the next exposure is one spectral channel away; consecutive visits are rolled 180°. **Never blink raw frames.** Blink stacks per time bin and wavelength bin, registered north-up, on one stretch.
- Most positions have 3–4 visits about 6 months apart. SPHEREx alone only shows motions above roughly 1–3"/yr.
- **Catalogue coordinates are old.** The challenge's WISE 0855 coordinates are its 2010 position, 126" from where it is now; Barnard's Star is 269" from its J2000 position. Propagate names to the observation epoch.
- Barnard's Star: 10.25" in a year, core saturated in every exposure (position from the wings, about ±1.5").
- WISE 0855: invisible in single frames; visible only in 4.4–5.0 µm stacks; blended with a background star 4–11" away. Fitted jointly it moved 4.36 ± 0.34" in six months (4.54" predicted). Gaia does not contain it; use CatWISE.
- RW Aur: +51% at 1.2 µm and −46% at 4.6 µm across three visits; core flagged OVERFLOW, so indicative only. R Dra: saturated in almost every exposure; only the 4–5 µm halo is usable, as a relative proxy.
- Eps Indi Ba+Bb is unresolved (one blended source) and its motion test has not been run. [VERIFY]
- Unsaturated-star photometry agrees with 2MASS and AllWISE within about 3%: median ratio 0.987 with 2.9% scatter in the morning prototype (six stars); 1.029 (five stars) and 1.005 with 3.4% scatter (an independent check) through the engine's `/spectrum` in the evening. The differences between these runs are unexplained.
- Spectrum of WISE 0855 through `/spectrum` (joint fit with two neighbours): 562 ± 45 µJy at 4.4–4.8 µm, nothing below 3.8 µm. Blank sky reads low by 15–35 µJy at some positions; binned errors carry a floor for it. A click 6–15" from a bright star picks up its light and is still labelled "ok" (known limit).
- Then & Now registration: AllWISE W1 against the SPHEREx frame agrees to 0.29" rms (10 stars, WISE 0855 field) and 0.22" (16 stars, Barnard field) with no fitted shift. The 2010 W2 image shows WISE 0855 at the brief's coordinates (30σ) and nothing at its 2026 position; SPHEREx still shows a fainter source 2–4" from the 2010 position, not yet identified, so the 2010 image there is not the dwarf alone. The 2010 AllWISE image shows Barnard's Star 168" south of where SPHEREx sees it in September 2026 (10.4"/yr over 16.2 years; Gaia 10.39"/yr), which is 161" south of the recorded field's centre.
- CatWISE motions are mostly unreliable for faint sources (over 200 false fast movers in the Barnard field). The engine moves a CatWISE marker only after strict checks; WISE 0855's track comes from the published astrometry (Kirkpatrick et al. 2021 via SIMBAD).
- Flag masks from the SPHEREx Explanatory Supplement: stack `0x3FD2CEC5`, photometry `0x3C028E44`, background `0x3C2A8E47`. Never mask the SOURCE bit; never drop the SIP distortion terms; a strict mask erases saturated stars, so hatch their cores instead.
- CDS Strasbourg (SIMBAD, VizieR, Aladin tiles and script) is down this weekend. Use the CfA and IDIA mirrors; keep Aladin Lite off the critical path.
- Never fabricate data, endpoints, column names, or astronomy values. If unsure, say "unverified" in code comments and UI.

## 6. Competitors [MEASURED from their code and READMEs]
- **Ashhajj0/SPHEREX-And-PLANETX** (the repo we were pointed at): a static bundle over one pre-baked field. Its RA/Dec entry is cosmetic, all five test targets are synthetic "fixtures", and nothing blinks over time. Real strengths: candid labelling, careful photometry, a polished interface.
- **The wider field is stronger.** 117+ "spherex" repositories since 13 Nov; at least eight claim live coordinate search, blink, subtraction, Gaia overlay and spectra (muninn, Driftnet, SPHEREx-Blink-3.0 and others). Two already place a 2010 WISE frame beside SPHEREx and tell the Pluto story.
- So features and the Pluto story will not win. Five targets on real pixels with honest limits, numbers checked against Gaia, proof that strangers can use it, and craft can.

**Rules:** do NOT copy anyone's code. Do not disparage other teams. Never claim to be the "only" tool; say what we validated.

## 7. Prizes [CHALLENGE]
1st €2500 · 2nd €1500 · 3rd €1000 · Best Use of Open Data €500 · Best Use of Local Application (Region) €500 · Best Storytelling and Creativity €500 · People's Choice €500 (voted during presentations).
Strategy [TEAM]: aim for 1st. Most specials come nearly free:
- Open Data: IRSA SPHEREx + Gaia DR3 + WISE + 2MASS, open-source repo, public embed/URL API.
- Storytelling: the story arc in §9.
- People's Choice: a QR code to the live link on every slide.
- Local Application: bonus only (Irish-language toggle, schools and Irish astronomy club outreach angle). Do not spend build time here.
Open question: can one team win multiple prizes? Ask organizers.

## 8. Tech stack and architecture [TEAM; states MEASURED on 14 Nov]
```
browser ── /  and  /look/     static site (web/)                 not deployed; host undecided (§14, 3)
   ├── /resolve, /stars ────► team backend (src/backend)         Render free tier, deployed by B2
   └── /api/fields ─────────► frames engine (api/)               not deployed (§14, 2)
         or, with no engine, the two recorded fields bundled in the site
```
| Part | Stack | Data path | State |
|---|---|---|---|
| Team backend `src/backend` | Python ≥ 3.12, FastAPI, astropy, astroquery, reproject, Pillow; uv | IRSA TAP and cutouts → PNG frames, one stretch per request; Gaia DR3 from the ESA archive; names through Sesame | Deployed by its owner on Render's free tier (sleeps when idle, 512 MB, disk reset on every deploy); address not in the repo. Started locally on 14 Nov: `/health`, `/resolve`, `/stars` correct. A new live `/frames` often takes 1 to 2 min |
| Frames engine `api/` | Python 3.12, FastAPI, Astropy, numpy/scipy, synchronous `requests` with a thread pool; uv, ruff, pytest | IRSA SIA discovery; range reads of only the needed rows from the public bucket; masked, registered north-up, stacked per visit and wavelength bin; one float16 file per field, disk cache; since pipeline 0.3.0 also AllWISE and 2MASS planes on the field's grid, `/overlays` (Gaia DR3, CatWISE) and `/spectrum` | 835 tests pass without network; container image builds; not deployed. From the venue: a new 6′ field in 30 to 80 s, a 10′ field in 56 s, then instant from cache |
| Static site `web/` | Vite, React, TypeScript (strict), Canvas 2D, Biome, Vitest (`node`), npm; self-hosted fonts | `VITE_ENGINE_URL`, `VITE_TEAM_API_URL`; recorded fields copied in at build time | Built from `docs/design/` on Saturday evening: landing page and comparator with all twelve removable parts; 862 tests; checked in a browser at 1280×720, 1440×900 and 390×844 with and without the engine; not deployed |
| Proxy for `/api` | Cloudflare Pages Function `web/functions/api/[[path]].ts`; Vercel example `web/vercel.example.json` | One origin for site and engine, no CORS | Never run |
| CI | `.github/workflows/ci.yml`: engine (ruff, pytest), web (lint, test, build); no network | No job for `src/backend` | Not yet run on GitHub |

**Why the comparator takes its frames from the engine** (the current wiring; the team still has to confirm it, §14 decision 1). The designs and the viewer need every wavelength band of a visit on one brightness scale, with bad pixels masked and no-data pixels marked, and the engine is the only part that has produced all the test targets so far: WISE 0855 is visible only in a stack of about 30 exposures at 4 to 5 µm, at its 2026 position, 126" from the coordinates in the brief. The team backend has what the engine lacks: name lookup, Gaia stars and a deployment.

Fallback if hosting fails: the two recorded fields are bundled into the site and work with no back end.

## 9. Presentation plan [TEAM]
Story arc: Problem, why it matters, solution, impact. Save technical details for Q&A. Script to 2:40 for a 3:00 hard stop; one speaker, one driver; the deck must work with no network.
1. Hook (20 s): Tombaugh found Pluto by flipping between two photos; SPHEREx photographs the whole sky every six months and there is no public way to flip through it.
2. Who it is for and the live link (20 s): Backyard Worlds volunteers; QR code on every slide.
3. Solution (55 s): the chosen mover; then and now with years; click the dot for its spectrum.
4. Validity (25 s): one number against the catalogue prediction for WISE 0855 (4.4 ± 0.3" measured, 4.5" predicted; Gaia does not contain it); every pixel real; limits shown on the image.
5. Close (40 s): paste NASA's own test coordinates and most tools show empty sky, ours tells you where the star went; open source; new images as released.
Roles: storyteller, demo driver, science Q&A, tech Q&A. Prepare answers on: can it find Planet X (no, and why), false positives, pixel scale, wavelength variation, saturation, data refresh, cost, how much AI did. Keep a recorded backup of the real product.
For NASA: a separate video of at most 29 seconds, the project page with a "tested on" table, every source cited.

## 10. Roles [TEAM]
This file names roles, not people; the team documents do the same (B1, B2). Holders are agreed in the team.

| Role | Folders and files |
|---|---|
| B1 (away at present): wrote the team backend's SPHEREx frame code | `src/backend/spherex.py`, maintained by B2 meanwhile |
| B2: the team backend, its contract and documents, the Render service | `src/backend/`, `docs/CONTRACT.md`, `docs/ARCHITECTURE.md` (backend sections), `docs/TARGETS.md`, `docs/VALIDATION.md` |
| Front-end owner: the static site and its design sources | `web/` (except `web/functions/`), `docs/design/`, the Frontend section of `docs/ARCHITECTURE.md` |
| Frames engine and infrastructure: built with the foundation, in the same lane as the front end; holder to confirm | `api/`, `docs/CONTRACT_FIELDS.md`, `docs/contract/`, `cache/fixtures/`, `docs/ENGINE_NOTES.md`, `Dockerfile`, `fly.toml`, `.github/`, `web/functions/` |
| Science and validity (role from the plan) | `science/`; the numbers in §5 |
| Design, story and pitch (role from the plan) | deck, demo video, NASA page, stranger tests |
| Shared: any role, by pull request | `CLAUDE.md`, `README.md`, `docs/plan.md`, `docs/RUNBOOK.md`, `docs/DATA_SOURCES.md`, `docs/AI_USE.md` |

## 11. Schedule [TEAM; Irish time; re-based Sat 19:30, times from 19:30 on proposed]
| When | Gate |
|---|---|
| Sat 16:35 | **Done.** Foundation works locally: engine on real data for any position, two recorded fields, first viewer, container image builds |
| Sat 19:00 | **Done.** `main` merged into `frontend/main`; design sources in `docs/design/`; tokens, fonts and component styles in `web/` |
| Sat 23:30 | **Done** (two hours late). Designed landing page and comparator work locally on the two recorded fields and on live fields; search and the moved-object hint work against a local team backend; spectrum, catalogue markers and Then & Now work against a local engine |
| Sun 01:00 | Deployed: the site and live frames for any coordinate on public URLs (needs decisions 1 to 3 in §14). Not started: nothing from this branch is pushed or deployed |
| Sun 02:00 | Remaining parts that work are in; five targets checked. **Feature freeze** |
| Sun 04:30 | Rehearsal: the demo script passes three times in a row on production; tagged |
| Sun 06:00 | Team confirmed in person at the desk (named primary and backup) |
| Sun 07:00 | **Production lock**: deploys manual; only lead-approved demo-path fixes until 10:30 |
| Sun 08:00–10:00 | Record captures; stranger test; first complete NASA page saved |
| Sun 11:30 | Pitch (from 11:30). Afterwards: 29-second video, page polish, final save by 22:00; portal closes 23:59 |

Not met or not recorded from the earlier schedule: the mentor check (before 18:00), the 18:30 deployment, the 19:30 Then & Now and solar-system-mover tests (still open in §14).
Cut rule: at every gate, what does not work is cut or hidden, never faked. Never cut: the fast-mover hint, the difference image, URL state, the recorded fields, the backup recording.

## 12. How Claude must work in this repo
**Context discipline**
- Read only: this file, the guide of the folder you work in (`web/README.md`, `api/README.md`), the contract of the part you call or change (§0), and the files for your task. Do not explore the repo.
- One task per session. Stay inside the folders of your role (§10).
- Do not touch `package.json`, `pyproject.toml`, lockfiles, shared types (`web/src/contract.ts`, `web/src/overlays/types.ts`) or config. Ask their owner (a human) instead.
- No refactors, renames, or "improvements" outside the task.
- After each task, append one entry to the change log at the end of `docs/ARCHITECTURE.md`, in its style: date, what changed and where, then "Constraint:" and any new constraint (or "none"). Never edit other entries. When a known limit of the engine changes, update the list in `docs/ENGINE_NOTES.md` too.
- Build against the contract of the part you call. If a contract must change, say so and stop. Its owner updates it.

**Science and honesty**
- Do not invent IRSA endpoints, column names, or astronomy numbers. Mark anything unchecked `unverified` in code comments and in the UI data notes.
- Never mix bands in a blink sequence. Never fake or synthesize data in the live app. Fixtures are recorded real data and are labelled with their dates and provenance.
- Validate inputs (RA 0–360, Dec -90 to 90, capped FOV), rate-limit the API, keep secrets out of git (`.env.example` only).

**Git**
- `main` is the shared branch and stays deployable: Render deploys the team backend from it.
- One branch per task, named area/topic as the team does (`backend/resolve`, `docs/add-documentation`, `bugfix/indent`, `frontend/main`). Pull requests into `main`, under about 300 lines where the work allows.
- Every PR needs a human review and green CI. Merge `main` into your branch first. No force-push.
- Merge window about every 2 hours, then re-test the five test targets.
- Tag known-good builds (`v0.1`, `v0.2`) for rollback.
- If one person runs several Claudes, use `git worktree`, one per task.
- Keep a prompt log (supports the validity and open-data story).

## 13. Known risks
| Risk | Prevention |
|---|---|
| Merge conflicts | folder ownership, small PRs, frequent merges |
| Front end and back ends drift | two contracts, recorded real fields, contract tests for the engine in CI; the team backend has no CI job yet |
| Two back ends doing the same job | decision 1 in §14; until then each keeps its own contract |
| Claude invents data endpoints or facts | measurements first; human checks against IRSA notebooks; science lead validates on known cases |
| Claude refactors unrelated files | scoped prompts; reviewer rejects out-of-scope diffs |
| IRSA slow, down, or rate-limited | engine: pixels from S3, cached discovery; recorded fields bundled in the site; team backend: presets (none computed yet) |
| Render free tier sleeps, resets its disk, has 512 MB | wake it with `/health` before a demo; commit what the demo needs (`src/backend/demo_cache/`) |
| Hosting limits found late | deploy the skeleton before adding features |
| Band flicker looks like motion | stacks per wavelength bin only; validate on WISE 0855 and Barnard's Star |
| SPHEREx-only motion is too subtle for a general jury | lead with Then & Now or a solar-system mover, chosen from real frames |
| Saturated or blended test targets look broken | hatched cores, "saturated" state, joint fit or a warning, honest captions |
| Overclaiming | fixed words: candidate, measured, uncertain; this finds nearby stars and brown dwarfs, not Planet X |
| Scope creep | Core list is fixed; extras need lead approval |
| Reviewer fatigue | rotate reviewers; freeze at the gate |
| Live demo fails or is not allowed | recorded fields in the site, recorded backup, deck that works offline, phone hotspot |

## 14. Open items for humans
**Decisions** (each with its options):
1. [ ] **Frames in the comparator**: (a) the engine, as wired now, with the team backend's `/frames` kept as a fallback; or (b) the team backend's `/frames` alone.
2. [ ] **Where the engine runs**: (a) a second Render web service from this repo, built from the `Dockerfile`; (b) Fly.io, as first proposed (`fly.toml`); or (c) the team backend imports the engine. And who owns that account.
3. [ ] **Static site host**: Cloudflare Pages (the `/api` proxy function is in `web/functions/`), Vercel (`web/vercel.example.json`), or another static host. And who owns that account.
4. [ ] **Name**: keep Tombaugh (a working name) or choose another.
5. [ ] **Licence**: keep Apache-2.0 (`LICENSE`, added as a proposal; also named in `api/pyproject.toml` and `web/package.json`) or choose another and change all three.
6. [ ] **AI disclosure**: confirm or change the draft `docs/AI_USE.md` (its "TEAM TO CONFIRM" lines), and the wording for the NASA project page. Space Apps asks that AI not be used to come up with the idea and that AI-generated code be acknowledged in descriptive text and metadata.
7. [ ] **Fields contract clarification of 14 Nov**: `frames.url` is opaque and ends in `?v=<hash>` (`docs/CONTRACT_FIELDS.md`). Sign it off as a clarification of v1.0, or ask for a version bump instead.
8. [ ] **Fields contract clarifications of pipeline 0.3.0** (`docs/CONTRACT_FIELDS.md` sections 5, 7.1 and 7.3; JSON shapes unchanged): older-survey planes follow the SPHEREx planes and one that cannot be matched on field stars is left out; `snapped_to.catalog` may be "simbad"; an incomplete spectrum is marked by the `X-Tombaugh-Incomplete` header; binned errors include background terms; `track` on a CatWISE source. Sign them off or ask for a version bump.
9. [ ] **Choices made in the comparator that the design does not state**: CatWISE markers only within 15" of the ring plus tracked movers; the spectrum chart's flux axis follows the data; Then & Now pairs W1 with a band that has no older image of its own; the new caveat sentences for engine 0.3.0 warnings. Listed in `web/src/comparator/CONTRACT.md`.

**Other open items**
- [ ] Ask the desk: are slides required, sent in advance, is a live demo from our own laptop allowed?
- [ ] Name the two people at the desk for Sunday 06:00.
- [ ] Agree who holds each role in §10, including the frames engine if it stays.
- [ ] Write the Render address where the team can find it (it is needed for `VITE_TEAM_API_URL` and for the checks in `docs/VALIDATION.md`, all unticked).
- [ ] Still to test on real data: Eps Indi B motion (a live build at RA 331.096, Dec -56.801 shows a bright source at the predicted place in four visits; its motion is not measured), a solar-system mover (Pluto or comet 3I/ATLAS), and what the faint source near WISE 0855's 2010 position is (§5). Then & Now itself is tested on both recorded fields.
- [ ] Science owner: outlier rejection per detector (as built) or per wavelength bin; one rule for saturated cores (see the known limits in `docs/ENGINE_NOTES.md`).
- [x] Latest SPHEREx release and access method confirmed (DR1 + QR3, SIA for discovery, S3 range reads).
- [x] Test-target astrometry checked against Gaia DR3, CatWISE and SIMBAD (see `docs/plan.md`).
