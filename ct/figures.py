"""Figures for the Coverage Truth write-up.

    python -m ct.figures
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LightSource  # noqa: E402

from .common import DATA, ROOT, WORK  # noqa: E402
from .terrain_scene import load_dem  # noqa: E402

FIG = ROOT / "figures"
FIG.mkdir(exist_ok=True)


def hillshade(ax, bbox, step=6):
    lat, lon, z = load_dem(DATA, *bbox, step=step)
    hs = LightSource(azdeg=315, altdeg=35).hillshade(z, vert_exag=2, dx=30 * step, dy=30 * step)
    ax.imshow(hs, cmap="gray", extent=(lon.min(), lon.max(), lat.min(), lat.max()), alpha=0.45,
              origin="upper", zorder=0)


def area_panels(area: str, bbox, carriers: list[str], title: str):
    schools = pd.read_csv(WORK / "schools_vs_claims.csv")
    s, w, n, e = bbox
    sch = schools[schools.LAT.between(s, n) & schools.LON.between(w, e)]
    tiles = pd.read_parquet(WORK / "tiles_vs_claims.parquet")
    tiles = tiles[tiles.lat.between(s, n) & tiles.lon.between(w, e)]
    one = len(carriers) == 1
    fig, axes = plt.subplots(1, len(carriers), figsize=(8.5, 9) if one else (6.2 * len(carriers), 6.4), squeeze=False)
    for ax, slug in zip(axes[0], carriers):
        d = WORK / area / f"physics_{slug}"
        c = pd.read_parquet(d / "claims_vs_physics.parquet")
        sites = pd.read_csv(d / "sites.csv")
        r = json.loads((d / "result.json").read_text())
        hillshade(ax, bbox)
        ok = c[~c.implausible]
        sc = ax.scatter(ok.lon, ok.lat, c=ok.claimed_min_rsrp, cmap="viridis", vmin=-120, vmax=-50, s=2.2,
                        marker="h", linewidths=0, alpha=0.7, zorder=1)
        gen = pd.read_parquet(d / "generous" / "claims_vs_physics.parquet")[["h3", "env", "implausible"]]
        c = c.merge(gen.rename(columns={"implausible": "imp_gen"}), on=["h3", "env"], how="left")
        rg = json.loads((d / "generous" / "result.json").read_text())
        bad = c[c.implausible & ~c.imp_gen.fillna(False)]
        ax.scatter(bad.lon, bad.lat, color="#ff9896", s=3.5, marker="h", linewidths=0, zorder=2,
                   label=f"implausible unless an unseen weak-peak site exists ({len(bad)})")
        rob = c[c.imp_gen.fillna(False)]
        ax.scatter(rob.lon, rob.lat, color="#b2182b", s=5, marker="h", linewidths=0, zorder=2,
                   label=f"implausible under generous site assumptions ({len(rob)})")
        ax.scatter(tiles.lon, tiles.lat, s=10 + 3 * np.sqrt(tiles.tests), facecolors="none", edgecolors="#ff7f0e",
                   linewidths=0.8, zorder=3, label=f"Ookla tiles w/ tests ({len(tiles)})")
        k = sites[sites.source == "ULS"]
        ax.scatter(k.lon, k.lat, marker="^", s=70, color="black", edgecolors="white", zorder=4,
                   label="registered site (ULS 850 MHz)")
        i = pd.read_csv(d / "generous" / "sites.csv")
        i = i[(i.source == "inferred") & (i.peak_dbm < -80)]
        ax.scatter(i.lon, i.lat, marker="^", s=40, color="#bbbbbb", edgecolors="black", zorder=4,
                   label="possible weak-peak site (generous only)")
        i = sites[sites.source == "inferred"]
        ax.scatter(i.lon, i.lat, marker="^", s=70, color="white", edgecolors="black", zorder=4,
                   label="site inferred from claims")
        ax.scatter(sch.LON, sch.LAT, marker="*", s=140, color="#e377c2", edgecolors="black", zorder=5,
                   label="public school")
        ax.set_xlim(w, e); ax.set_ylim(s, n)
        ax.set_aspect(1 / np.cos(np.radians((s + n) / 2)))
        ax.set_title(f"{r['carrier']}: {r['evaluated']:,} fringe cells judged\n"
                     f"consistent: {r['pct_consistent']}% (base sites) / {rg['pct_consistent']}% (generous)",
                     fontsize=10)
        ax.tick_params(labelsize=7)
        ax.ticklabel_format(useOffset=False, style="plain")
    handles, labels = axes[0][0].get_legend_handles_labels()
    labels = [l.split(" (")[0] if "implausible" in l else l for l in labels]
    fig.legend(handles, labels, loc="lower center", ncol=2 if one else 4, fontsize=8, frameon=False,
               markerscale=1.5, bbox_to_anchor=(0.45, -0.06 if one else -0.02))
    cb = fig.colorbar(sc, ax=axes[0].tolist(), shrink=0.7, pad=0.01)
    cb.set_label("carrier's claimed min. RSRP (dBm)")
    fig.suptitle(title, fontsize=12, y=0.99 if one else 0.93)
    out = FIG / f"{area}_physics.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def verification_gap():
    s = pd.read_csv(WORK / "schools_vs_claims.csv")
    cells = pd.read_parquet(WORK / "fcc_cells_ctx.parquet")
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.2))
    g = s.groupby("on_tribal_land").apply(lambda x: pd.Series(dict(
        zero=100 * (x.tests2km.fillna(0) == 0).mean(), n=len(x))), include_groups=False)
    ax[0].bar(["Not on tribal land", "On tribal land"], g.zero, color=["#4c72b0", "#dd8452"])
    for i, (v, n) in enumerate(zip(g.zero, g.n)):
        ax[0].text(i, v + 0.4, f"{v:.1f}%\n(n={int(n)} schools)", ha="center", fontsize=9)
    ax[0].set_ylabel("% of schools with zero tests within 2 km")
    ax[0].set_ylim(0, g.zero.max() * 1.25)
    ax[0].set_title("Where the FCC map says there is 4G, can anyone check?")
    k = cells.groupby("county").tested.mean().mul(100).sort_values()
    ax[1].barh(k.index, k.values, color="#55a868")
    ax[1].set_xlabel("% of FCC-claimed 4G area (H3 cells) with any Ookla test")
    ax[1].set_title("Verification coverage by county")
    fig.tight_layout()
    out = FIG / "verification_gap.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def statewide_map():
    t = pd.read_parquet(WORK / "tiles_vs_claims.parquet")
    s = pd.read_csv(WORK / "schools_vs_claims.csv")
    import geopandas as gpd
    st = gpd.read_file(f"zip://{DATA / 'cb_state.zip'}")
    az = st[st.STUSPS == "AZ"].to_crs(4326)
    aian = gpd.read_file(f"zip://{DATA / 'cb_aiannh.zip'}").to_crs(4326)
    aian = gpd.clip(aian, az)
    fig, ax = plt.subplots(figsize=(8, 9))
    az.boundary.plot(ax=ax, color="black", linewidth=0.8)
    aian.plot(ax=ax, color="#f2c6a0", alpha=0.6, edgecolor="#c77c48", linewidth=0.4)
    ax.scatter(t.lon, t.lat, s=0.6, color="#4c72b0", alpha=0.5, label=f"Ookla tiles with tests ({len(t):,})")
    z = s[s.tests2km.fillna(0) == 0]
    ax.scatter(z.LON, z.LAT, marker="*", s=90, color="#d62728", edgecolors="black", linewidths=0.4,
               label=f"schools with zero tests within 2 km ({len(z)})", zorder=5)
    c = t[t.contradiction & t.robust]
    ax.scatter(c.lon, c.lat, marker="X", s=50, color="#9467bd", edgecolors="black", linewidths=0.4,
               label=f"robust tiles below the FCC 5/1 standard ({len(c)})", zorder=6)
    ax.set_title("Arizona: FCC 4G LTE claims vs. crowdsourced reality\n(tan = tribal lands)")
    ax.legend(loc="lower left", fontsize=8)
    ax.set_aspect(1 / np.cos(np.radians(34)))
    out = FIG / "statewide_map.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


if __name__ == "__main__":
    print(statewide_map())
    print(verification_gap())
    print(area_panels("whiteriver", (33.70, -110.10, 33.97, -109.94), ["smith"],
                      "Whiteriver (Fort Apache): Smith Bagley 4G claims vs. terrain physics"))
    print(area_panels("blackmesa", (36.05, -110.45, 36.55, -109.80), ["att", "verizon", "smith"],
                      "Black Mesa / Piñon (Navajo Nation): carrier 4G claims vs. terrain physics"))
