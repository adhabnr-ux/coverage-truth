# Methods, assumptions and limits

## 1. Data

| Dataset | Version | Unit | Use |
| --- | --- | --- | --- |
| FCC BDC mobile broadband, Arizona, 4G LTE | Dec 31 2025 availability, released 15 Sep 2026 | H3 res-9 hexagon (~0.1 km²) | all-carrier claimed coverage (1,786,775 hexagons) |
| FCC BDC per-provider 4G LTE (AT&T 1794313, T-Mobile 1794410, Smith Bagley 1794475, Verizon 1794513) | same | hexagon + `minsignal` (claimed min. RSRP, dBm) + `environmnt` | physics check |
| Ookla Open Data, mobile | Q3 2025 – Q2 2026 | z16 tile (~0.26 km² at AZ latitude) | 24,001 AZ tiles, 184,512 tests |
| NCES EDGE public schools 2024-25 + neighborhood poverty (IPR) 2021-22 | | point | 2,633 schools |
| FCC ULS cellular (850 MHz) sites via HIFLD | | point | 443 AZ sites |
| Census cartographic boundaries 2023 | | polygon | state, county, AIANNH areas |
| Copernicus GLO-30 DEM | | 1 arc-second | terrain |

`environmnt`: 0 = outdoor stationary only, 1 = in-vehicle and outdoor ([FCC BDC help](https://help.bdc.fcc.gov/hc/en-us/articles/6047425308187-Formatting-Mobile-Broadband-Availability-Coverage-Maps)).
In the files, each hexagon appears once per carrier with its strongest claimed contour level.

**FCC access.** broadbandmap.fcc.gov refuses non-browser clients. The statewide file was downloaded by
clicking in a normal browser. Per-carrier signal levels for a study area were extracted in the page with
`tools/fcc_inpage_extract.js`: it fetches the provider zip, inflates only the `.dbf`, keeps hexagons whose H3
res-7 parent is in the study list, and emits a run-length-encoded slot string (decoded by `ct/inpage.py`,
unit-tested against the `h3` library).

## 2. Statewide comparison (`ct/statewide.py`)

- A tile is **fully claimed** if every H3 cell centred in it is claimed.
- A tile is **robust** with ≥ 10 tests, ≥ 3 devices and ≥ 2 quarters (4-quarter test-weighted means).
- **Contradiction** = fully claimed, but mean download < 5 Mbps or mean upload < 1 Mbps. Ookla's mobile tiles
  pool all carriers and 4G/5G, so this is conservative: a single carrier could be worse.
- Schools: claim status of the school's own hexagon and of the ~2 km disk (H3 k = 7), tests within 2 km,
  tribal land by point-in-polygon.

## 3. Physics check (`ct/physics_check.py`)

1. **Registered sites**: ULS 850 MHz sites for the carrier's licensee within 40 km (+ half the area's diagonal).
2. **Inferred sites**: DBSCAN (eps 1 km, min 2 cells) on hexagons at or above the carrier's strongest
   level with ≥ 40 cells. Then walk down level by level to −80 dBm (base) or −100 dBm (generous), adding
   a site for each new cluster that contains no known peak. Site = strength-weighted centroid of the
   cluster's top level; height 30 m (sweep 20 / 45 m).
3. **Path loss**: free space + ITU-R P.526 Bullington construction over the DEM profile (≤ 60 m sampling,
   4/3-earth bulge), receiver 1.5 m. Frequencies: 850 MHz (Smith Bagley), 739 MHz (AT&T), 751 MHz (Verizon).
4. **Prediction**: RSRP = 33 dBm − min path loss over all sites. 33 dBm/RE ≈ 40 W over 600 subcarriers
   (18 dBm) + 15 dBi. It ignores antenna patterns, clutter, foliage and cable loss, so it is **optimistic**,
   which makes "implausible" conservative.
5. **Verdict**: judged only for fringe claims (≤ −90 dBm) at least 8 km inside the area (Black Mesa), so that
   un-inferred towers outside the area don't create false flags. Implausible = shortfall > 6 dB.
   Sensitivity to EIRP (−3 … +6 dB) and margin (3 / 6 / 10 dB) is in each `result.json`.

**Why a terrain-profile model and not only Sionna RT?** Sionna RT (v2.1) handles line-of-sight links and reflections
exactly, but uses single-order edge diffraction on a mesh. Over rugged terrain, most receivers are shadowed by
several ridges. Our cross-check (`ct/crosscheck_sionna.py`, `results/summary.json → sionna_crosscheck`)
shows exact agreement on line-of-sight links and no Sionna path for 60% of shadowed receivers.

## 4. Known limits

- Site inference can't see a tower whose claimed contours are all weak, or towers outside the area. The
  generous scenario gives the upper bound, and the difference between the scenarios is reported, not hidden.
- One EIRP per carrier. Real sites differ (small cells, sector patterns, multiple bands).
- Ookla tests are opt-in and cluster along roads and in towns. Tile means hide within-tile variation.
- The FCC environment flag and signal levels are the carriers' own modelling choices (e.g., AT&T claims coverage
  down to −120 dBm RSRP).
- Two study areas, not the whole state. The pipeline is area-generic (`ct/run_physics.py → AREAS`).
