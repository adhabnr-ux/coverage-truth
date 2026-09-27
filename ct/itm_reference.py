"""NTIA ITM (Longley-Rice, point-to-point) loss for the Sionna cross-check's shadowed receivers.

Gives an independent, standards-body reference next to the Bullington terrain model and Sionna RT.
Needs the compiled NTIA ITM library from the safe-planner repo (ITM_LIB env var or ../safeplan).

    python -m ct.itm_reference
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .common import WORK
from .crosscheck_sionna import TOWER
from .terrain_model import Terrain

ROOT = WORK.parent
sys.path.insert(0, os.environ.get("SAFEPLAN", str(ROOT.parent / "safeplan")))
from sp.itm import p2p_loss  # noqa: E402

R = 6_371_000.0


def gc_dist(la1, lo1, la2, lo2):
    p1, p2, dl = np.radians(la1), np.radians(la2), np.radians(lo2 - lo1)
    return R * np.arccos(np.clip(np.sin(p1) * np.sin(p2) + np.cos(p1) * np.cos(p2) * np.cos(dl), -1, 1))


def main(n_pts=600):
    grid = dict(np.load(WORK / "crosscheck" / "grid.npz"))
    terr = Terrain(dict(lat=grid["lat"], lon=grid["lon"], z=grid["z"]))
    df = pd.read_csv(ROOT / "results" / "diffraction_ablation.csv")
    itm = []
    for la, lo in zip(df.lat, df.lon):
        t = np.linspace(0, 1, n_pts + 1)
        z = terr(TOWER["lat"] + t * (la - TOWER["lat"]), TOWER["lon"] + t * (lo - TOWER["lon"]))
        d = gc_dist(TOWER["lat"], TOWER["lon"], la, lo)
        loss, _ = p2p_loss(TOWER["height_m"], 1.5, np.r_[n_pts, d / n_pts, z], 850.0)
        itm.append(-loss)
    df["itm_db"] = np.round(itm, 2)
    df.to_csv(ROOT / "results" / "diffraction_ablation.csv", index=False)
    s = dict(n=len(df), median_itm_minus_bullington_db=round(float((df.itm_db - df.model_db).median()), 2),
             iqr_itm_minus_bullington_db=[round(float(q), 2) for q in (df.itm_db - df.model_db).quantile([.25, .75])])
    json.dump(s, open(ROOT / "results" / "itm_reference.json", "w"), indent=2)
    print(json.dumps(s, indent=2))


if __name__ == "__main__":
    main()
