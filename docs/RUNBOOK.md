# Runbook

How to deploy Tombaugh, check that it is healthy, and react when something upstream changes.

Tombaugh has three deployable parts: the team backend (`src/backend/`), the frames engine (`api/`) and the
static site (`web/`). Where the engine and the site run, and who owns those accounts, is still open
(`CLAUDE.md`, section 14).

**State on Saturday 14 November 2026, about 19:30 GMT.**

- **RUN, by its owner:** the team backend is deployed on Render's free tier. Its address is not written in
  the repository. The checks in `docs/VALIDATION.md` have not been ticked.
- **RUN, locally:** the engine's container image was built and run (`docker build -t tombaugh-api .`, then
  `/healthz` and a recorded field answered from the container).
- **NOT RUN:** everything else on this page. The engine and the site are not deployed. No Fly or Cloudflare
  command has been run: they were written without either tool at hand, so check each one against the tool's
  own help before relying on it. Steps marked **PLANNED** depend on something that does not exist yet.

## 1. Deploy

### Accounts and settings

| What | Where it is set | What it is for |
|---|---|---|
| Render account (used by the team backend's owner) | render.com | Hosts the team backend. Also an option for the engine (below) |
| Fly.io account with a payment card | fly.io | Option for the engine (`fly.toml`, `Dockerfile`) |
| Cloudflare account | cloudflare.com | Option for the web app (Pages) and the proxy function |
| `VITE_TEAM_API_URL`, `VITE_ENGINE_URL` | Build settings of the static host (`web/.env.example`) | Addresses compiled into the page: the team backend, and the engine (empty: same origin, `/api` through the proxy). Not secret |
| `TOMBAUGH_CORS_ORIGINS` | Engine environment (optional) | Origins allowed to call the engine directly; default `http://localhost:5173`. Needed when `VITE_ENGINE_URL` points to another origin than the site |
| `FLY_API_TOKEN` | GitHub repository secret | **PLANNED**: a deploy job in CI. A `fly deploy` from a logged-in terminal does not need it |
| `ORIGIN_URL` | Cloudflare Pages project, variable | Address of the API, for example `https://tombaugh-api.fly.dev`. Read by `web/functions/api/[[path]].ts` |
| `PROXY_SECRET` | Cloudflare Pages project, secret | The proxy sends it as `x-tombaugh-proxy-secret` |
| `TOMBAUGH_PROXY_SECRET` | Fly secret, the same value as `PROXY_SECRET` | When set, the API refuses `/api` requests without it and charges new builds to the visitor address the proxy forwards (`x-forwarded-client-ip`). When unset, every visitor behind the proxy counts as one client for the limit below |
| `TOMBAUGH_RATE_BURST`, `TOMBAUGH_RATE_PER_MINUTE` | Fly variables (optional) | Limit on NEW builds per client: 5 at once, then 3 a minute by default. Cached and recorded fields are not limited. Raise the burst for an audience behind one address |
| `TOMBAUGH_CONTACT` | Fly secret (optional) | Contact text in the User-Agent sent to the archives (`api/tombaugh/http.py`) |

### The team backend, on Render (RUN, by its owner)

The settings below are the ones recorded in the team backend's notes (`docs/ARCHITECTURE.md`); the service
was set up by its owner, outside this page.

- Root directory `src/backend`; build `uv sync`; start `uv run uvicorn main:app --host 0.0.0.0 --port $PORT`.
- It deploys from `main`, so a merge into `main` can deploy it again. [VERIFY] whether automatic deploys
  are on.
- Free tier: it sleeps when idle (call `/health` and wait up to 60 s before a demo), it has 512 MB of
  memory, and its disk is reset on every deploy, so whatever the demo needs must be committed in
  `src/backend/demo_cache/`.
- **NOT RUN** yet: write the address where the team can find it; run the checks in `docs/VALIDATION.md`.

### The frames engine as a second Render web service (option, NOT RUN)

One of the options for the engine (`CLAUDE.md` section 14, decision 2). Nothing has been tried. What the
repository says:

- The image is built from the `Dockerfile` at the repository root (the build context must include
  `cache/fixtures/`) and listens on port 8080.
- The engine keeps its cache in `TOMBAUGH_CACHE_DIR` (`/data/cache` in the image). Without a persistent
  disk, every restart or deploy starts with an empty cache and each field is built again (30 to 80 s for a
  new 6 arcmin field, measured from the venue).
- `fly.toml` asks for 2 GB of memory for one machine; the team backend's free instance has 512 MB. The
  engine's memory use during a build has not been measured.
- Unverified: how Render routes requests to the port of a Docker service, and which plan gives a
  persistent disk.

### The frames engine, on Fly.io (option, NOT RUN)

Blocking today: a Fly.io account with a payment card. The image builds locally (737 MB) and needs the
recorded fields in `cache/fixtures/`, which are in the repository.

```bash
fly auth login
fly apps create tombaugh-api     # or another name: then change `app` in fly.toml
fly config validate              # fly.toml has never been checked by the tool
fly deploy --ha=false            # builds ./Dockerfile; one machine in iad; creates the 3 GB volume on the first run
fly status                       # expect one started machine with passing checks
fly scale show                   # expect shared-cpu-2x with 2048 MB
```

- If the first deploy says the volume `tombaugh_data` is missing:
  `fly volumes create tombaugh_data --region iad --size 3`, then deploy again.
- Later deploys: `fly deploy` from an up-to-date `main`, by hand.
- Roll back: `fly releases --image` lists earlier images; `fly deploy --image <earlier image>` runs one.
- The container starts as root for one `mkdir` and `chown` of `/data/cache`, then runs the server as
  uid 10001. A shell opened with `fly ssh console` is root: do not create files in `/data/cache` by hand.

### The web app, on Cloudflare Pages (option, NOT RUN)

**PLANNED**: no Pages project exists yet, and the static host is not chosen (`CLAUDE.md` section 14).

- Project settings: root directory `web`, build command `npm run build`, output directory `dist`,
  environment variable `NODE_VERSION=24`, and `VITE_TEAM_API_URL` set to the team backend's address.
- Set `ORIGIN_URL` and `PROXY_SECRET` (table above). Pages finds `web/functions/` by itself; every
  `/api/*` request then goes through the function.
- On Vercel instead: copy `web/vercel.example.json` to `web/vercel.json` and replace the placeholder
  with the API address. A rewrite in `vercel.json` cannot add `x-tombaugh-proxy-secret` or
  `x-forwarded-client-ip`, so on that route the API cannot tell proxied requests from direct ones.

## 2. Check health

| Check | Tells you | State |
|---|---|---|
| `curl -fsS https://<render address>/health` | The team backend answers (`{"status": "ok"}`). The first call after a sleep can take up to 60 s | Answered on a developer machine on 14 November; not checked on Render from this repository |
| `curl -fsS https://<fly address>/healthz` | The API process answers. It must answer while a build runs (measured locally: median 1 ms during a build). Fly asks every 15 s (`fly.toml`) | In the code; works once deployed |
| `curl -fsS https://<site>/api/status` | Pipeline version, newest public exposure, upstream health (`irsa_sia`, `s3`), cache used and free, builds active and queued (Contract v1.0, section 7.4). The first answer after a start shows both upstreams with `checked_at: null`: the probe runs in the background, ask again | In the code; works once deployed |
| `fly status`, `fly checks list`, `fly logs` | Machine state, check results, server log | Works once deployed |
| External uptime monitor that alerts two owners | The site is down when nobody is looking | **PLANNED** |

`/healthz` is not under `/api`, so the proxy does not forward it: ask the Fly address directly.

When the site answers HTTP 503 with `"code": "upstream_unavailable"`, look at the response header
`x-tombaugh-proxy-error`:

- `origin_not_configured`: `ORIGIN_URL` is missing or not a URL in the Pages project.
- `origin_unreachable`: the proxy could not reach the API. Check `fly status`.
- header absent: the answer comes from the API itself, and the archive is the problem (next section).

## 3. When IRSA is down

Two upstreams matter, and they fail independently: IRSA's image search
(`https://irsa.ipac.caltech.edu/SIA`, finds the exposures) and the bucket `nasa-irsa-spherex` (pixels).

In the code today (`api/tombaugh/http.py`, `api/tombaugh/discovery.py`): connection errors, timeouts,
HTTP 5xx and 429 are retried with a jittered pause of 0.1 to 2 s, under a deadline (90 s by default for
discovery), with at most 2 requests to IRSA in flight. After that the call fails with `UpstreamError`.

In the service (`api/tombaugh/main.py`, covered by tests; not yet seen against a real outage):

- fields already built are served from the cache, also past their 24-hour check when the archive cannot
  be reached (the check is then repeated after 10 minutes);
- a position never built answers HTTP 503, code `upstream_unavailable`;
- the recorded fields (`?fixture=wise0855`, `?fixture=barnard`) need no upstream, and the web app
  carries its own copies of them;
- `/api/status` shows `upstreams.irsa_sia.ok: false`. It can lag by up to 5 minutes and probes once, so
  one failed probe is not proof of an outage.

What to do: nothing needs a restart. Look for a notice on <https://irsa.ipac.caltech.edu/>, show the
recorded fields meanwhile, and do not delete the volume: it holds every field built so far.

The team backend is affected differently (`docs/CONTRACT.md`, `docs/ARCHITECTURE.md`): its live `/frames`
uses IRSA TAP and cutouts and answers 502 when they fail; only presets would be served without IRSA, and
none has been computed yet. Its `/resolve` and `/stars` do not use IRSA.

## 4. When SPHEREx publishes a new release

The collections searched are the tuple `COLLECTIONS` in `api/tombaugh/discovery.py`: `spherex_dr1`,
`spherex_dr1_deep`, `spherex_qr3`, `spherex_qr3_deep` (checked against IRSA on 14 November 2026;
`spherex_qr2` returned nothing).

- New exposures inside a listed collection need no change. A cached field is checked against the archive
  again after 24 hours and rebuilt only when its list of exposures has changed.
- A new collection needs a code change and a deploy:
  1. Add its name to `COLLECTIONS`.
  2. Extend `KEY_PATTERN` in the same file. It accepts only object keys that start with `dr1/` or `qr3/`,
     and a row that fails it is dropped, not repaired.
  3. Check the preference in `merge_exposures`: of two copies of one exposure it keeps the `spherex_dr1`
     one.
  4. Add the new DOI to `docs/DATA_SOURCES.md`, and to `provenance.data_dois` of the manifest
     (`api/tombaugh/build.py`).
  5. Run `cd api && uv run pytest -q`, raise the pipeline version (`__version__` in
     `api/tombaugh/__init__.py` and `version` in `api/pyproject.toml`; a test keeps them equal), record the
     two fixtures again with `uv run python -m tombaugh.tools.make_fixture <name>`, deploy.
- **PLANNED**: read the list from run-time configuration, so that a release needs no deploy.
- How to notice a release: the SPHEREx page at IRSA, <https://irsa.ipac.caltech.edu/Missions/spherex.html>,
  and `newest_exposure` in `/api/status`.

## 5. Dated manual checks

The plan asks for a check by hand on three dates, with the service kept alive through 26 January 2027.
Every step is **PLANNED** until the service is deployed.

1. `curl -fsS https://<render address>/health` (the team backend), and `curl -fsS https://<fly address>/healthz`
   or the engine's address wherever it runs
2. `curl -fsS https://<site>/api/status`: both upstreams `ok`, free cache space, date of the newest exposure.
3. Open the site on a phone: one recorded field, and one coordinate that is not cached.
4. Look at the SPHEREx page at IRSA for a new collection (section 4).
5. `fly status` and `fly volumes list`; look at the month's cost on the Fly dashboard (the plan's limit
   is 5 US dollars a month).
6. Write the result in the table.

| Date | Done by (role) | Result |
|---|---|---|
| 2 December 2026 | | |
| 16 December 2026 | | |
| 25 January 2027 | | |
