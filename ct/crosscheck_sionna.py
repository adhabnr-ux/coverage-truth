"""Cross-check the terrain path-loss model against NVIDIA Sionna RT on the same DEM.

For receivers the terrain model says are line-of-sight, Sionna's LOS-only path gain must match free
space (checks geometry/registration end-to-end), and LOS + ground-reflection shows the two-ray spread the
simple model ignores. For obstructed receivers, Sionna RT (single-order edge diffraction on a triangle
mesh) is expected to under-predict versus the multi-edge terrain method -- the reason the check uses a
terrain-profile model at scale.

    python -m ct.crosscheck_sionna
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .common import DATA, WORK
from .pathsim import path_gain
from .terrain_model import Terrain, path_loss_db
from .terrain_scene import build, load_dem

BBOX = (33.70, -110.05, 33.84, -109.90)
TOWER = dict(name="ULS_SBI_Whiteriver", lat=33.760333, lon=-109.974833, height_m=45.7)


def main(n=60, seed=0):
    out = WORK / "crosscheck"
    info = build(out, DATA, BBOX, lat0=(BBOX[0] + BBOX[2]) / 2, lon0=(BBOX[1] + BBOX[3]) / 2,
                 terrain_step=1, ue_step=8)
    grid = dict(np.load(out / "grid.npz"))
    terr = Terrain(dict(lat=grid["lat"], lon=grid["lon"], z=grid["z"]))
    rng = np.random.default_rng(seed)
    lat = rng.uniform(BBOX[0] + 0.01, BBOX[2] - 0.01, 4000)
    lon = rng.uniform(BBOX[1] + 0.01, BBOX[3] - 0.01, 4000)
    loss, los, d = path_loss_db(terr, TOWER["lat"], TOWER["lon"], TOWER["height_m"], lat, lon, 1.5, 850e6, n=600)
    pick = np.r_[np.flatnonzero(los & (d > 800))[: n // 2], np.flatnonzero(~los & (d > 800))[: n // 2]]
    lat, lon, loss, los, d = lat[pick], lon[pick], loss[pick], los[pick], d[pick]
    pg_los, t1 = path_gain(out, [TOWER], lat, lon, 1.5, 850e6, max_depth=0, diffraction=False, samples=100_000)
    pg_all, t2 = path_gain(out, [TOWER], lat, lon, 1.5, 850e6, max_depth=1, diffraction=True, samples=1_000_000)
    df = pd.DataFrame(dict(lat=lat, lon=lon, d_m=d, los=los, model_db=-loss,
                           sionna_los_db=pg_los[0], sionna_los_refl_diff_db=pg_all[0]))
    df.to_csv(WORK / "crosscheck.csv", index=False)
    L = df[df.los]
    N = df[~df.los]
    res = dict(scene=info | {"terrain_shape": list(info["terrain_shape"]), "ue_shape": list(info["ue_shape"])},
               n_los=int(len(L)), n_nlos=int(len(N)),
               los_model_minus_sionna_los_db=dict(median=round(float((L.model_db - L.sionna_los_db).median()), 2),
                                                  max_abs=round(float((L.model_db - L.sionna_los_db).abs().max()), 2)),
               los_model_minus_sionna_full_db=dict(median=round(float((L.model_db - L.sionna_los_refl_diff_db).median()), 2),
                                                   p90_abs=round(float((L.model_db - L.sionna_los_refl_diff_db).abs().quantile(.9)), 2)),
               nlos_sionna_found_paths_pct=round(100 * float((N.sionna_los_refl_diff_db > -299).mean()), 1),
               nlos_model_minus_sionna_db_median=round(float((N.model_db - N.sionna_los_refl_diff_db)[N.sionna_los_refl_diff_db > -299].median()), 2)
               if (N.sionna_los_refl_diff_db > -299).any() else None,
               runtime_s=round(t1 + t2, 1))
    (WORK / "crosscheck.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
