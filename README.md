# Tombaugh

Tombaugh is a public blink comparator for NASA's SPHEREx infrared sky survey. Give it a position on the sky,
and it shows registered, north-up images of that spot, one per visit and wavelength band, all on one
brightness scale, so that anything that moved or changed brightness between visits shows when the frames are
flipped. It is named after Clyde Tombaugh, who found Pluto with a blink comparator. Tombaugh is a working
name.

## Status

**Being built during the NASA Space Apps 2026 hackathon weekend (14 and 15 November 2026).** This section
describes the repository on Saturday 14 November 2026 at about 23:30 GMT. It holds two lines of work that
were built apart and merged that evening: the team backend (`src/backend/`) and a foundation with a frames
engine (`api/`), a web app (`web/`) and two recorded fields (`cache/fixtures/`).

Works today, on real data:

- **Team backend** (`src/backend/`): `/health`; `/resolve` (names through CDS Sesame, decimal and
  sexagesimal coordinates); `/stars` (Gaia DR3 stars with proper motions); `/frames` (PNG frames from IRSA
  cutouts, grouped by wavelength); `/overlay` (where the Gaia stars fall on those frames, proper motion
  applied). Its owner has deployed it on Render's free tier; the address is not in this repository. Started
  on a developer machine on 14 November, `/health`, `/resolve` and `/stars` answered correctly. `/presets`
  is empty: no preset could be computed because IRSA failed at the time.
- **Frames engine** (`api/`), on a developer machine: for any position with SPHEREx coverage it finds the
  public exposures at IRSA, reads only the needed rows from the public bucket, masks bad pixels, registers
  north-up and stacks per visit and wavelength bin. Measured from the hackathon venue: a new 6 arcmin field
  in 30 to 80 s, a 10 arcmin field in 56 s, then instant from the cache. Since Saturday evening (pipeline
  0.3.0) it also puts the older surveys' images of the same patch on the field's grid (AllWISE W1 and W2
  from 2010, 2MASS J, H and Ks from 1997 to 2001), serves catalogue markers (Gaia DR3 and CatWISE positions
  carried to the date of each visit) and measures a quick-look spectrum at a clicked position. 835 tests
  pass without network. Its container image builds and serves the recorded fields.
- **Two recorded fields**, WISE 0855−0714 and Barnard's Star, in `cache/fixtures/`. They are real SPHEREx
  data saved by the engine, each with five older-survey images, and the web app carries its own copies, so
  they load with no server at all.
- **The web site** (`web/`), built from the design files in `docs/design/`: a landing page at `/` and the
  comparator at `/look/`. The comparator takes its frames from the engine (or the bundled recorded fields)
  and uses the team backend's `/resolve` and `/stars` for search by name and for the hint about objects
  that have moved away from their catalogue position. All twelve removable parts of the design are in:
  search by name, the moved-object banner, hold to flip, side by side, the difference image, then and now,
  contrast and invert, the spotlight zoom, three-colour, the spectrum panel, catalogue markers and copy
  link. Each has a switch in `web/src/comparator/features.ts`. Checked in a browser at 1280×720, 1440×900
  and 390×844, with the engine running and with no back end at all. Without the engine, the two recorded
  fields show the engine's recorded answers for the catalogue markers and for the spectrum at the field's
  centre, labelled with the date they were recorded; anywhere else those two parts say that they are not
  available.

Measured on real data on Saturday (details and limits in `docs/ENGINE_NOTES.md`):

- Typing the challenge's own WISE 0855 coordinates brings up "WISE 0855-0714 was here in 2010. It is now
  127″ to the west." with a jump to the present position.
- The 2010 WISE image of the Barnard field shows the star 168″ south of where SPHEREx sees it in September
  2026 (10.4″ a year over 16.2 years; Gaia DR3 gives 10.39″). Older-survey images register on the SPHEREx frames to 0.2 to 0.3″
  rms. Positions compare between surveys; brightness does not, and the page says so.
