# Data sources

Every pixel Tombaugh shows comes from a public NASA archive. Nothing is simulated: the repository rule is
"real data only", and the only invented numbers are small arrays in unit tests of pure maths, named
`synthetic_*` and never shipped.

This page says what the project reads, from where, and how each source is credited. "Used" means code in
this repository has read it; "planned" means the contract or the plan names it and no code reads it yet.
State as of Saturday 14 November 2026, on the `dev` branch.

## SPHEREx (the survey Tombaugh is built on)

| Dataset | DOI | Archive |
|---|---|---|
| SPHEREx DR1 Spectral Images | [10.26131/IRSA678](https://doi.org/10.26131/IRSA678) | NASA/IPAC Infrared Science Archive (IRSA) |
| SPHEREx QR3 Spectral Images | [10.26131/IRSA662](https://doi.org/10.26131/IRSA662) | NASA/IPAC Infrared Science Archive (IRSA) |

- Used. Exposures are found with IRSA's Simple Image Access service (`https://irsa.ipac.caltech.edu/SIA`),
  in the collections `spherex_dr1`, `spherex_dr1_deep`, `spherex_qr3` and `spherex_qr3_deep`.
- Pixels are read with HTTP range requests from the public bucket `nasa-irsa-spherex` (AWS `us-east-1`,
  anonymous access): `https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/`.
- Archive pages: <https://irsa.ipac.caltech.edu/> and <https://irsa.ipac.caltech.edu/Missions/spherex.html>.

Acknowledgements, quoted as given:

> This publication makes use of data products from the Spectro-Photometer for the History of the Universe, Epoch of Reionization and Ices Explorer (SPHEREx), which is a joint project of the Jet Propulsion Laboratory and the California Institute of Technology, and is funded by the National Aeronautics and Space Administration.

> This research has made use of the NASA/IPAC Infrared Science Archive, which is funded by the National Aeronautics and Space Administration and operated by the California Institute of Technology.

## Other sources

The credit lines below are plain descriptions written by the team. They are not the providers' official
acknowledgement texts: those are still to be looked up (see the last section).

| Source | What Tombaugh does with it | State | Credit | Link |
|---|---|---|---|---|
| Gaia DR3 | Star positions, proper motions and parallaxes: reference stars for the fixtures, catalogue overlay, positions carried to the observation date | Used: the frames engine reads it through the Gaia services at ARI Heidelberg and the GAVO Data Center (reference stars of the recorded fields, catalogue markers, the target of a spectrum); the team backend reads it from the ESA Gaia Archive (`/stars`) | Gaia Data Release 3, from the Gaia mission of the European Space Agency (ESA) | <https://www.cosmos.esa.int/gaia> |
| CatWISE2020 | Catalogue overlay and positions of cold, faint sources | Used: the frames engine reads it through IRSA's Gator catalogue interface (catalogue markers, neighbours fitted in a spectrum) | The CatWISE2020 catalogue, built from WISE and NEOWISE survey data and served by IRSA | <https://catwise.github.io/> |
| AllWISE | Atlas images for the "Then & Now" comparison; catalogue magnitudes as a cross-check | Used: the frames engine puts the W1 and W2 Atlas images on a field's grid (found through IRSA SIA v2, cut out by IRSA). Source Catalog used in a morning prototype (IRSA TAP) | Images and catalogue of the AllWISE programme, from NASA's Wide-field Infrared Survey Explorer (WISE), served by IRSA | <https://irsa.ipac.caltech.edu/Missions/wise.html>; Atlas images: AllWISE Atlas (L3a) Coadd Images, [10.26131/IRSA153](https://doi.org/10.26131/IRSA153) |
| 2MASS | Atlas images for the "Then & Now" comparison; catalogue magnitudes as a cross-check | Used: the frames engine puts the J, H and Ks Atlas images on a field's grid (found through IRSA SIA v2, cut out by IRSA). Point Source Catalog used in a morning prototype (IRSA TAP) | Images and catalogue of the Two Micron All Sky Survey (2MASS), served by IRSA | <https://irsa.ipac.caltech.edu/Missions/2mass.html>; Atlas images: 2MASS All-Sky Atlas Image Service, [10.26131/IRSA121](https://doi.org/10.26131/IRSA121) |
| SIMBAD | Names, coordinates and proper motions of known objects | Used in the first morning's measurements (mirror at CfA); the frames engine holds the published astrometry of the test targets read there. Names are looked up by the team backend through Sesame | The SIMBAD database of the Centre de Données astronomiques de Strasbourg (CDS), reached through its mirror at the Center for Astrophysics, Harvard & Smithsonian (CfA) | <https://simbad.harvard.edu/simbad/> |
| Sesame | Turns an object name into a position | Used by the team backend (`/resolve`, through astropy's name resolver). The mirrors at CfA and at IDIA are the fallback named in the plan; no code reads them yet | The Sesame name resolver of CDS, reached through mirrors at CfA and at the Inter-University Institute for Data Intensive Astronomy (IDIA) | <https://vizier.cfa.harvard.edu/> and <https://vizier.idia.ac.za/> |
| IMCCE SkyBoT | Known solar-system objects near a position at a given time | Planned | The Sky Body Tracker (SkyBoT) service of IMCCE, Observatoire de Paris | <https://ssp.imcce.fr/webservices/skybot/> |
| JPL Horizons | Ephemerides of comet 3I/ATLAS, to find the exposures that contain it | Used in a morning prototype only (`science/prototypes/mover_finder.py`). Not read by the API | The Horizons system of NASA's Jet Propulsion Laboratory | <https://ssd.jpl.nasa.gov/horizons/> |
| SPHEREx Explanatory Supplement | The flag bits and masks used in the code | Used (documentation) | The SPHEREx Explanatory Supplement, published at IRSA | <https://irsa.ipac.caltech.edu/data/SPHEREx/docs/SPHEREx_Expsupp.pdf> |
| IRSA SPHEREx tutorials | Reference for reading SPHEREx images from the archive | Used (documentation) | The IRSA tutorial notebooks, by Caltech/IPAC | <https://caltech-ipac.github.io/irsa-tutorials/> |
| WiseView | The interaction model: blink registered images of one field taken at different times. No data comes from it | Used as a model | WiseView, a browser tool for blinking WISE images, used by the Backyard Worlds: Planet 9 project | <http://byw.tools/wiseview> |

CDS in Strasbourg was unreachable on 14 November 2026, which is why SIMBAD and Sesame are reached
through mirrors. The hosts the API may contact are a fixed allow-list in `api/tombaugh/http.py`.

## To verify before submission

Official acknowledgement or citation texts still to be looked up at the provider, and copied word for word:

- [ ] SPHEREx and IRSA: confirm the two sentences above against the current IRSA pages for DR1 and QR3.
- [ ] Gaia (ESA, DPAC): the standard acknowledgement for Gaia data.
- [ ] WISE, AllWISE and NEOWISE: the acknowledgement for WISE data products.
- [ ] CatWISE2020: the requested citation and acknowledgement.
- [ ] 2MASS: the acknowledgement for 2MASS data products.
- [ ] IRSA dataset DOIs for the AllWISE, 2MASS and CatWISE products actually used. Found on 14 November 2026
  for the Atlas images that the Then & Now planes read: 10.26131/IRSA153, "AllWISE Atlas (L3a) Coadd Images"
  (asked for on <https://irsa.ipac.caltech.edu/docs/program_interface/sia_allwise_atlas.html>), and
  10.26131/IRSA121, "2MASS All-Sky Atlas Image Service" (asked for on
  <https://irsa.ipac.caltech.edu/docs/program_interface/sia_2mass_allsky.html>); both names as their landing
  pages at doi.org give them. Still open: CatWISE2020, and the AllWISE and 2MASS catalogues if they stay.
- [ ] SIMBAD and Sesame (CDS): the acknowledgement for each service, and whether the mirrors ask for one.
- [ ] ARI Heidelberg and GAVO: whether their Gaia services ask for an acknowledgement.
- [ ] IMCCE SkyBoT: the requested citation.
- [ ] JPL Horizons: the requested citation.
- [ ] SPHEREx Explanatory Supplement: version and date of the copy the flag masks were taken from.
- [ ] WiseView: the citation its authors ask for.
- [ ] Remove from this page any source that the submitted version does not use.
