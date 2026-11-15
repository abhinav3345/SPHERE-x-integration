# Tombaugh Contract v1.0

The interface every lane builds against. It covers the HTTP API, the manifest, the binary frame file, the sky grid, time and wavelength bins, presets, and the fixtures.

**Change process.** This file is frozen. A change needs the data/backend owner's review (a human; see CLAUDE.md section 10), a version bump, regenerated fixtures and regenerated test vectors in the same pull request. Additive optional fields are a minor bump (1.x); anything else is 2.0.

## 1. Conventions

- Sky coordinates are ICRS, decimal degrees. Proper motions are mas/yr (`pmra` already includes cos δ). Parallax is mas.
- Times are MJD (UTC) as floats, plus ISO 8601 dates (`YYYY-MM-DD`) for display.
- `epoch_ref` is **2026.0** (Julian year). "Where the object is now" always means its position at `epoch_ref`, so cache keys never drift with the calendar.
- Image values are surface brightness in **MJy/sr**, background-subtracted. 1 MJy/sr = 23.5044 µJy/arcsec².
- Flux densities are **µJy**.
- Wavelengths are **µm**.
- JSON keys are `snake_case`. Unknown keys must be ignored by clients.

## 2. Sky grid

Every plane of a field shares one grid: a north-up gnomonic (TAN) projection centred on the field centre.