- The spectrum of WISE 0855 reads 562 ± 45 µJy at 4.4 to 4.8 µm and nothing below 3.8 µm. Unsaturated
  field stars read within about 3% of 2MASS and AllWISE. Barnard's Star answers "Saturated: no reliable
  brightness", and RW Aurigae "indicative only".

Not done:

- **Nothing from this branch is deployed**: not the engine, not the web site. `fly.toml`, the Cloudflare
  Pages Function and the CI workflow have never run on those services. Where the engine and the site will
  run is still to be decided (`CLAUDE.md`, section 14).
- The checks in `docs/VALIDATION.md` and `docs/TARGETS.md` are all still unticked.

Known limits of the engine are listed at the end of [`docs/ENGINE_NOTES.md`](docs/ENGINE_NOTES.md); those
of the team backend in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Run it

Python 3.12 with [uv](https://docs.astral.sh/uv/) for both back ends, Node 24 for the web app.

```bash
# Team backend: http://localhost:8000
cd src/backend && uv sync && uv run uvicorn main:app --port 8000

# Frames engine: http://localhost:8080
cd api && uv sync && uv run pytest -q          # no network; what CI runs
cd api && uv run uvicorn tombaugh.main:app --reload --port 8080

# Web app: http://localhost:5173/ (landing page) and http://localhost:5173/look/ (comparator)
cd web && npm install && npm run dev
cd web && npm test && npm run lint && npm run build
```

The web app reads its addresses from `web/.env.local` (copy [`web/.env.example`](web/.env.example)):
`VITE_TEAM_API_URL` for the team backend, `VITE_ENGINE_URL` for the engine. Left empty, the engine is reached
through `/api` on the same origin, which the development server sends to `localhost:8080`. If that port is
taken, start the engine with `--port 8081` and the web app with `TOMBAUGH_API_URL=http://localhost:8081 npm
run dev`. With no engine running, the two recorded fields still load; other positions need the engine and
network access to IRSA and the bucket. More in [`web/README.md`](web/README.md).

## Where things are

- Contracts: [`docs/CONTRACT.md`](docs/CONTRACT.md) for the team backend, and
  [`docs/CONTRACT_FIELDS.md`](docs/CONTRACT_FIELDS.md) (Contract v1.0, machine-readable parts in
  `docs/contract/`) for the frames engine and the recorded fields.
- Designs: [`docs/design/`](docs/design/): the design system (`system/`), the landing page (`landing/`) and
  the comparator (`comparator/`).
- Notes: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (team backend, front end, and the team change log),
  [`docs/ENGINE_NOTES.md`](docs/ENGINE_NOTES.md) (the engine's history and known limits),
  [`docs/RUNBOOK.md`](docs/RUNBOOK.md) (deploying and operating), [`docs/TARGETS.md`](docs/TARGETS.md) and
  [`docs/VALIDATION.md`](docs/VALIDATION.md) (test targets and checks), [`docs/plan.md`](docs/plan.md) (the
  build plan approved on 14 November).
- Rules for the team and for coding assistants, and the open decisions: [`CLAUDE.md`](CLAUDE.md).

## Data

Tombaugh shows real data only. The images are SPHEREx Spectral Images, DR1
([10.26131/IRSA678](https://doi.org/10.26131/IRSA678)) and QR3
([10.26131/IRSA662](https://doi.org/10.26131/IRSA662)), from the NASA/IPAC Infrared Science Archive, read from
the public bucket `nasa-irsa-spherex` and through IRSA's services. Star positions and proper motions come
from Gaia DR3 (European Space Agency), and names are resolved with Sesame (CDS, Strasbourg). Every source,
with its credit and the acknowledgement texts, is in [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md).

Tombaugh is an independent student project, not an official NASA or SPHEREx tool.

## Use of AI

Code, tests and documents in this repository were written with the help of an AI coding tool, Claude Code
(Anthropic). What the tool did, and what the team decided and checked, is recorded in
[`docs/AI_USE.md`](docs/AI_USE.md), a draft the team still has to confirm.

## Licence

Apache License 2.0: see [`LICENSE`](LICENSE). It was added as a proposal and the team has still to confirm
it. It covers the code and documents of this repository. The survey data are not ours to license: see
[`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md).
