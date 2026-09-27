"""Run the physics consistency check for every (area, carrier) and a tower-height sensitivity sweep.

    python -m ct.run_physics
"""

from __future__ import annotations

import json

import pandas as pd

from .common import ROOT, WORK
from .inpage import decode
from .physics_check import Config, run

EXTRACTS = ROOT / "results" / "extracts"


def whiteriver_claims() -> pd.DataFrame:
    r7 = (EXTRACTS / "whiteriver_res7.txt").read_text().strip().split(",")
    enc = dict(line.split(" ", 1) for line in (EXTRACTS / "whiteriver_smithbagley_rle.txt").read_text().strip().splitlines())
    return decode(r7, {0: enc["E0"], 1: enc["E1"]}).assign(carrier="Smith Bagley Inc")


def blackmesa_claims() -> pd.DataFrame:
    j = json.loads((EXTRACTS / "blackmesa_fcc_extract.json").read_text())
    r7 = ["87" + k + "ffffff" for k in j["res7"]]
    parts = [decode(r7, {0: r["E0"], 1: r["E1"]}).assign(carrier=r["brand"]) for r in j["results"].values()]
    return pd.concat([p for p in parts if len(p)], ignore_index=True)


AREAS = {
    "whiteriver": dict(bbox=(33.70, -110.10, 33.97, -109.94), eval_margin_km=0.0, claims=whiteriver_claims),
    "blackmesa": dict(bbox=(36.05, -110.45, 36.55, -109.80), eval_margin_km=8.0, claims=blackmesa_claims),
}
CARRIER = {  # band assumption (dominant rural LTE layer) and ULS licensee names for registered 850 MHz sites
    "Smith Bagley Inc": dict(freq_hz=850e6, uls_licensees=["SBI License Corporation"]),
    "AT&T": dict(freq_hz=739e6, uls_licensees=["AT&T Mobility Spectrum, LLC"]),
    "Verizon": dict(freq_hz=751e6, uls_licensees=["Cellco Partnership"]),
}


def main():
    results = []
    for area, a in AREAS.items():
        claims = a["claims"]()
        for carrier, g in claims.groupby("carrier"):
            slug = carrier.split()[0].lower().replace("&", "")
            # scenarios: tower height sweep (strict peak floor), plus a "generous" site-inference scenario
            # that also treats weak local peaks (down to -100 dBm) as towers. Cells implausible under the
            # generous scenario are the robust findings.
            for h, floor in ((20.0, -80.0), (30.0, -80.0), (45.0, -80.0), (30.0, -100.0)):
                cfg = Config(name=area, bbox=a["bbox"], eval_margin_km=a["eval_margin_km"], tx_height_m=h,
                             peak_floor_dbm=floor, **CARRIER[carrier])
                sub = "" if (h, floor) == (30.0, -80.0) else (f"h{int(h)}" if floor == -80.0 else "generous")
                out = WORK / area / f"physics_{slug}" / sub
                r = run(g.reset_index(drop=True), cfg, out, sensitivity=(h == 30.0))
                r.pop("config")
                r["scenario"] = sub or "base"
                results.append(r)
                print(json.dumps({k: r[k] for k in ("area", "carrier", "cells", "sites_registered", "sites_inferred",
                                                    "evaluated", "implausible", "pct_consistent")}), "h=", h, "floor=", floor, flush=True)
    (WORK / "physics_results.json").write_text(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
