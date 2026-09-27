"""Figure for the Sionna RT terrain-diffraction finding (results/diffraction_*.json/csv -> figures/)."""

from __future__ import annotations

import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .common import WORK  # noqa: E402

ROOT = WORK.parent


def main():
    d = pd.read_csv(ROOT / "results" / "diffraction_ablation.csv")
    c = json.load(open(ROOT / "results" / "diffraction_convergence.json"))
    pts = {1_000_000: int((d.d1_diff > -299).sum()), 10_000_000: int((d.d1_diff_1e7 > -299).sum())}
    pts.update({int(k): v["found"] for k, v in c.items()})
    samples, found = zip(*sorted(pts.items()))
    g = np.array(c[str(max(int(k) for k in c))]["gains"])
    fig, ax = plt.subplots(1, 2, figsize=(11, 5.2), gridspec_kw=dict(width_ratios=[1, 1.35]))
    ax[0].semilogx(samples, found, "o-", color="#0f6a86")
    ax[0].set(xlabel="rays launched per transmitter (samples_per_src)", ylabel="receivers with any path (of 30)",
              ylim=(0, 31), title="Paths found depends on ray count")
    ax[0].grid(alpha=.3)
    f = g > -299
    ax[1].scatter(d.d_m[f] / 1e3, d.model_db[f], s=18, color="#2f7d57", label="Bullington knife-edge (ITU-R P.526)")
    ax[1].scatter(d.d_m / 1e3, d.itm_db, s=18, color="#b7791f", label="NTIA ITM / Longley-Rice (point-to-point)")
    ax[1].scatter(d.d_m[f] / 1e3, g[f], s=18, color="#b8403a", label="Sionna RT 2.1, 1st-order diffraction, 1e8 rays")
    ax[1].scatter(d.d_m[~f] / 1e3, np.full((~f).sum(), -232), s=26, marker="v", color="#b8403a",
                  facecolors="none", label="Sionna RT: no path found")
    ax[1].set(xlabel="distance from tower (km)", ylabel="path gain (dB)", ylim=(-240, -95),
              title="30 terrain-shadowed receivers, 850 MHz, Whiteriver AZ")
    ax[1].grid(alpha=.3)
    ax[1].legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2, frameon=False)
    fig.tight_layout()
    fig.savefig(ROOT / "figures" / "sionna_terrain_diffraction.png", dpi=150)
    print("figures/sionna_terrain_diffraction.png")


if __name__ == "__main__":
    main()
