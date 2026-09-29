"""Build the public school lookup page, docs/index.html (served by GitHub Pages).

    python -m ct.site

Inputs: work/schools_vs_claims.csv (ct.statewide), work/<area>/physics_*/ (ct.run_physics),
Census boundaries in data/. Templates: site/page_head.html, site/page_body.html, site/page_script.js.
"""
from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import mapping

from .common import DATA, ROOT, WORK

AREAS = {"blackmesa": ((36.05, -110.45, 36.55, -109.80), ["att", "verizon", "smith"]),
         "whiteriver": ((33.70, -110.10, 33.97, -109.94), ["smith"])}
CARRIER_NAMES = {"att": "AT&T", "verizon": "Verizon", "smith": "Smith Bagley (Cellular One)"}


def status(r) -> str:
    if not r.claimed_at_school:
        return "none"
    t = 0 if pd.isna(r.tests2km) else r.tests2km
    if t == 0:
        return "unverified"
    if t < 10:
        return "thin"
    return "checked" if r.dl2km >= 5 else "below"


def _km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * np.arcsin(np.sqrt(a))


def physics_near_schools(s: pd.DataFrame, radius_km=2.0) -> dict:
    out = {}
    for area, (bb, carriers) in AREAS.items():
        S, W, N, E = bb
        m = s.LAT.between(S, N) & s.LON.between(W, E)
        for c in carriers:
            d = WORK / area / f"physics_{c}"
            base = pd.read_parquet(d / "claims_vs_physics.parquet")
            gen = pd.read_parquet(d / "generous" / "claims_vs_physics.parquet")[["h3", "env", "implausible"]]
            b = base.merge(gen.rename(columns={"implausible": "imp_gen"}), on=["h3", "env"])
            for _, r in s[m].iterrows():
                near = b[_km(r.LAT, r.LON, b.lat.values, b.lon.values) <= radius_km]
                ev = near[near.evaluated]
                out.setdefault(int(r.NCESSCH), {"area": area, "carriers": []})["carriers"].append(dict(
                    carrier=CARRIER_NAMES[c], claimed_cells=int(len(near)), judged=int(len(ev)),
                    implausible=int(ev.implausible.sum()), implausible_generous=int(ev.imp_gen.sum())))
    return out


def build() -> dict:
    s = pd.read_csv(WORK / "schools_vs_claims.csv")
    s["status"] = s.apply(status, axis=1)
    phys = physics_near_schools(s)
    twin_f = ROOT / "results" / "mesa_twin_schools.json"
    twin = json.loads(twin_f.read_text()) if twin_f.exists() else {}
    rows = []
    for r in s.itertuples():
        rows.append([r.NAME.title() if r.NAME.isupper() else r.NAME, r.CITY.title(), r.NMCNTY.replace(" County", ""),
                     round(r.LAT, 4), round(r.LON, 4), r.status,
                     None if pd.isna(r.tests2km) else int(r.tests2km), None if pd.isna(r.dl2km) else round(r.dl2km, 1),
                     None if pd.isna(r.IPR_EST) else int(r.IPR_EST), r.tribal_area if isinstance(r.tribal_area, str) else None,
                     None if pd.isna(r.claim_env) else int(r.claim_env), round(r.claim_frac_2km, 3), round(r.tower_km, 1),
                     phys.get(int(r.NCESSCH)), twin.get(str(int(r.NCESSCH)))])
    schools = dict(cols=["name", "city", "county", "lat", "lon", "status", "tests", "dl", "ipr", "tribal", "env",
                         "claim2km", "towerkm", "physics", "twin"], rows=rows)
    st = gpd.read_file(f"zip://{DATA / 'cb_state.zip'}")
    az = st[st.STUSPS == "AZ"].to_crs(4326)
    ai = gpd.clip(gpd.read_file(f"zip://{DATA / 'cb_aiannh.zip'}").to_crs(4326), az)
    ai = ai[ai.to_crs(5070).area > 2e7]                  # drop slivers under 20 km^2
    geo = dict(az=mapping(az.geometry.iloc[0].simplify(0.01)),
               tribal=[dict(name=n, geom=mapping(g.simplify(0.01))) for n, g in zip(ai.NAME, ai.geometry)])
    t = ROOT / "site"
    head, body, js = (t / "page_head.html").read_text(), (t / "page_body.html").read_text(), (t / "page_script.js").read_text()
    enc = lambda o: json.dumps(o, separators=(",", ":")).replace("</", "<\\/")
    page = ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
            "<meta name=\"description\" content=\"Does anyone check the FCC 4G map at Arizona schools? FCC claims vs. "
            "12 months of speed tests vs. terrain physics, for every public school.\">\n"
            f"{head}</head>\n<body>\n{body}"
            f"<script type=\"application/json\" id=\"schools-data\">{enc(schools)}</script>\n"
            f"<script type=\"application/json\" id=\"geo-data\">{enc(geo)}</script>\n<script>\n{js}\n</script>\n</body>\n</html>\n")
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "index.html").write_text(page)
    counts = s.groupby("on_tribal_land").status.value_counts().unstack(fill_value=0)
    return dict(schools=len(s), tribal_areas=len(geo["tribal"]), counts=counts.to_dict(orient="index"))


if __name__ == "__main__":
    print(build())
