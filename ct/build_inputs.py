"""Download public inputs and build the analysis tables in work/.

    python -m ct.build_inputs            # everything except the FCC files (see README: browser-only)

Sources
  Ookla Open Data, mobile performance tiles (z16), 4 quarters Q3-2025 .. Q2-2026 (CC BY-NC-SA 4.0)
  NCES EDGE public school locations 2024-25 + School Neighborhood Poverty (IPR) estimates
  FCC ULS cellular (850 MHz) antenna structures, via HIFLD "Cellular Towers"
  US Census cartographic boundaries 2023 (states, counties, AIANNH areas)
  Copernicus GLO-30 DEM (fetched on demand by ct.terrain_scene.load_dem)
"""

from __future__ import annotations

import urllib.request

import geopandas as gpd
import h3
import mercantile
import numpy as np
import pandas as pd

from .common import DATA, WORK, tile_cells

OOKLA = "https://ookla-open-data.s3.amazonaws.com/parquet/performance/type=mobile/year={y}/quarter={q}/{d}_performance_mobile_tiles.parquet"
QUARTERS = [("2025-07-01", 2025, 3, "ookla_2025-07-01"), ("2025-10-01", 2025, 4, "ookla_2025-10-01"),
            ("2026-01-01", 2026, 1, "ookla_2026-01-01"), ("2026-04-01", 2026, 2, "ookla_mobile_2026q2")]
CENSUS = {"cb_state.zip": "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_state_500k.zip",
          "cb_county.zip": "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip",
          "cb_aiannh.zip": "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_aiannh_500k.zip"}


def fetch(url, dest):
    if not dest.exists():
        print("downloading", url)
        urllib.request.urlretrieve(url, dest)
    return dest


def arizona():
    st = gpd.read_file(f"zip://{fetch(CENSUS['cb_state.zip'], DATA / 'cb_state.zip')}")
    return st[st.STUSPS == "AZ"].to_crs(4326).geometry.iloc[0]


def build_ookla() -> pd.DataFrame:
    az = arizona()
    w, s, e, n = az.bounds
    parts = []
    for d, y, q, name in QUARTERS:
        f = fetch(OOKLA.format(y=y, q=q, d=d), DATA / f"{name}.parquet")
        t = pd.read_parquet(f, columns=["quadkey", "tile_x", "tile_y", "avg_d_kbps", "avg_u_kbps",
                                        "avg_lat_ms", "tests", "devices"])
        t = t[t.tile_x.between(w, e) & t.tile_y.between(s, n)]
        parts.append(t)
    t = pd.concat(parts)
    pts = gpd.GeoSeries(gpd.points_from_xy(t.tile_x, t.tile_y), crs=4326)
    t = t[pts.within(az).values]
    for c in ("avg_d_kbps", "avg_u_kbps", "avg_lat_ms"):
        t[c + "_w"] = t[c] * t.tests
    g = t.groupby("quadkey").agg(lon=("tile_x", "first"), lat=("tile_y", "first"), tests=("tests", "sum"),
                                 devices=("devices", "sum"), dw=("avg_d_kbps_w", "sum"),
                                 uw=("avg_u_kbps_w", "sum"), lw=("avg_lat_ms_w", "sum"),
                                 quarters=("tests", "size")).reset_index()
    g["d_mbps"] = g.dw / g.tests / 1000
    g["u_mbps"] = g.uw / g.tests / 1000
    g["lat_ms"] = g.lw / g.tests
    g = g[["quadkey", "lon", "lat", "tests", "devices", "d_mbps", "u_mbps", "lat_ms", "quarters"]]
    g.to_parquet(WORK / "ookla_az_4q.parquet")
    rows = [(qk, c) for qk in g.quadkey for c in tile_cells(qk)]
    pd.DataFrame(rows, columns=["quadkey", "h3"]).to_parquet(WORK / "tile_cells.parquet")
    return g


