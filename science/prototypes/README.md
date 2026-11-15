# Research prototypes (14 Nov 2026)

Scripts written during the first morning to test feasibility on real SPHEREx data. They are **not product
code**: they are kept so every lane can see exactly how each number in the plan was measured, and so the
production modules can be ported from tested logic rather than rewritten.

| File | What it shows |
|---|---|
| `spx.py` | First range-read helper: SIA discovery (with the unquoted-JSON CSV quirk), visit clustering, row-wise FLAGS decode, wavelength lookup, proper-motion propagation |
| `acc.py`, `fast_reader.py` | Request-minimal reader: 6 range requests per exposure, bit-identical to astropy's remote reader |
| `wise0855_stack.py`, `wise0855_common.py` | WISE 0855: 4-5 um per-visit stacks, one- and two-source fits, motion vs prediction |
| `barnard_stack.py`, `barnard_common.py` | Barnard's Star: per-visit stacks, difference image, centroids, saturation handling |
| `variability_phot.py`, `variability_analysis.py`, `variability_common.py` | RW Aur and R Dra: aperture photometry, comparison stars, 2MASS/WISE cross-check |
| `mover_finder.py`, `found_3I_atlas.json` | Ephemeris-to-exposure finder; the 350 detector-images covering comet 3I/ATLAS |

They import each other from this folder and expect numpy, scipy, astropy, requests and matplotlib.
Several were cut short when the session switched to planning, so treat them as starting points.
