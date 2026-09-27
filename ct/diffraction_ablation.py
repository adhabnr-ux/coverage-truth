"""Does any Sionna RT setting recover paths to terrain-shadowed receivers?

Re-runs the 30 obstructed (NLOS) receivers from the Whiteriver cross-check under every relevant
PathSolver setting (max_depth, edge diffraction, lit-region diffraction, sample count, seed) and records
whether Sionna finds any path and the resulting path gain, next to the multi-edge terrain model.

    python -m ct.diffraction_ablation                # results/diffraction_ablation.{csv,json}  (~1 min)
    python -m ct.diffraction_ablation convergence    # results/diffraction_convergence.json      (~6 min, 2 CPU cores)
    python -m ct.itm_reference                       # adds NTIA ITM column to the ablation CSV
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from .common import WORK
from .crosscheck_sionna import TOWER
from .pathsim import path_gain

ROOT = WORK.parent
CONFIGS = [
    dict(name="d1_diff", max_depth=1, diffraction=True),
    dict(name="d2_diff", max_depth=2, diffraction=True),
    dict(name="d3_diff", max_depth=3, diffraction=True),
    dict(name="d3_diff_edge", max_depth=3, diffraction=True, edge_diffraction=True),
    dict(name="d3_diff_nolit", max_depth=3, diffraction=True, diffraction_lit_region=False),
    dict(name="d1_diff_1e7", max_depth=1, diffraction=True, samples=10_000_000),
    dict(name="d1_diff_seed7", max_depth=1, diffraction=True, seed=7),
    dict(name="d3_nodiff", max_depth=3, diffraction=False),
]


def main():
    cc = pd.read_csv(ROOT / "results" / "crosscheck.csv")
    n = cc[~cc.los].reset_index(drop=True)
    rows, timing = n[["lat", "lon", "d_m", "model_db"]].copy(), {}
    for c in CONFIGS:
        kw = {k: v for k, v in c.items() if k != "name"}
        kw.setdefault("samples", 1_000_000)
        pg, t = path_gain(WORK / "crosscheck", [TOWER], n.lat.values, n.lon.values, 1.5, 850e6, **kw)
        rows[c["name"]] = pg[0]
        timing[c["name"]] = round(t, 1)
        found = pg[0] > -299
        print(f"{c['name']:>15}: paths found {found.sum()}/{len(n)}  ({t:.0f}s)", flush=True)
    rows.to_csv(ROOT / "results" / "diffraction_ablation.csv", index=False)
    summ = {}
    for c in CONFIGS:
        v = rows[c["name"]]
        f = v > -299
        summ[c["name"]] = dict(found=int(f.sum()), of=len(v), seconds=timing[c["name"]],
                               median_model_minus_sionna_db=round(float((rows.model_db - v)[f].median()), 2) if f.any() else None)
    json.dump(summ, open(ROOT / "results" / "diffraction_ablation.json", "w"), indent=2)
    print(json.dumps(summ, indent=2))


def convergence(samples=(3_000_000, 30_000_000, 100_000_000)):
    """Paths found and path gain vs. number of launched rays (max_depth=1, diffraction on)."""
    n = pd.read_csv(ROOT / "results" / "crosscheck.csv").query("~los").reset_index(drop=True)
    out = {}
    for s in samples:
        pg, t = path_gain(WORK / "crosscheck", [TOWER], n.lat.values, n.lon.values, 1.5, 850e6,
                          max_depth=1, diffraction=True, samples=s, batch=10)
        f = pg[0] > -299
        out[s] = dict(found=int(f.sum()), sec=round(t), median_gain=float(np.median(pg[0][f])),
                      median_gap=float(np.median((n.model_db - pg[0])[f])), gains=pg[0].round(1).tolist())
        print(s, out[s]["found"], out[s]["sec"], flush=True)
    json.dump(out, open(ROOT / "results" / "diffraction_convergence.json", "w"), indent=1)


if __name__ == "__main__":
    import sys
    convergence() if sys.argv[1:] == ["convergence"] else main()