def build_schools(ookla: pd.DataFrame) -> pd.DataFrame:
    s = pd.read_csv(DATA / "az_public_schools.csv")
    u = pd.read_csv(DATA / "az_uls_cellular_towers.csv")
    R = 6371.0088

    def hav(la1, lo1, la2, lo2):
        p1, p2 = np.radians(la1), np.radians(la2)
        a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lo2 - lo1) / 2) ** 2
        return 2 * R * np.arcsin(np.sqrt(a))

    out = []
    for r in s.itertuples():
        d = hav(r.LAT, r.LON, ookla.lat.values, ookla.lon.values)
        m = d <= 2.0
        t = ookla[m]
        tests = t.tests.sum()
        out.append(dict(tiles2km=int(m.sum()), tests2km=float(tests),
                        dl2km=float((t.d_mbps * t.tests).sum() / tests) if tests else np.nan,
                        tower_km=float(hav(r.LAT, r.LON, u.latdec.values, u.londec.values).min())))
    s = pd.concat([s, pd.DataFrame(out)], axis=1)
    s["rural"] = s.LOCALE >= 41
    s.to_csv(WORK / "schools_ookla.csv", index=False)
    return s


if __name__ == "__main__":
    for f, url in CENSUS.items():
        fetch(url, DATA / f)
    o = build_ookla()
    print("ookla tiles", len(o), "tests", int(o.tests.sum()))
    s = build_schools(o)
    print("schools", len(s))


# --- tabular sources (ArcGIS REST) -------------------------------------------------------------------
NCES = "https://nces.ed.gov/opengis/rest/services/K12_School_Locations"
SCHOOLS_URL = NCES + "/EDGE_GEOCODE_PUBLICSCH_2425/MapServer/0/query"
IPR_URL = NCES + "/EDGE_SIDE_1822_PUBLICSCH_2122/MapServer/1/query"
TOWERS_URL = ("https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/"
              "Cellular_Towers_in_the_United_States/FeatureServer/0/query")


def arcgis_table(url, where, fields, page=1000):
    import json
    import urllib.parse
    rows, off = [], 0
    while True:
        q = urllib.parse.urlencode(dict(where=where, outFields=",".join(fields), returnGeometry="false",
                                        resultOffset=off, resultRecordCount=page, orderByFields="OBJECTID",
                                        f="json"))
        with urllib.request.urlopen(f"{url}?{q}", timeout=60) as r:
            js = json.load(r)
        feats = js.get("features", [])
        rows += [f["attributes"] for f in feats]
        if len(feats) < page and not js.get("exceededTransferLimit"):
            break
        off += len(feats)
    return pd.DataFrame(rows)


def fetch_schools(dest=DATA / "az_public_schools.csv"):
    s = arcgis_table(SCHOOLS_URL, "STATE='AZ'", ["NCESSCH", "NAME", "CITY", "NMCNTY", "LOCALE", "LAT", "LON",
                                                 "SCHOOLYEAR"])
    ids = s.NCESSCH.astype(str).tolist()     # includes BIE (59...) and cross-state (49...) schools
    ipr = pd.concat([arcgis_table(IPR_URL, "NCESSCH IN (" + ",".join(f"'{i}'" for i in ids[k:k + 150]) + ")",
                                  ["NCESSCH", "IPR_EST"]) for k in range(0, len(ids), 150)])
    s = s.merge(ipr.drop_duplicates("NCESSCH"), on="NCESSCH", how="left")
    s.to_csv(dest, index=False)
    return s


def fetch_towers(dest=DATA / "az_uls_cellular_towers.csv"):
    t = arcgis_table(TOWERS_URL, "LocState='AZ'", ["Licensee", "Callsign", "LocCity", "LocCounty", "StrucType",
                                                   "AllStruc", "SupStruc", "LicStatus", "latdec", "londec"])
    t.to_csv(dest, index=False)
    return t
