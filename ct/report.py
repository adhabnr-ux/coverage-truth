"""Collect every number the write-up quotes into results/ (JSON + a Markdown table).

    python -m ct.report
"""

from __future__ import annotations

import json
import shutil

import pandas as pd

from .common import ROOT, WORK

RES = ROOT / "results"


def physics_table(results: list[dict]) -> str:
    rows = {}
    for r in results:
        k = (r["area"], r["carrier"])
        rows.setdefault(k, {})[r["scenario"]] = r
    out = ["| Area | Carrier | Claimed cells | Fringe cells judged | Registered sites | Inferred sites (base / generous) "
           "| Implausible, base (20 / 30 / 45 m) | Implausible, generous | Consistent, base | Consistent, generous |",
           "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for (area, carrier), s in rows.items():
        b, g = s["base"], s.get("generous", {})
        out.append(f"| {area} | {carrier} | {b['cells']:,} | {b['evaluated']:,} | {b['sites_registered']} | "
                   f"{b['sites_inferred']} / {g.get('sites_inferred', '-')} | "
                   f"{s['h20']['implausible']} / {b['implausible']} / {s['h45']['implausible']} | "
                   f"{g.get('implausible', '-')} | {b['pct_consistent']}% | {g.get('pct_consistent', '-')}% |")
    return "\n".join(out)


def main():
    RES.mkdir(exist_ok=True)
    phys = json.loads((WORK / "physics_results.json").read_text())
    state = json.loads((WORK / "statewide_summary.json").read_text())
    cross = json.loads((WORK / "crosscheck.json").read_text())
    t = pd.read_parquet(WORK / "tiles_vs_claims.parquet")
    rob = t[t.robust & (t.claim_frac == 1)]
    state["robust_fully_claimed_tiles"] = int(len(rob))
    state["robust_contradictions_download"] = int((rob.contradiction & (rob.d_mbps < 5)).sum())
    state["robust_contradictions_upload_only"] = int((rob.contradiction & (rob.d_mbps >= 5)).sum())
    cells = pd.read_parquet(WORK / "fcc_cells_ctx.parquet")
    tr = cells.groupby("on_tribal").tested.mean().mul(100).round(2)
    state["pct_claimed_area_tested_tribal"] = float(tr.get(True))
    state["pct_claimed_area_tested_non_tribal"] = float(tr.get(False))
    by_nation = (cells[cells.on_tribal].groupby("tribal").agg(cells=("tested", "size"), pct_tested=("tested", "mean"))
                 .assign(pct_tested=lambda d: (100 * d.pct_tested).round(2)).sort_values("cells", ascending=False))
    by_nation.head(12).to_csv(RES / "tribal_verification_gap.csv")
    s = pd.read_csv(WORK / "schools_vs_claims.csv")
    s[s.tests2km.fillna(0) == 0].to_csv(RES / "schools_zero_tests_2km.csv", index=False)
    rob[rob.contradiction].to_csv(RES / "robust_contradiction_tiles.csv", index=False)
    (RES / "summary.json").write_text(json.dumps(dict(statewide=state, physics=phys, sionna_crosscheck=cross),
                                                  indent=2, default=str))
    (RES / "physics_table.md").write_text(physics_table(phys) + "\n")
    for a in ("whiteriver", "blackmesa"):
        for d in (WORK / a).glob("physics_*"):
            dst = RES / a / d.name
            dst.mkdir(parents=True, exist_ok=True)
            for f in ("result.json", "sites.csv"):
                shutil.copy(d / f, dst / f)
            g = d / "generous"
            if g.exists():
                shutil.copy(g / "result.json", dst / "result_generous.json")
                shutil.copy(g / "sites.csv", dst / "sites_generous.csv")
    print(physics_table(phys))
    print(json.dumps(state, indent=1))


if __name__ == "__main__":
    main()
