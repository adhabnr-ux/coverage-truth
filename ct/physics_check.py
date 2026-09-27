"""Physics consistency check of one carrier's FCC coverage claims in one area.

Pipeline
  1. Sites: registered sites (FCC ULS cellular, if the carrier has any) + sites *inferred from the claims
     themselves*: carriers' strongest claimed contours (-50..-80 dBm) hug their towers, so DBSCAN on the
     strongest cells recovers tower locations the public never sees (AWS/PCS/700 MHz sites are not in ULS).
  2. Terrain path loss from every site to every claimed cell: free space + Bullington knife-edge
     diffraction over a 30 m DEM profile (ct/terrain_model.py; cross-checked against Sionna RT LOS).
  3. Predicted RSRP = EIRP per resource element - min path loss. Optimistic by design (isotropic in
     azimuth at full antenna gain, no clutter/foliage/building loss, no cable loss).
  4. A claim is *implausible* when even this optimistic prediction is > margin dB short of the carrier's
     own claimed level. Only weak "fringe" thresholds are judged (<= FRINGE_DBM): near towers the claimed
     levels are strong and a few hundred metres of site-location error dominates, so those cells are
     reported but not judged.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

from .common import DATA
from .terrain_model import Terrain, path_loss_db
from .terrain_scene import load_dem

R_KM = 6371.0088


@dataclass
class Config:
    name: str
    bbox: tuple[float, float, float, float]          # south, west, north, east of the claims analysed
    eval_margin_km: float = 8.0                      # judge only cells this far inside the bbox
    dem_margin_deg: float = 0.25
    freq_hz: float = 850e6
    eirp_re_dbm: float = 33.0                        # 40 W / 10 MHz LTE (18 dBm/RE) + 15 dBi
    tx_height_m: float = 30.0                        # inferred sites
    rx_height_m: float = 1.5
    margin_db: float = 6.0
    fringe_dbm: float = -90.0
    strong_min_cells: int = 40
    peak_floor_dbm: float = -80.0
    dbscan_eps_km: float = 1.0
    dbscan_min_samples: int = 2
    uls_licensees: list[str] = field(default_factory=list)
    uls_radius_km: float = 40.0


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * R_KM * np.arcsin(np.sqrt(a))


def strong_threshold(claims: pd.DataFrame, min_cells: int) -> int:
    levels = sorted(claims.claimed_min_rsrp.unique(), reverse=True)
    for lv in levels:
        if (claims.claimed_min_rsrp >= lv).sum() >= min_cells:
            return int(lv)
    return int(levels[-1])


def infer_sites(claims: pd.DataFrame, cfg: Config) -> tuple[pd.DataFrame, int]:
    """Multi-level peak finding. Start with the strongest contour levels (>= strong threshold); then walk
    down level by level to `peak_floor_dbm`, adding a site for every cluster whose peak is at that level
    and which contains no site found so far (towers whose strongest contour is weaker than the
    carrier's best towers would otherwise be missed, and their coverage wrongly judged implausible)."""
    thr = strong_threshold(claims, cfg.strong_min_cells)
    levels = [lv for lv in sorted(claims.claimed_min_rsrp.unique(), reverse=True)
              if cfg.peak_floor_dbm <= lv <= thr] or [thr]
    rows = []
    for lv in levels:
        s = claims[claims.claimed_min_rsrp >= lv]
        X = np.radians(s[["lat", "lon"]].to_numpy())
        lab = DBSCAN(eps=cfg.dbscan_eps_km / R_KM, min_samples=cfg.dbscan_min_samples,
                     metric="haversine").fit_predict(X)
        for k in sorted(set(lab) - {-1}):
            g = s[lab == k]
            if rows:
                have = pd.DataFrame(rows)
                dmin = np.array([haversine_km(r.lat, r.lon, g.lat.values, g.lon.values).min()
                                 for r in have.itertuples()])
                if (dmin <= cfg.dbscan_eps_km).any():
                    continue                             # cluster already explained by a known peak
            top = g[g.claimed_min_rsrp == g.claimed_min_rsrp.max()]
            w = 10 ** (top.claimed_min_rsrp / 10)
            rows.append(dict(name=f"inferred_{len(rows)}", lat=np.average(top.lat, weights=w),
                             lon=np.average(top.lon, weights=w), height_m=cfg.tx_height_m,
                             source="inferred", peak_dbm=int(top.claimed_min_rsrp.max()), n_cells=len(top)))
    return pd.DataFrame(rows), thr


def registered_sites(cfg: Config) -> pd.DataFrame:
    if not cfg.uls_licensees:
        return pd.DataFrame(columns=["name", "lat", "lon", "height_m", "source"])
    u = pd.read_csv(DATA / "az_uls_cellular_towers.csv")
    u = u[u.Licensee.isin(cfg.uls_licensees)].drop_duplicates(["latdec", "londec"])
    s, w, n, e = cfg.bbox
    d = haversine_km((s + n) / 2, (w + e) / 2, u.latdec, u.londec)
    u = u[d <= cfg.uls_radius_km + haversine_km(s, w, n, e) / 2]
    return pd.DataFrame(dict(name=[f"ULS_{c}_{i}" for i, c in enumerate(u.Callsign)], lat=u.latdec.values,
                             lon=u.londec.values, height_m=u.SupStruc.clip(10, 100).values, source="ULS"))


def run(claims: pd.DataFrame, cfg: Config, out_dir: Path, sensitivity: bool = True) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    inferred, thr = infer_sites(claims, cfg)
    known = registered_sites(cfg)
    sites = pd.concat([known, inferred], ignore_index=True)
    s, w, n, e = cfg.bbox
    m = cfg.dem_margin_deg
    lat_all = np.r_[claims.lat, sites.lat]
    lon_all = np.r_[claims.lon, sites.lon]
    dem_bbox = (min(s, lat_all.min()) - m, min(w, lon_all.min()) - m,
                max(n, lat_all.max()) + m, max(e, lon_all.max()) + m)
    lat, lon, z = load_dem(DATA, *dem_bbox, step=1)
    terr = Terrain(dict(lat=lat, lon=lon, z=z))

    pl = np.full((len(sites), len(claims)), np.inf)
    for i, st in sites.iterrows():
        dmax = haversine_km(st.lat, st.lon, claims.lat.values, claims.lon.values).max()
        npts = int(np.clip(dmax * 1000 / 60, 200, 1200))   # <= ~60 m profile spacing
        for b in range(0, len(claims), 3000):
            sl = slice(b, b + 3000)
            pl[i, sl], _, _ = path_loss_db(terr, st.lat, st.lon, st.height_m, claims.lat.values[sl],
                                           claims.lon.values[sl], cfg.rx_height_m, cfg.freq_hz, n=npts)
    best = pl.argmin(0)
    c = claims.copy()
    c["pl_db"] = pl.min(0)
    c["best_site"] = sites.name.values[best]
    c["site_km"] = haversine_km(c.lat.values, c.lon.values, sites.lat.values[best], sites.lon.values[best])
    c["pred_rsrp"] = cfg.eirp_re_dbm - c.pl_db
    c["shortfall_db"] = c.claimed_min_rsrp - c.pred_rsrp
    k = cfg.eval_margin_km / 111.0
    c["evaluated"] = (c.lat.between(s + k, n - k) & c.lon.between(w + k / np.cos(np.radians(s)), e - k / np.cos(np.radians(s)))
                      & (c.claimed_min_rsrp <= cfg.fringe_dbm))
    c["implausible"] = c.evaluated & (c.shortfall_db > cfg.margin_db)

    # validation: distance from each registered site to the nearest inferred site
    val = []
    for _, r in known.iterrows():
        if len(inferred):
            d = haversine_km(r.lat, r.lon, inferred.lat.values, inferred.lon.values)
            val.append(dict(site=r["name"], nearest_inferred_km=round(float(d.min()), 2)))

    ev = c[c.evaluated]
    res = dict(area=cfg.name, carrier=str(c.carrier.iloc[0]) if "carrier" in c else "",
               cells=int(len(c)), strong_threshold_dbm=thr, sites_registered=int(len(known)),
               sites_inferred=int(len(inferred)), evaluated=int(len(ev)),
               implausible=int(c.implausible.sum()),
               pct_consistent=round(100 * (1 - c.implausible.sum() / max(len(ev), 1)), 1),
               implausible_median_site_km=round(float(c[c.implausible].site_km.median()), 1) if c.implausible.any() else None,
               registered_vs_inferred=val, config=asdict(cfg))
    if sensitivity:   # EIRP shifts are exact (prediction is linear in EIRP); margins likewise
        res["sensitivity"] = [dict(eirp_re_dbm=cfg.eirp_re_dbm + de, margin_db=mg,
                                   implausible=int((ev.shortfall_db - de > mg).sum()))
                              for de in (-3, 0, 3, 6) for mg in (3, 6, 10)]
    c.to_parquet(out_dir / "claims_vs_physics.parquet")
    sites.to_csv(out_dir / "sites.csv", index=False)
    (out_dir / "result.json").write_text(json.dumps(res, indent=2, default=str))
    return res