| Field | Meaning |
|---|---|
| `ra0`, `dec0` | Field centre: the requested position rounded to 4 decimals (0.36") |
| `pixscale_arcsec` | **3.075** (half the native 6.15" SPHEREx pixel; frames are resampled, not sharper) |
| `nx`, `ny` | `n = 2 * round(fov_arcsec / (2 * 3.075)) + 1`, always odd and square |
| `cx`, `cy` | `(n - 1) / 2`: the pixel whose centre is exactly (`ra0`, `dec0`) |

Allowed `fov` values (arcmin) and sizes: 3 → 59, 4 → 79, 5 → 99, **6 → 119 (default)**, 8 → 157, 10 → 197.

**Pixel convention.** Arrays are row-major. **Row 0 is the northern edge (top); column 0 is the eastern edge (left).** Pixel centres sit at integer coordinates. So `x` grows to the west (right on screen) and `y` grows to the south (down on screen), which is exactly how a canvas draws.

**Sky → pixel.** With α, δ the target, α₀, δ₀ the centre (radians), and `k = 206264.806 / pixscale_arcsec`:

```
D  = sin δ₀ sin δ + cos δ₀ cos δ cos(α − α₀)
ξ  = cos δ sin(α − α₀) / D                              (east positive)
η  = (cos δ₀ sin δ − sin δ₀ cos δ cos(α − α₀)) / D       (north positive)
x  = cx − k ξ
y  = cy − k η
```

**Pixel → sky.** `ξ = (cx − x)/k`, `η = (cy − y)/k`, then

```
ρ = sqrt(ξ² + η²),  c = atan(ρ)
δ = asin(cos c sin δ₀ + η sin c cos δ₀ / ρ)            (δ = δ₀ when ρ = 0)
α = α₀ + atan2(ξ sin c, ρ cos δ₀ cos c − η sin δ₀ sin c)
```

Both languages implement exactly these formulas (`api/tombaugh/grid.py`, `web/src/player/grid.ts`) and are tested against `docs/contract/vectors/grid.json`, which is generated from astropy as an independent reference.

## 3. Time bins

A frame of the blink is a **time bin**, not a raw exposure.

1. Sort exposures by mid-time. Start a new bin at every gap longer than **20 days**.
2. Any bin spanning more than **60 days** (continuous coverage near the ecliptic poles and in the deep fields) is split into equal parts no longer than **30 days**.

A normal visit lasts 2–6 weeks and its detectors cross the target on different days, so a visit must stay whole to keep all wavelengths. The three numbers are recorded in the manifest as `time_binning` so they can be tuned without a contract change.

At most **600** exposures are used per field. Beyond that they are sampled deterministically (evenly per time bin and detector, ordered by `obs_id`) and the manifest says how many of how many were used.

## 4. Wavelength bins and presets

Each of the six detectors is cut into **4 equal wavelength sub-bins**, giving 24 wave bins. An exposure belongs to the bin containing its wavelength **at the field centre**.

| Detector | Range (µm) |
|---|---|
| 1 | 0.744 – 1.116 |
| 2 | 1.099 – 1.651 |
| 3 | 1.636 – 2.421 |
| 4 | 2.423 – 3.822 |
| 5 | 3.809 – 4.420 |
| 6 | 4.412 – 5.002 |

`wave_bin.id = (detector − 1) * 4 + sub` with `sub` in 0..3 from blue to red.

The server ships **one plane per (time bin, wave bin)** that has data. The browser forms a displayed frame as a weighted sum of planes; it never needs the raw exposures.

Presets live in `docs/contract/presets.json`, the single source used by both languages. A preset selects wave bins by detector list or by wavelength range (a bin is selected when its centre lies inside the range).

```
frame(t)  = Σ_b w_b · P(t, b) / Σ_b w_b          over selected bins b with a finite pixel
σ_frame   = sqrt(Σ_b w_b² σ_b²) / Σ_b w_b
weights   = "uniform": w_b = 1 (default, keeps the colour mix stable between visits)
            "ivar":    w_b = 1 / σ_b²  ("maximum S/N")
```

A frame is **partial** when its set of contributing wave bins differs from the union across time bins, and **thin** when fewer than 8 exposures went into it. Clients grey such frames and exclude them from differences.

## 5. Manifest

`GET /api/fields` returns this JSON when a field is ready.

```jsonc
{
  "contract": "1.0",
  "status": "ready",                 // "ready" | "partial" | "empty"
  "key": "f3a9c1d2e4b5a697",          // content key: centre, fov, epoch_ref, pipeline version, exposure set
  "request": { "ra": 133.7599, "dec": -7.2418, "fov_arcmin": 6 },
  "centre": { "ra": 133.7599, "dec": -7.2418 },
  "epoch_ref": 2026.0,
  "grid": { "nx": 119, "ny": 119, "cx": 59, "cy": 59, "pixscale_arcsec": 3.075,
            "projection": "TAN", "row0": "north", "col0": "east" },
  "time_binning": { "gap_days": 20, "max_span_days": 60, "sub_span_days": 30 },
  "time_bins": [
    { "id": 0, "mjd_start": 60979.72, "mjd_end": 60993.91, "mjd_mid": 60986.8,
      "date_start": "2025-10-31", "date_end": "2025-11-14",
      "n_exposures": 110, "detectors": [1, 2, 3, 4, 5, 6] }
  ],
  "wave_bins": [ { "id": 0, "detector": 1, "lam_min": 0.744, "lam_max": 0.837 } /* … 24 */ ],
  "planes": [
    { "index": 0, "kind": "sci", "mission": "SPHEREx",
      "time_bin": 0, "wave_bin": 20, "band": null,
      "lam_min": 4.412, "lam_max": 4.5595, "lam_eff": 4.49,
      "n_exposures": 5, "sigma": 0.021,           // robust noise of this plane, MJy/sr
      "mjd_mid": 60990.1, "date_start": "2025-11-07", "date_end": "2025-11-14",
      "offset": 0 }                               // byte offset in frames.bin
  ],
  "frames": { "url": "/api/fields/f3a9c1d2e4b5a697/frames.bin?v=<16 hex>",
              "dtype": "float16", "byteorder": "little",
              "nbytes": 2039184, "sha256": "…" },
  "exposures": { "found": 258, "used": 258, "sampled": false,
                 "collections": { "spherex_dr1": 258 },
                 "newest_mjd": 61174.29, "newest_date": "2026-05-14" },
  "provenance": { "pipeline_version": "0.2.0", "built_at": "2026-11-14T12:30:00Z",
                  "data_dois": ["10.26131/IRSA678", "10.26131/IRSA662"],
                  "notes": ["resampled to 3.075\"/px; native pixel 6.15\"; resolution about 10\""] },
  "warnings": []
}
```

- `status: "empty"` (HTTP 200) means no public SPHEREx exposure covers the position. `planes` is empty and `frames` is null. This is a normal, honest answer, not an error.
- `status: "partial"` means the build hit its deadline; `warnings` says what is missing.
- `kind` is `"sci"` for SPHEREx stacks and `"legacy"` for Then & Now planes. A legacy plane has `mission` `"AllWISE"` or `"2MASS"`, a `band` (`"W1"`, `"W2"`, `"J"`, `"H"`, `"Ks"`), `time_bin: null`, `wave_bin: null`, its own dates, and `"scaled": "field_stars"`. Its brightness is not comparable with SPHEREx; only positions are. Since pipeline 0.3.0 legacy planes follow every SPHEREx plane (in the band order above); a band whose survey image could not be fetched, or whose brightness could not be matched on field stars, is left out and `warnings` says so (clarified on 14 Nov 2026).
- A legacy plane's values are the survey image (its background removed) times one gain: the median ratio of the aperture fluxes of unsaturated field stars found both in the plane and in its paired SPHEREx frame (`legacy_pairs` in `presets.json`). They are therefore on that frame's MJy/sr scale for display only, not a photometric calibration (bands, beams and epochs differ), and `sigma` is on the same scale. A plane that cannot be scaled so is not served in the survey's own unit; whether it may be is the data/backend owner's decision (clarified on 14 Nov 2026).
- `frames.url` is opaque: fetch it exactly as given and never build it from `key`. Since pipeline 0.2.0 it ends in `?v=<first 16 hex characters of frames.sha256>`, so that one URL always names the same bytes (clarified on 14 Nov 2026; a v1.0 client that follows `frames.url` needs no change).
- Fixture manifests add `fixture_stars`: three Gaia DR3 stars as `{ "source_id", "ra", "dec", "x", "y" }` at the fixture's reference date, for decoder and grid tests.

## 6. frames.bin

- The planes concatenated in `planes[].index` order, nothing else. No header.
- Each plane is `ny × nx` **little-endian IEEE float16**, row-major, row 0 north, column 0 east.
- **NaN means no data** (off detector, masked, or saturated core). Clients must draw NaN with an explicit "no data" style and never as zero.
- `plane.offset = index × ny × nx × 2`.
- `sha256` in the manifest is over the uncompressed bytes. The file is immutable: served with `Content-Encoding: gzip` and `Cache-Control: public, max-age=31536000, immutable`.
- Browsers without `Float16Array` decode with `DataView.getFloat16` or the fallback table decoder in `web/src/player/float16.ts`.

## 7. HTTP API

Base path `/api`. All responses are JSON except `frames.bin`.

| Method and path | Purpose |
|---|---|
| `GET /api/fields?ra=&dec=&fov=` | Build or fetch a field. Idempotent: repeat the same request to poll |
| `GET /api/fields?fixture=<name>` | Fixture mode: returns a recorded real manifest (`wise0855`, `barnard`) |
| `GET /api/fields/{key}/frames.bin?v=<16 hex>` | The immutable frame file, as named by `frames.url`. 404 `not_found` when no copy under `key` has that hash. Without `v` the server answers with the copy it holds |
| `GET /api/fields/{key}/spectrum?ra=&dec=` | Quick-look spectrophotometry at a position inside the field |
| `GET /api/fields/{key}/overlays` | Gaia DR3 and CatWISE sources in the field, with positions per time bin |
| `GET /api/resolve?q=` | Name or coordinate string → position, proper motion, position at `epoch_ref` |
| `GET /api/status` | Pipeline version, newest public exposure, upstream health, cache and build state |
| `GET /healthz` | Liveness. Must answer while a build is running |

**Building.** While a field is being built the same GET returns **HTTP 202**:

```json
{ "contract": "1.0", "status": "building",
  "progress": { "stage": "fetch", "done": 120, "total": 258 }, "retry_after_s": 1 }
```

`stage` is `"discover"`, `"fetch"` or `"stack"`. One build runs at a time; up to 8 wait; beyond that the API answers 429. A build nobody has polled for 20 s is cancelled. A build that reaches 120 s returns what it has with `status: "partial"`.

**Errors.** `{ "contract": "1.0", "status": "error", "code": "…", "message": "…" }`

| HTTP | `code` | When |
|---|---|---|
| 400 | `bad_request` | Missing or out-of-range `ra`, `dec`, `fov` |
| 404 | `not_found` | Unknown key or fixture |
| 429 | `busy` | Build queue full or rate limit hit (`Retry-After` header set) |
| 503 | `upstream_unavailable` | Archive unreachable and nothing cached |
| 500 | `internal` | Anything else |

### 7.1 Spectrum

```jsonc
{
  "contract": "1.0", "status": "ok",
  "state": "ok",                      // "ok" | "indicative" | "saturated" | "contaminated" | "no_data"
  "target": { "ra": 133.7599, "dec": -7.2418,
              "snapped_to": { "catalog": "catwise", "id": "J085508.34-071439.2", "sep_arcsec": 0.8 },
              "pmra": -7965, "pmdec": 806, "parallax": 439, "epoch": 2015.4 },
  "neighbours": [ { "catalog": "catwise", "id": "J085501.95-071428.2", "sep_arcsec": 7.5, "fitted": true } ],
  "method": { "kind": "joint_psf", "radius_px": 2, "encircled_energy": 0.96,
              "annulus_px": [5, 9], "systematic_floor": 0.03 },
  "time_span": { "mjd_min": 60800.7, "mjd_max": 61174.3 },
  "points": [ { "lam": 4.49, "dlam": 0.037, "mjd": 60990.1, "det": 6, "time_bin": 0,
                "flux_ujy": 512.0, "err_ujy": 133.0, "flags": 0, "quality": "good" } ],
  "binned": [ { "time_bin": 0, "lam": 4.6, "lam_min": 4.412, "lam_max": 5.002,
                "flux_ujy": 488.0, "err_ujy": 40.0, "n": 19 } ]
}
```

- `snapped_to.catalog` names where the target's astrometry came from: `"gaia"`, `"catwise"`, or, for an object whose published astrometry the server holds, the service it was read from (`"simbad"` for WISE 0855). `snapped_to` is null when no source lies within one native pixel (6.15") of the click; the click is then measured where it is (clarified on 14 Nov 2026).
- A spectrum that misses exposures (a read failed, or the deadline passed) is answered with `Cache-Control: no-store` and the header `X-Tombaugh-Incomplete: <n> of <m> exposures not measured; not cached`; its JSON is unchanged. `upstream_unavailable` (503) also answers when the catalogues that place the target and its neighbours cannot be reached, and `busy` (429) when other spectra are being measured (clarified on 14 Nov 2026).
- `state: "saturated"` means the core is blank in the data: `points` is empty and the client shows "saturated: no reliable photometry".
- `state: "indicative"` means the core carries the OVERFLOW flag: points are returned with `quality: "saturated"` and drawn hollow.
- `state: "contaminated"` means a catalogued neighbour lies within 15" and could not be fitted jointly.
- `quality` is `"good"`, `"flagged"` or `"saturated"`. `flags` is the SPHEREx bit mask OR-ed over the aperture.
- `err_ujy` already includes the 3% systematic floor in quadrature.
- A `binned` value's `err_ujy` also includes, in quadrature, a background term of its detector (25 µJy for detectors 1–4, 35 µJy for 5–6, measured on blank sky) and the bin's measured annulus skew (large in crowded fields): the sky under a faint source is not known better than that, and averaging exposures does not remove it. `lam_min`/`lam_max` are the wave bin's edges, widened to the members' own `lam` where a point lies just beyond its detector's nominal range, so `lam` always lies between them (clarified on 14 Nov 2026).
- `snapped_to.sep_arcsec` is the separation of this request's click from the source; a kept spectrum is shared by every click that snaps to the same source (clarified on 14 Nov 2026).
- `method.kind` is `"aperture"` or `"joint_psf"`.

### 7.2 Resolve

```jsonc
{ "contract": "1.0", "status": "ok", "query": "WISE 0855-0714", "name": "WISE J085510.83-071442.5",
  "ra": 133.795129, "dec": -7.245147, "epoch": 2010.3,
  "pmra": -8118, "pmdec": 680, "parallax": 439,
  "ra_ref": 133.7599, "dec_ref": -7.2422, "moved_arcsec": 127.0,
  "otype": "BrownD*", "source": "sesame:cfa" }
```

- `ra`/`dec` are the catalogue position at `epoch`; `ra_ref`/`dec_ref` are the position at `epoch_ref`. Clients centre on the `_ref` position and draw the catalogue position as a ghost marker.
- A plain coordinate string resolves to itself, plus `movers`: fast movers (> 300 mas/yr) within 6' whose track passes within 15" of the typed position between 1995 and `epoch_ref`: `[ { "name", "ra_ref", "dec_ref", "moved_arcsec", "pm_arcsec_yr", "year_at_position" } ]`. This powers the "it has moved, jump" banner.
- `status: "not_found"` for unknown names. `status: "solar_system"` with a `message` for planets, asteroids and comets.

### 7.3 Overlays

```jsonc
{ "contract": "1.0", "status": "ok",
  "gaia": [ { "source_id": "4472832130942575872", "ra": 269.4485, "dec": 4.7394, "epoch": 2016.0,
              "pmra": -801.551, "pmdec": 10362.394, "parallax": 546.976, "g": 8.19,
              "track": [ { "time_bin": 0, "ra": 269.4462, "dec": 4.7672 } ] } ],
  "catwise": [ { "id": "J085501.95-071428.2", "ra": 133.7581, "dec": -7.2412, "epoch": 2015.4,
                 "pmra": 12, "pmdec": -30, "w1": 14.98, "w2": 15.05 } ],
  "upstreams": { "gaia": "ok", "catwise": "stale" } }
```

`track` is present only for sources moving faster than 50 mas/yr, includes parallax, and is computed by the server so there is a single implementation of propagation. `upstreams` values are `"ok"`, `"stale"` (cached copy served) or `"unavailable"`.

- A CatWISE motion moves a marker only when it passes the server's checks (most fast CatWISE motions near bright stars are not real); a source that fails them has no `track` and stays at its catalogue position (clarified on 14 Nov 2026).
- An object whose published astrometry the server holds (WISE 0855) keeps one CatWISE entry, its most significant, whose `track` comes from that published astrometry (parallax included), not from CatWISE's motion; its other CatWISE entries, the object listed again, are left out. Its `ra`, `dec`, `pmra`, `pmdec` and `epoch` stay CatWISE's own (clarified on 14 Nov 2026).

### 7.4 Status

```jsonc
{ "contract": "1.0", "status": "ok", "pipeline_version": "0.1.0",
  "newest_exposure": { "mjd": 61318.0, "date": "2026-10-05" },
  "upstreams": { "irsa_sia": { "ok": true, "latency_ms": 1600, "checked_at": "2026-11-14T12:00:00Z" },
                 "s3": { "ok": true, "latency_ms": 90, "checked_at": "2026-11-14T12:00:00Z" } },
  "cache": { "used_mb": 412, "free_mb": 2588 },
  "builds": { "active": 0, "queued": 0 } }
```

## 8. Fixtures

`cache/fixtures/<name>/manifest.json` and `frames.bin` are **real SPHEREx data** produced by the production pipeline (`python -m tombaugh.tools.make_fixture <name>`), never hand-made. Two exist at v1.0:

| Name | Centre | Why |
|---|---|---|
| `wise0855` | WISE 0855−0714 at `epoch_ref` | Only visible in the 4–5 µm bins; moves ~4.5" per half-year; has a blended neighbour |
| `barnard` | Barnard's Star at `epoch_ref` | Moves 10.25" per year; saturated core (NaN handling) |

The web app carries copies under `web/public/fixtures/` so the front end runs with no API. Golden tests assert: each `fixture_stars` entry maps to its recorded pixel within 0.5 px; `frames.bin` matches its `sha256`; WISE 0855's "cold" frame has a source within 2 px of the centre in the full visits; Barnard's centroid moves north between the first and last time bins.

**Recorded answers** (clarified on 15 Nov 2026; the JSON of 7.1 and 7.3 is unchanged). A recorded field may also hold `overlays.json` and `spectrum.json`: the engine's real answers to `GET /api/fields/{key}/overlays` and to `GET /api/fields/{key}/spectrum` at the manifest's `request` position, for `{key}` the field's own key, written by `python -m tombaugh.tools.record_answers <name>` and never by hand. Both are optional: a recorded field without them is valid. Each file is one JSON object, compact, with one trailing newline:

```jsonc
{ "contract": "1.0", "kind": "recorded_answer",
  "route": "spectrum",                          // "overlays" | "spectrum"
  "field": "wise0855",                          // the recorded field's name
  "key": "5c321dc84550bfba",                    // the manifest's key
  "pipeline_version": "0.3.0",                  // the manifest's provenance.pipeline_version
  "recorded_at": "2026-11-15T00:01:42Z",        // UTC
  "request": { "ra": 133.7598, "dec": -7.2422 },  // {} for overlays; for a spectrum, the manifest's request
  "response": { "contract": "1.0", "status": "ok", "state": "ok" /* … the route's body, byte for byte */ } }
```

Only a final answer is recorded: HTTP 200, a body of the contract's shape, for overlays both `upstreams` "ok", for a spectrum no `X-Tombaugh-Incomplete` header. A client uses a recorded answer under these rules:

- **R1.** A recorded answer belongs to one recorded field. It is used only for a field whose manifest `key` equals the envelope's `key`, and only when `contract`, `kind`, `route` and `field` are as expected and `response` passes the same validation as a live answer.
- **R2.** Live answers win. The client asks the engine first, as it does without recorded answers. A recorded answer is used only when no live answer can be had: the field itself came from the bundled copy (the engine is unreachable), or the request to the engine failed (network error, timeout, 404, 429, 5xx), or, for overlays only, the live answer marks an upstream `"unavailable"`.
- **R3.** The recorded spectrum applies only while the selected position is the pixel of the envelope's `request` position (a recorded field's default selection). Anywhere else the client says what it says when no spectrum can be measured.
- **R4.** A recorded answer on screen is always labelled as recorded, with the UTC date of `recorded_at`: once in the spectrum panel while a recorded spectrum is shown, and once among the caveats while recorded catalogue markers are drawn. Nothing may suggest that it is live.
- **R5.** A missing file (404), or an envelope that fails R1, is not an error for the reader: the client behaves as it does when the field has no recorded answer.

Golden tests (`api/tests/test_recorded_answers.py`) hold each file to its field: the envelope above, a response that is the contract model's own JSON with its recorded digest, overlays equal to what the engine computes offline from the catalogue answers kept in `api/tests/data/catalogs`, and a spectrum measured for what those overlays say at the request position.

## 9. Shared code interfaces

- **Python** (`api/tombaugh/models.py`, pydantic): `Exposure`, `Cutout`, `TimeBin`, `WaveBin`, `Plane`, `Manifest`, `SpectrumResponse`, `ResolveResponse`, `OverlaysResponse`. These models are the source of truth; `docs/contract/manifest.schema.json` is exported from them.
- **TypeScript** (`web/src/contract.ts`): the same shapes as interfaces.
- **Grid** (`web/src/player/grid.ts`): `skyToPixel(grid, ra, dec) → {x, y}` and `pixelToSky(grid, x, y) → {ra, dec}` in plane pixel coordinates.
- **Viewport** (`web/src/player/`): exposes `skyToScreen`, `screenToSky` and `onSkyClick(cb)` on top of the grid functions, so panels never do their own projection maths.
- **Presets**: `docs/contract/presets.json`, read by both languages. No preset is defined anywhere else.
