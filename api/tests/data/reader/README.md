# Recorded reader samples

Real bytes from the public SPHEREx archive, recorded once so that the reader tests run with no network.
Nothing here is simulated or edited. Everything was written by `record_samples.py` in this folder
(run from `api/`: `uv run python tests/data/reader/record_samples.py`; it needs IRSA and the bucket).

Recorded on 14 Nov 2026 for the contract's example field, RA 133.7599, Dec -7.2418 (ICRS degrees).

| File | What it is |
|---|---|
| `sia_excerpt.csv` | The header line and 8 rows, spread evenly through the 258, of IRSA's SIA answer for collection `spherex_dr1` (`POS=circle 133.759900 -7.241800 0.010000`, `RESPONSEFORMAT=csv`). Byte for byte, including the unquoted JSON in `cloud_access`. |
| `exposure.json` | The one exposure the byte ranges come from: obs_id `2025W19_1B_0116_1`, detector 3, object `dr1/level2/2025W19_1B/l2b-v27-2026-197/3/level2_2025W19_1B_0116_1D3_spx_l2b-v27-2026-197.fits` (65,790,720 bytes), and the request (`half_px` 8). |
| `ranges.npz` | Every byte range `read_window` asked for, keyed `<start>_<end>` (half-open, uint8). Six for the normal path, two more for the sequential walk. |
| `expected.npz` | The same window by an independent route. |

## Byte ranges in `ranges.npz`

| Key | Bytes | Content |
|---|---|---|
| `0_34560` | 34,560 | head: PRIMARY header and IMAGE header |
| `1249920_1388640` | 138,720 | IMAGE rows 150 to 166, full width |
| `16672320_16705920` | 33,600 | FLAGS header and its 2040 row descriptors |
| `17579623_17680098` | 100,475 | FLAGS heap: the Rice tiles of rows 150 to 166 |
| `46457280_46489920` | 32,640 | ZODI rows 156 to 159 |
| `29799360_29832000` | 32,640 | VARIANCE rows 156 to 159 |
| `28514880_28526400` | 11,520 | VARIANCE header (only read by the sequential walk) |
| `45172800_45184320` | 11,520 | ZODI header (only read by the sequential walk) |

## How `expected.npz` was made

The whole object was downloaded once and opened with `astropy.io.fits`, so none of the reader's offsets
or decoding is involved:

- `image`: `hdus["IMAGE"].data[150:167, 353:370]` (float32, MJy/sr).
- `flags`: the FLAGS HDU decompressed in full by astropy as a `CompImageHDU`, then the same slice (int32).
- `x`, `y`, `x0`, `y0`: the detector pixel of the position, from solving the forward WCS (with SIP)
  numerically with `scipy.optimize.fsolve`, not with astropy's inverse.
- `lam`, `dlam` (micron): a hand-written bilinear lookup in the file's own WCS-WAVE table, checked
  against wcslib to 1e-9 micron.
- `mjd`, `psf_fwhm`: `MJD-AVG` and `PSF_FWHM` of the IMAGE header as astropy reads them from the file.
- `zodi_level`, `sky_var`: medians of `hdus["ZODI"].data[156:160, 353:370]` and of the same slice of VARIANCE.

The recorder also wrote `tombaugh/data/wcs_wave_D1.fits` to `wcs_wave_D6.fits`: the last 5760 bytes
(the WCS-WAVE HDU) of one real file per detector behind an empty primary HDU. For each detector the HDU
was compared with that of a second file a year later and found identical, header included.
