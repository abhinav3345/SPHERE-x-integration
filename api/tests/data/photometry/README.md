# Recorded photometry samples

Real windows from the public SPHEREx archive, recorded once so that `tests/test_photometry.py` runs with no
network. Nothing here is simulated or edited. Everything was written by `record_samples.py` in this folder (run
from `api/`: `uv run python tests/data/photometry/record_samples.py`; it needs IRSA and the bucket), on
14 Nov 2026, through the production code: `discovery.discover`, `build.sample_exposures`,
`remote_fits.read_windows` with `photometry.WINDOW_HALF_PX` (11, so 23 x 23 native pixels) centred on the target
at the mean time of the field's exposures, exactly as `photometry.measure` reads them, and
`photometry.fetch_psf_table` for the point-spread functions.

| File | What it is |
|---|---|
| `windows.npz` | For each of 16 windows: `image_<i>` (float32, MJy/sr, zodiacal light not subtracted), `flags_<i>` (int32 SPHEREx bit mask) and `header_<i>` (the IMAGE header text, zlib-compressed, as uint8). |
| `windows.json` | For each window, in the same order: its sample set, the exposure (obs_id, detector, MJD, collection, bucket key), `x0`, `y0`, `lam`, `dlam`, `mjd`, `psf_fwhm`, `zodi_level`, `sky_var` and `version` as the reader returned them. |
| `psf.npz` | For each detector used: `xcenter_<d>`, `ycenter_<d>`, `cwave_<d>` of every zone of its EPSF table, and `zones_<d>`, `stamps_<d>`: the ids and 33 x 33 stamps of the 14 zones these windows use (target and neighbour). Other zones are not kept, to stay small. |
| `sets.json` | The astrometry used for each set, with its source. |

## Sample sets

| Set | Field centre | Windows | Why |
|---|---|---|---|
| `wise0855` | 133.7598, -7.2422 | 4 of detector 6 (4.4 to 5.0 micron), one each of detectors 1, 2, 3; two visits | A cold brown dwarf blended with a star 4 to 11" away: the joint fit must give about 550 microjansky at 4.5 micron and nothing below 2.4 micron |
| `barnard` | 269.4463, 4.7682 | 2 of detector 1, 2 of detector 2, 1 of detector 6 | A saturated core: the answer must be "saturated" |
| `empty` | 133.7514, -7.2616 | one each of detectors 1, 3, 5, 6 | 21.6" from the nearest CatWISE2020 source, 25" or more from 2MASS and AllWISE sources: fluxes consistent with zero |

Astrometry: WISE 0855 from SIMBAD quoting Kirkpatrick et al. 2021 (as in `tombaugh/tools/make_fixture.py`);
Barnard's Star from Gaia DR3 4472832130942575872 (same file); the neighbour CatWISE2020 J085501.95-071428.2 from
VizieR II/365 at the CfA mirror (position at epoch 2015.405, motion 8.69 and -4.39 mas/yr).

Windows are picked by a fixed rule (`counts[det]` exposures per detector, spread evenly through the field's list),
not by looking at their pixels.
