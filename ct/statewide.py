"""Statewide Arizona: FCC 4G LTE coverage claims (any provider, H3 res-9) vs. Ookla speed tests vs. schools.

Inputs (see README "Data"):
  work/fcc_az_4glte_any.parquet  h3_res9_id, environmnt (0 = outdoor stationary only, 1 = in-vehicle + outdoor)
  work/ookla_az_4q.parquet       Ookla mobile tiles (z16 quadkey), 4 quarters Jul 2025 - Jun 2026 pooled
  work/tile_cells.parquet        quadkey -> H3 res-9 cells whose centres fall in the tile
  work/schools_ookla.csv         NCES public schools + Ookla context (2 km)
  data/cb_aiannh.zip             Census American Indian / Alaska Native / Native Hawaiian areas

Outputs: work/tiles_vs_claims.parquet, work/schools_vs_claims.csv, work/statewide_summary.json
"""

from __future__ import annotations

import json

import geopandas as gpd
import h3
import numpy as np
import pandas as pd

from .common import DATA, WORK

FCC_STANDARD_DL, FCC_STANDARD_UL = 5.0, 1.0      # Mbps, 4G LTE BDC claim
ROBUST = dict(min_tests=10, min_devices=3, min_quarters=2)
SCHOOL_K = 7                                       # res-9 grid ring ~2 km radius
CELL_KM2 = h3.average_hexagon_area(9, unit="km^2")


def load_claims() -> pd.Series:
    c = pd.read_parquet(WORK / "fcc_az_4glte_any.parquet")
    return c.set_index("h3_res9_id")["environmnt"]


def tiles_vs_claims(env: pd.Series) -> pd.DataFrame:
    o = pd.read_parquet(WORK / "ookla_az_4q.parquet")
    tc = pd.read_parquet(WORK / "tile_cells.parquet")
    tc["env"] = tc["h3"].map(env)                      # NaN = no claim
    g = tc.groupby("quadkey").agg(cells=("h3", "size"),
                                  claimed=("env", lambda s: s.notna().sum()),
                                  vehicle=("env", lambda s: (s == 1).sum()))
    t = o.merge(g, left_on="quadkey", right_index=True, how="left")
    t["claim_frac"] = t["claimed"] / t["cells"]
    t["vehicle_frac"] = t["vehicle"] / t["cells"]
    t["robust"] = ((t.tests >= ROBUST["min_tests"]) & (t.devices >= ROBUST["min_devices"])
                   & (t.quarters >= ROBUST["min_quarters"]))
    t["below_std"] = (t.d_mbps < FCC_STANDARD_DL) | (t.u_mbps < FCC_STANDARD_UL)
    t["contradiction"] = (t.claim_frac == 1) & t.below_std
    t["underclaimed"] = (t.claim_frac == 0) & ~t.below_std
    return t


def schools_vs_claims(env: pd.Series) -> pd.DataFrame:
    s = pd.read_csv(WORK / "schools_ookla.csv")
    cells = [h3.latlng_to_cell(a, b, 9) for a, b in zip(s.LAT, s.LON)]
    s["cell"] = cells
    s["claim_env"] = pd.Series(cells).map(env).values
    s["claimed_at_school"] = s["claim_env"].notna()
    fr = []
    for c in cells:
        d = h3.grid_disk(c, SCHOOL_K)
        e = env.reindex(d)
        fr.append((e.notna().mean(), (e == 1).mean()))
    s["claim_frac_2km"], s["vehicle_frac_2km"] = np.array(fr).T
    aian = gpd.read_file(f"zip://{DATA / 'cb_aiannh.zip'}")[["NAME", "geometry"]].to_crs(4326)
    pts = gpd.GeoDataFrame(s[["NCESSCH"]], geometry=gpd.points_from_xy(s.LON, s.LAT), crs=4326)
    j = gpd.sjoin(pts, aian, how="left", predicate="within").drop_duplicates("NCESSCH")
    s["tribal_area"] = j["NAME"].values
    s["on_tribal_land"] = s["tribal_area"].notna()
    s["unverifiable"] = s.claimed_at_school & (s.tests2km.fillna(0) == 0)
    return s


def summary(env: pd.Series, t: pd.DataFrame, s: pd.DataFrame) -> dict:
    az_km2 = 295_234.0
    r = t[t.robust]
    out = {
        "fcc_claimed_cells": int(len(env)),
        "fcc_claimed_km2": round(len(env) * CELL_KM2),
        "fcc_claimed_pct_of_az_area": round(100 * len(env) * CELL_KM2 / az_km2, 1),
        "fcc_vehicle_cells": int((env == 1).sum()),
        "ookla_tiles": int(len(t)), "ookla_tests": int(t.tests.sum()),
        "tiles_fully_claimed": int((t.claim_frac == 1).sum()),
        "tiles_unclaimed": int((t.claim_frac == 0).sum()),
        "robust_tiles": int(len(r)),
        "contradictions_all": int(t.contradiction.sum()),
        "contradictions_robust": int(r.contradiction.sum()),
        "contradiction_rate_robust_pct": round(100 * r.contradiction.sum() / max((r.claim_frac == 1).sum(), 1), 2),
        "underclaimed_robust": int(r.underclaimed.sum()),
        "schools": int(len(s)),
        "schools_unclaimed_at_site": int((~s.claimed_at_school).sum()),
        "schools_outdoor_only_at_site": int((s.claim_env == 0).sum()),
        "schools_unverifiable": int(s.unverifiable.sum()),
        "schools_on_tribal_land": int(s.on_tribal_land.sum()),
    }
    for name, m in {"tribal": s.on_tribal_land, "non_tribal": ~s.on_tribal_land}.items():
        x = s[m]
        out[f"{name}_pct_unclaimed_at_site"] = round(100 * (~x.claimed_at_school).mean(), 1)
        out[f"{name}_pct_zero_tests_2km"] = round(100 * (x.tests2km.fillna(0) == 0).mean(), 1)
        out[f"{name}_median_claim_frac_2km"] = round(float(x.claim_frac_2km.median()), 3)
        out[f"{name}_median_ipr"] = float(x.IPR_EST.median())
    return out


def run() -> dict:
    env = load_claims()
    t = tiles_vs_claims(env)
    s = schools_vs_claims(env)
    t.to_parquet(WORK / "tiles_vs_claims.parquet")
    s.to_csv(WORK / "schools_vs_claims.csv", index=False)
    out = summary(env, t, s)
    (WORK / "statewide_summary.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
