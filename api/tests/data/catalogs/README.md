# Recorded catalogue answers

Real answers of the two catalogue services that `tombaugh.catalogs` asks, recorded once so that
`tests/test_catalogs.py` runs with no network. Nothing here is simulated or edited: each file is the service's
answer byte for byte, gzip-compressed (`gzip.compress(body, mtime=0)`).

Recorded on 14 Nov 2026 at 19:55 UTC by `record_samples.py` in this folder (run from `api/`:
`uv run python tests/data/catalogs/record_samples.py`; it needs the network). `samples.json` lists every
request in full (URL, parameters), how many rows came back and how long each took.

The two fields are the recorded fixtures `cache/fixtures/wise0855` (centre 133.7598, -7.2422) and
`cache/fixtures/barnard` (centre 269.4463, 4.7682), 119 x 119 pixels of 3.075 arcsec. The search radius is
`catalogs.search_radius_deg`: the grid's corner plus the path of the fastest known star between the
catalogue epoch and the last visit.

| File | Service | Rows | Seconds |
|---|---|---|---|
| `gaia_wise0855.csv.gz` | Gaia DR3, ARI Heidelberg TAP (`gaiadr3.gaia_source`), radius 0.10304 deg | 282 | 1.40 |
| `gaia_barnard.csv.gz` | the same, radius 0.10304 deg | 2636 | 0.19 |
| `catwise_wise0855.tbl.gz` | CatWISE2020, IRSA Gator (`catwise_2020`, IPAC table), radius 374.36 arcsec | 1388 | 3.27 |
| `catwise_barnard.tbl.gz` | the same, radius 377.90 arcsec | 2196 | 2.76 |

Gaia columns: `source_id, ra, dec, pmra, pmdec, parallax, radial_velocity, phot_g_mean_mag` (CSV).
CatWISE columns: `source_name, ra_pm, dec_pm, pmra, pmdec, sigpmra, sigpmdec, w1mpro_pm, w2mpro_pm`
(Gator adds `clon, clat, dist, angle`); motions in arcsec/yr as the catalogue gives them.

The folder holds about 390 kB.
