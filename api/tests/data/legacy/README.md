# Recorded "Then and now" samples

Real answers of IRSA, recorded once so that `tests/test_legacy.py` runs with no network. Nothing here is
simulated or edited, apart from the SIA excerpts described below. Everything was written by
`record_samples.py` in this folder (run from `api/`: `uv run python tests/data/legacy/record_samples.py`;
it needs IRSA), which asks exactly what `tombaugh.legacy.build_legacy_planes` asks.

Recorded on 14 Nov 2026 for a 3' grid (59 x 59 pixels of 3.075") centred on the recorded WISE 0855 field,
RA 133.7598, Dec -7.2422 (ICRS degrees), bands W2 and Ks. `requests.json` lists every request: URL, query
parameters, length and SHA-256 of what was saved.

| File | What it is |
|---|---|
| `sia_wise_allwise_0.tsv` | Excerpt of IRSA's SIA v2 answer for `COLLECTION=wise_allwise`, `POS=circle 133.759800 -7.242200 0.035635`, `RESPONSEFORMAT=TSV`: the header line and every row of bands W2 and W3 (all subtypes), whole lines in the order served. The whole answer (24,479 bytes) also held W1 and W4 rows. |
| `sia_twomass_allsky_0.tsv` | Excerpt of the same query for `COLLECTION=twomass_allsky`: the header line and every row of bands K and J. The whole answer (20,792 bytes) also held H rows. |
| `cutout_W2_1342m076_ac51.fits.gz` | IBE cut-out of the AllWISE Atlas image `1342m076_ac51-w2-int-3.fits`, `center=133.759800,-7.242200&size=233arcsec&gzip=true`, gzip as served (170 x 170 pixels of 1.375"). |
| `cutout_Ks_allsky_981228s_s094_0209.fits.gz` | IBE cut-out of the 2MASS Atlas image `981228s/s094/image/ki0940209.fits.gz`, `size=264arcsec`, as served; clipped by the service at the image edge. |
| `cutout_Ks_allsky_981228s_s093_0068.fits.gz` | The same for `981228s/s093/image/ki0930068.fits.gz`. The 3' field straddles the edge between 2MASS scans 93 and 94, so Ks is a mosaic of these two images. |
| `record_samples.py` | The recorder. |
